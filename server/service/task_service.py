import asyncio
import json
import sys
from pathlib import Path

# Make sdk and server root importable
_server_root = Path(__file__).parent.parent
sys.path.insert(0, str(_server_root))
sys.path.insert(0, str(_server_root.parent / "sdk"))

from rag_eval.adapters.dagent import DagentAdapter
from rag_eval.judge.openai_compatible import OpenAICompatibleJudge
from rag_eval.runner import EvalRunner, RunConfig
from rag_eval.dataset.schema import EvalDataset, EvalSample
from rag_eval.dataset.generator import DatasetGenerator
from models.db import get_db, _now, _id


async def _get_platform_config(db, config_id: str) -> dict:
    rows = await db.execute_fetchall(
        "SELECT * FROM platform_config WHERE id=?", (config_id,)
    )
    if not rows:
        raise ValueError(f"Platform config {config_id} not found")
    return dict(rows[0])


async def _get_judge_config(db, config_id: str) -> dict:
    rows = await db.execute_fetchall(
        "SELECT * FROM judge_config WHERE id=?", (config_id,)
    )
    if not rows:
        raise ValueError(f"Judge config {config_id} not found")
    return dict(rows[0])


async def _load_dataset(db, dataset_id: str) -> EvalDataset:
    ds_rows = await db.execute_fetchall(
        "SELECT * FROM eval_dataset WHERE id=?", (dataset_id,)
    )
    if not ds_rows:
        raise ValueError(f"Dataset {dataset_id} not found")
    ds = dict(ds_rows[0])

    sample_rows = await db.execute_fetchall(
        "SELECT * FROM eval_sample WHERE dataset_id=?", (dataset_id,)
    )
    samples = [
        EvalSample(
            id=r["id"],
            question=r["question"],
            reference_answer=r["reference_answer"],
            relevant_chunk_ids=json.loads(r["relevant_chunk_ids"] or "[]"),
            knowledge_hub_id=r["knowledge_hub_id"],
            source_file_id=r["source_file_id"],
            metadata=json.loads(r["metadata"] or "{}"),
        )
        for r in sample_rows
    ]
    return EvalDataset(id=ds["id"], name=ds["name"], description=ds.get("description", ""), samples=samples)


async def run_eval_task(task_id: str):
    """Background coroutine: runs the full eval loop for a task."""
    async with get_db() as db:
        task_rows = await db.execute_fetchall(
            "SELECT * FROM eval_task WHERE id=?", (task_id,)
        )
        if not task_rows:
            return
        task = dict(task_rows[0])

        await db.execute(
            "UPDATE eval_task SET status='running' WHERE id=?", (task_id,)
        )
        await db.commit()

        try:
            platform_cfg = await _get_platform_config(db, task["platform_config_id"])
            judge_cfg = await _get_judge_config(db, task["judge_config_id"])
            dataset = await _load_dataset(db, task["dataset_id"])
        except Exception as exc:
            await db.execute(
                "UPDATE eval_task SET status='failed', error_message=? WHERE id=?",
                (str(exc), task_id),
            )
            await db.commit()
            return

    adapter = DagentAdapter(
        base_url=platform_cfg["base_url"],
        org_id=platform_cfg.get("org_id", ""),
        token=platform_cfg.get("token", ""),
    )
    judge = OpenAICompatibleJudge(
        base_url=judge_cfg["base_url"],
        api_key=judge_cfg["api_key"],
        model=judge_cfg["model"],
        embed_base_url=judge_cfg.get("embed_base_url", ""),
        embed_api_key=judge_cfg.get("embed_api_key", ""),
        embed_model=judge_cfg.get("embed_model", "text-embedding-3-small"),
    )
    run_cfg = RunConfig(
        agent_id=task["agent_id"],
        knowledge_hub_id=task["knowledge_hub_id"],
        top_k=task["top_k"],
        eval_retrieval=bool(task["eval_retrieval"]),
        eval_generation=bool(task["eval_generation"]),
        selected_metrics=json.loads(task.get("selected_metrics") or "[]") or None,
        file_id_list=json.loads(task["file_id_list"] or "[]") or None,
        concurrency=task["concurrency"],
    )

    finished = 0
    total = len(dataset.samples)

    async with get_db() as db:
        await db.execute(
            "UPDATE eval_task SET total=? WHERE id=?", (total, task_id)
        )
        await db.commit()

    async def _progress(done, _total):
        nonlocal finished
        finished = done
        async with get_db() as db:
            await db.execute(
                "UPDATE eval_task SET progress=? WHERE id=?", (done, task_id)
            )
            await db.commit()

    runner = EvalRunner(adapter=adapter, judge=judge)

    try:
        report = await runner.run(dataset, run_cfg, progress_cb=lambda d, t: asyncio.create_task(_progress(d, t)))
    except Exception as exc:
        async with get_db() as db:
            await db.execute(
                "UPDATE eval_task SET status='failed', error_message=? WHERE id=?",
                (str(exc), task_id),
            )
            await db.commit()
        return

    # Generate interpretation using judge LLM
    interpretation = ""
    try:
        # Format metrics for prompt
        def fmt(val, fmt_str='.2%'):
            return f"{val:{fmt_str}}" if val is not None else 'N/A'

        interp_prompt = f"""请对以下 RAG 系统评测结果进行解读分析，用 2-3 段中文总结：

评测样本数：{report.sample_count}

检索层指标：
- 命中率 (Hit Rate): {fmt(report.avg_hit_rate)}
- 平均倒数排名 (MRR): {fmt(report.avg_mrr, '.4f')}
- 归一化折损累积增益 (NDCG): {fmt(report.avg_ndcg, '.4f')}
- 上下文精确度 (Context Precision): {fmt(report.avg_context_precision)}
- 上下文召回率 (Context Recall): {fmt(report.avg_context_recall)}

生成层指标：
- 忠实度 (Faithfulness): {fmt(report.avg_faithfulness)}
- 回答相关性 (Answer Relevance): {fmt(report.avg_answer_relevance, '.4f')}
- 回答正确性 (Answer Correctness): {fmt(report.avg_answer_correctness, '.4f')}
- 可溯源性 (Groundedness): {fmt(report.avg_groundedness)}

综合指标：
- RAG Score: {fmt(report.rag_score)}
- 幻觉发生率: {fmt(report.hallucination_rate)}

请从以下角度分析：
1. 整体表现评价（优势和亮点）
2. 存在的主要问题和不足
3. 具体改进建议

要求：语言简洁专业，每段 2-3 句话，总字数 200-300 字。"""

        interpretation = await judge._call(interp_prompt)
    except Exception:
        interpretation = "评测结果解释生成失败"

    # Persist results and report
    async with get_db() as db:
        for r in report.results:
            await db.execute(
                """INSERT INTO eval_result
                   (id,task_id,sample_id,question,reference_answer,retrieved_chunks,
                    agent_answer,hit_rate,mrr,ndcg,context_precision,context_recall,
                    faithfulness,answer_relevance,answer_correctness,groundedness,
                    latency_ms,judge_detail,error)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    _id(), task_id, r.sample_id, r.question, r.reference_answer,
                    json.dumps(r.retrieved_chunks, ensure_ascii=False),
                    r.agent_answer, r.hit_rate, r.mrr, r.ndcg,
                    r.context_precision, r.context_recall,
                    r.faithfulness, r.answer_relevance, r.answer_correctness,
                    r.groundedness, r.latency_ms,
                    json.dumps(r.judge_detail, ensure_ascii=False),
                    r.error,
                ),
            )

        await db.execute(
            """INSERT OR REPLACE INTO eval_report
               (id,task_id,sample_count,avg_hit_rate,avg_mrr,avg_ndcg,
                avg_context_precision,avg_context_recall,avg_faithfulness,
                avg_answer_relevance,avg_answer_correctness,avg_groundedness,
                rag_score,hallucination_rate,interpretation,created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                _id(), task_id, report.sample_count,
                report.avg_hit_rate, report.avg_mrr, report.avg_ndcg,
                report.avg_context_precision, report.avg_context_recall,
                report.avg_faithfulness, report.avg_answer_relevance,
                report.avg_answer_correctness, report.avg_groundedness,
                report.rag_score, report.hallucination_rate, interpretation, _now(),
            ),
        )

        await db.execute(
            "UPDATE eval_task SET status='done', finished_at=?, progress=total WHERE id=?",
            (_now(), task_id),
        )
        await db.commit()


async def run_generate_task(params: dict):
    """Background coroutine: generates dataset samples via LLM."""
    gen_task_id = params.get("gen_task_id")

    async def _update_gen_progress(done: int, total: int):
        if not gen_task_id:
            return
        async with get_db() as db:
            await db.execute(
                "UPDATE generate_task SET progress=?, total=?, status='running' WHERE id=?",
                (done, total, gen_task_id),
            )
            await db.commit()

    async with get_db() as db:
        platform_cfg = await _get_platform_config(db, params["platform_config_id"])
        judge_cfg = await _get_judge_config(db, params["judge_config_id"])

    adapter = DagentAdapter(
        base_url=platform_cfg["base_url"],
        org_id=platform_cfg.get("org_id", ""),
        token=platform_cfg.get("token", ""),
    )
    judge = OpenAICompatibleJudge(
        base_url=judge_cfg["base_url"],
        api_key=judge_cfg["api_key"],
        model=judge_cfg["model"],
        embed_base_url=judge_cfg.get("embed_base_url", ""),
        embed_api_key=judge_cfg.get("embed_api_key", ""),
        embed_model=judge_cfg.get("embed_model", "text-embedding-3-small"),
    )

    try:
        gen = DatasetGenerator(judge=judge, adapter=adapter)
        dataset = await gen.generate(
            knowledge_hub_id=params["knowledge_hub_id"],
            file_id_list=params["file_id_list"],
            questions_per_chunk=params.get("questions_per_chunk", 2),
            max_chunks=params.get("max_chunks", 50),
            chunk_ids=params.get("chunk_ids") or None,
            progress_cb=_update_gen_progress,
        )
    except Exception as exc:
        if gen_task_id:
            async with get_db() as db:
                await db.execute(
                    "UPDATE generate_task SET status='failed', error_message=?, finished_at=? WHERE id=?",
                    (str(exc), _now(), gen_task_id),
                )
                await db.commit()
        return

    async with get_db() as db:
        for s in dataset.samples:
            await db.execute(
                """INSERT INTO eval_sample
                   (id,dataset_id,question,reference_answer,relevant_chunk_ids,
                    knowledge_hub_id,source_file_id,metadata)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (
                    s.id, params["dataset_id"], s.question, s.reference_answer,
                    json.dumps(s.relevant_chunk_ids, ensure_ascii=False),
                    s.knowledge_hub_id, s.source_file_id,
                    json.dumps(s.metadata, ensure_ascii=False),
                ),
            )
        await db.execute(
            "UPDATE eval_dataset SET sample_count=sample_count+? WHERE id=?",
            (len(dataset.samples), params["dataset_id"]),
        )
        if gen_task_id:
            await db.execute(
                "UPDATE generate_task SET status='done', progress=total, finished_at=? WHERE id=?",
                (_now(), gen_task_id),
            )
        await db.commit()
