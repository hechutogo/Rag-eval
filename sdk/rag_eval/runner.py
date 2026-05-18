import asyncio
import uuid
from dataclasses import dataclass
from typing import Callable

from .adapters.base import RAGAdapter
from .judge.base import LLMJudge
from .evaluators.retrieval import hit_rate, mrr, ndcg
from .dataset.schema import EvalDataset, EvalSample
from .report import EvalReport, SampleResult


RETRIEVAL_METRIC_KEYS = {"hit_rate", "mrr", "ndcg", "context_precision", "context_recall"}
GENERATION_METRIC_KEYS = {"faithfulness", "answer_relevance", "answer_correctness", "groundedness"}


@dataclass
class RunConfig:
    agent_id: str
    knowledge_hub_id: str
    top_k: int = 10
    eval_retrieval: bool = True
    eval_generation: bool = True
    selected_metrics: list[str] | None = None
    file_id_list: list[str] | None = None
    concurrency: int = 3                    # 并发评测样本数
    faithfulness_threshold: float = 0.7    # 低于此值视为幻觉

    def should_eval(self, metric_key: str) -> bool:
        """判断是否需要计算某个指标"""
        if self.selected_metrics:
            return metric_key in self.selected_metrics
        # 向后兼容：未指定 selected_metrics 时按 eval_retrieval/eval_generation 开关
        if metric_key in RETRIEVAL_METRIC_KEYS:
            return self.eval_retrieval
        if metric_key in GENERATION_METRIC_KEYS:
            return self.eval_generation
        return True

    @property
    def need_retrieval(self) -> bool:
        if self.selected_metrics:
            return bool(set(self.selected_metrics) & RETRIEVAL_METRIC_KEYS)
        return self.eval_retrieval

    @property
    def need_generation(self) -> bool:
        if self.selected_metrics:
            return bool(set(self.selected_metrics) & GENERATION_METRIC_KEYS)
        return self.eval_generation


class EvalRunner:
    def __init__(self, adapter: RAGAdapter, judge: LLMJudge):
        self.adapter = adapter
        self.judge = judge

    async def run(
        self,
        dataset: EvalDataset | str,
        config: RunConfig,
        progress_cb: Callable[[int, int], None] | None = None,
    ) -> EvalReport:
        """
        运行完整评测流程。

        Args:
            dataset: EvalDataset 对象或 JSON 文件路径
            config: 评测配置
            progress_cb: 进度回调 (finished, total)
        """
        if isinstance(dataset, str):
            import json
            with open(dataset, encoding="utf-8") as f:
                dataset = EvalDataset.from_dict(json.load(f))

        samples = dataset.samples
        total = len(samples)
        results: list[SampleResult] = []
        finished = 0

        sem = asyncio.Semaphore(config.concurrency)

        async def _eval_one(sample: EvalSample) -> SampleResult:
            async with sem:
                return await self._eval_sample(sample, config)

        tasks = [_eval_one(s) for s in samples]

        for coro in asyncio.as_completed(tasks):
            result = await coro
            results.append(result)
            finished += 1
            if progress_cb:
                progress_cb(finished, total)

        return self._build_report(
            task_id=uuid.uuid4().hex,
            dataset=dataset,
            results=results,
            config=config,
        )

    async def _eval_sample(self, sample: EvalSample, config: RunConfig) -> SampleResult:
        result = SampleResult(
            sample_id=sample.id,
            question=sample.question,
            reference_answer=sample.reference_answer,
        )
        try:
            # ── Step 1: Retrieval ─────────────────────────────────────────
            if config.need_retrieval:
                chunks = await self.adapter.retrieve(
                    query=sample.question,
                    knowledge_hub_id=config.knowledge_hub_id,
                    top_k=config.top_k,
                    file_id_list=config.file_id_list,
                )
                result.retrieved_chunk_ids = [c.chunk_id for c in chunks]
                result.retrieved_chunks = [c.content for c in chunks]

                # Rule-based metrics
                if sample.relevant_chunk_ids:
                    if config.should_eval("hit_rate"):
                        result.hit_rate = hit_rate(result.retrieved_chunk_ids, sample.relevant_chunk_ids)
                    if config.should_eval("mrr"):
                        result.mrr = mrr(result.retrieved_chunk_ids, sample.relevant_chunk_ids)
                    if config.should_eval("ndcg"):
                        result.ndcg = ndcg(result.retrieved_chunk_ids, sample.relevant_chunk_ids, k=config.top_k)

                # LLM-as-Judge retrieval metrics
                if sample.reference_answer and result.retrieved_chunks:
                    if config.should_eval("context_precision"):
                        cp, raw_cp = await self.judge.score_context_precision(
                            sample.question, sample.reference_answer, result.retrieved_chunks
                        )
                        result.context_precision = cp
                        result.judge_detail["context_precision"] = raw_cp

                    if config.should_eval("context_recall"):
                        cr, raw_cr = await self.judge.score_context_recall(
                            sample.reference_answer, result.retrieved_chunks
                        )
                        result.context_recall = cr
                        result.judge_detail["context_recall"] = raw_cr

            # ── Step 2: Generation ────────────────────────────────────────
            if config.need_generation:
                agent_resp = await self.adapter.chat(
                    query=sample.question,
                    agent_id=config.agent_id,
                )
                result.agent_answer = agent_resp.answer
                result.latency_ms = agent_resp.latency_ms

                # 若检索阶段被跳过，单独 retrieve 一次以支撑生成指标评判
                if not result.retrieved_chunks:
                    try:
                        chunks = await self.adapter.retrieve(
                            query=sample.question,
                            knowledge_hub_id=config.knowledge_hub_id,
                            top_k=config.top_k,
                            file_id_list=config.file_id_list,
                        )
                        result.retrieved_chunk_ids = [c.chunk_id for c in chunks]
                        result.retrieved_chunks = [c.content for c in chunks]
                    except Exception:
                        pass

                if result.agent_answer and result.retrieved_chunks:
                    if config.should_eval("faithfulness"):
                        faith, raw_faith = await self.judge.score_faithfulness(
                            result.agent_answer, result.retrieved_chunks
                        )
                        result.faithfulness = faith
                        result.judge_detail["faithfulness"] = raw_faith

                    if config.should_eval("answer_relevance"):
                        rel, raw_rel = await self.judge.score_relevance(
                            sample.question, result.agent_answer
                        )
                        result.answer_relevance = rel
                        result.judge_detail["answer_relevance"] = raw_rel

                    if config.should_eval("groundedness"):
                        ground, raw_ground = await self.judge.score_groundedness(
                            result.agent_answer,
                            [{"content": c} for c in result.retrieved_chunks],
                        )
                        result.groundedness = ground
                        result.judge_detail["groundedness"] = raw_ground

                    if config.should_eval("answer_correctness") and sample.reference_answer:
                        corr, raw_corr = await self.judge.score_correctness(
                            result.agent_answer, sample.reference_answer
                        )
                        result.answer_correctness = corr
                        result.judge_detail["answer_correctness"] = raw_corr

        except Exception as exc:
            result.error = str(exc)

        return result

    def _build_report(
        self,
        task_id: str,
        dataset: EvalDataset,
        results: list[SampleResult],
        config: RunConfig,
    ) -> EvalReport:
        def _avg(vals: list[float]) -> float | None:
            v = [x for x in vals if x is not None]
            return round(sum(v) / len(v), 4) if v else None

        def _collect(attr: str) -> list[float]:
            return [getattr(r, attr) for r in results if getattr(r, attr) is not None]

        avg_hit_rate          = _avg(_collect("hit_rate"))
        avg_mrr               = _avg(_collect("mrr"))
        avg_ndcg              = _avg(_collect("ndcg"))
        avg_ctx_prec          = _avg(_collect("context_precision"))
        avg_ctx_rec           = _avg(_collect("context_recall"))
        avg_faithfulness      = _avg(_collect("faithfulness"))
        avg_answer_relevance  = _avg(_collect("answer_relevance"))
        avg_answer_correctness= _avg(_collect("answer_correctness"))
        avg_groundedness      = _avg(_collect("groundedness"))

        # RAG Score: harmonic mean of four core metrics
        core = [s for s in [avg_faithfulness, avg_answer_relevance, avg_ctx_prec, avg_ctx_rec]
                if s is not None and s > 0]
        rag_score = round(len(core) / sum(1 / s for s in core), 4) if core else None

        # Hallucination Rate
        faith_vals = _collect("faithfulness")
        hallucination_rate = (
            round(sum(1 for f in faith_vals if f < config.faithfulness_threshold) / len(faith_vals), 4)
            if faith_vals else None
        )

        return EvalReport(
            task_id=task_id,
            dataset_name=dataset.name,
            sample_count=len(results),
            results=results,
            avg_hit_rate=avg_hit_rate,
            avg_mrr=avg_mrr,
            avg_ndcg=avg_ndcg,
            avg_context_precision=avg_ctx_prec,
            avg_context_recall=avg_ctx_rec,
            avg_faithfulness=avg_faithfulness,
            avg_answer_relevance=avg_answer_relevance,
            avg_answer_correctness=avg_answer_correctness,
            avg_groundedness=avg_groundedness,
            rag_score=rag_score,
            hallucination_rate=hallucination_rate,
        )
