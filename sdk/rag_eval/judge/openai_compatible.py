import asyncio
import json
from openai import AsyncOpenAI
from .base import LLMJudge

# ── Prompts ───────────────────────────────────────────────────────────────────

_DECOMPOSE_PROMPT = """请将以下回答分解为独立的原子声明列表，每条声明是一个不可再分的事实陈述。
回答：{answer}
只输出 JSON 数组，格式：["声明1", "声明2", ...]"""

_VERIFY_CLAIM_PROMPT = """参考资料：
{context}

声明：{claim}

上述声明是否可以从参考资料中推导出来？只回答 yes 或 no。"""

_RELEVANCE_GEN_PROMPT = """基于以下回答，生成 3 个该回答可能在回答的问题。
回答：{answer}
只输出 JSON 数组，格式：["问题1", "问题2", "问题3"]"""

_CORRECTNESS_PROMPT = """请评估以下回答与参考答案的事实一致程度。

参考答案：{reference}
待评估回答：{answer}

请从以下维度评估：
1. 事实一致性：回答中的事实与参考答案是否一致
2. 信息完整性：回答是否覆盖了参考答案的关键信息
3. 有无错误信息：回答是否包含参考答案中没有的错误内容

输出 JSON：
{{"score": 0到1之间的小数, "reason": "简短理由", "factual_tp": 正确事实数, "factual_fp": 错误事实数, "factual_fn": 遗漏事实数}}"""

_GROUNDEDNESS_PROMPT = """以下是检索到的切片列表（带编号）：
{numbered_chunks}

AI 回答：{answer}

请将回答分解为原子声明，并为每条声明标注支撑它的切片编号（无支撑则填 null）。
输出 JSON：{{"claims": [{{"text": "声明内容", "source_chunk_index": 1}}, {{"text": "声明内容", "source_chunk_index": null}}]}}"""

_CONTEXT_PRECISION_PROMPT = """问题：{question}
参考答案：{ground_truth}

以下是检索系统返回的文档片段列表：
{chunks_text}

请判断每个片段对于回答该问题是否有用。
输出 JSON：{{"results": [{{"index": 1, "useful": true, "reason": "简短理由"}}]}}"""

_CONTEXT_RECALL_PROMPT = """参考答案：{ground_truth}

检索到的文档内容（合并）：
{retrieved_context}

请将参考答案拆分为若干独立陈述，判断每个陈述是否能在检索文档中找到支撑。
输出 JSON：{{"statements": [{{"text": "陈述内容", "supported": true}}]}}"""


class OpenAICompatibleJudge(LLMJudge):
    """
    兼容所有 OpenAI 协议的模型：DeepSeek / Qwen / OpenAI / Azure OpenAI
    评判逻辑使用中文 prompt，适合中文 RAG 场景
    """

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        embed_base_url: str = "",
        embed_api_key: str = "",
        embed_model: str = "text-embedding-3-small",
    ):
        self.client = AsyncOpenAI(
            base_url=base_url or None,
            api_key=api_key,
        )
        self.model = model
        # 独立的 embedding client（可与 LLM 使用不同的 endpoint）
        self.embed_client = AsyncOpenAI(
            base_url=embed_base_url or base_url or None,
            api_key=embed_api_key or api_key,
        )
        self.embed_model = embed_model

    async def _call(self, prompt: str) -> str:
        resp = await self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
        )
        return (resp.choices[0].message.content or "").strip()

    async def _call_json(self, prompt: str) -> dict | list:
        resp = await self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
        )
        raw = (resp.choices[0].message.content or "").strip()
        # 去掉 markdown 代码块包装（```json ... ``` 或 ``` ... ```）
        if raw.startswith("```"):
            lines = raw.splitlines()
            # 去掉首行（```json 或 ```）和末行（```）
            inner = lines[1:] if lines[0].startswith("```") else lines
            if inner and inner[-1].strip() == "```":
                inner = inner[:-1]
            raw = "\n".join(inner).strip()
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            # 尝试提取第一个 JSON 对象或数组
            import re
            m = re.search(r'(\{[\s\S]*\}|\[[\s\S]*\])', raw)
            if m:
                try:
                    return json.loads(m.group(1))
                except json.JSONDecodeError:
                    pass
            return {}

    # ── Faithfulness（两步法）────────────────────────────────────────────────

    async def score_faithfulness(self, answer: str, context: list[str]) -> tuple[float, dict]:
        if not answer or not context:
            return 0.0, {}

        # Step 1: 分解为原子声明
        raw_claims = await self._call_json(
            _DECOMPOSE_PROMPT.format(answer=answer)
        )
        if isinstance(raw_claims, list):
            claims = raw_claims
        else:
            claims = raw_claims.get("items", []) or raw_claims.get("claims", [])

        if not claims:
            return 0.0, {"claims": []}

        context_text = "\n\n".join(c[:800] for c in context)

        # Step 2: 逐条验证（并发）
        async def _verify(claim: str) -> bool:
            result = await self._call(
                _VERIFY_CLAIM_PROMPT.format(context=context_text, claim=claim)
            )
            return "yes" in result.lower()

        results = await asyncio.gather(*[_verify(c) for c in claims])
        supported = sum(results)
        score = round(supported / len(claims), 4)

        detail = {
            "claims": [
                {"text": c, "supported": bool(r)}
                for c, r in zip(claims, results)
            ]
        }
        return score, detail

    # ── Answer Relevance（反向生成 + 语义相似）───────────────────────────────

    async def score_relevance(self, question: str, answer: str) -> tuple[float, dict]:
        if not answer:
            return 0.0, {}

        raw = await self._call_json(
            _RELEVANCE_GEN_PROMPT.format(answer=answer)
        )
        if isinstance(raw, list):
            gen_questions = raw
        else:
            gen_questions = raw.get("items", []) or raw.get("questions", [])

        if not gen_questions:
            return 0.0, {}

        # 用 embedding cosine 相似度计算
        scores = await asyncio.gather(*[
            self._embedding_similarity(question, q) for q in gen_questions
        ])
        avg = round(sum(scores) / len(scores), 4)
        return avg, {"generated_questions": gen_questions, "similarities": list(scores)}

    async def _embedding_similarity(self, text_a: str, text_b: str) -> float:
        import numpy as np
        resp = await self.embed_client.embeddings.create(
            model=self.embed_model,
            input=[text_a, text_b],
        )
        a = np.array(resp.data[0].embedding)
        b = np.array(resp.data[1].embedding)
        cos = float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-9))
        return round(max(0.0, cos), 4)

    # ── Answer Correctness ───────────────────────────────────────────────────

    async def score_correctness(self, answer: str, reference: str) -> tuple[float, dict]:
        if not answer or not reference:
            return 0.0, {}

        raw = await self._call_json(
            _CORRECTNESS_PROMPT.format(reference=reference, answer=answer)
        )
        try:
            score = float(raw.get("score", 0.0))
        except (TypeError, ValueError):
            score = 0.0

        tp = raw.get("factual_tp", 0) or 0
        fp = raw.get("factual_fp", 0) or 0
        fn = raw.get("factual_fn", 0) or 0
        f1 = (2 * tp / (2 * tp + fp + fn)) if (2 * tp + fp + fn) > 0 else 0.0
        final = round(0.75 * f1 + 0.25 * score, 4)
        return final, raw

    # ── Groundedness（可溯源性）──────────────────────────────────────────────

    async def score_groundedness(self, answer: str, chunks: list[dict]) -> tuple[float, dict]:
        if not answer or not chunks:
            return 0.0, {}

        numbered = "\n".join(
            f"[{i+1}] {c.get('content', '')[:500]}" for i, c in enumerate(chunks)
        )
        raw = await self._call_json(
            _GROUNDEDNESS_PROMPT.format(numbered_chunks=numbered, answer=answer)
        )
        claims = raw.get("claims", [])
        if not claims:
            return 0.0, raw

        grounded = sum(1 for c in claims if c.get("source_chunk_index") is not None)
        score = round(grounded / len(claims), 4)
        return score, raw

    # ── Context Precision ────────────────────────────────────────────────────

    async def score_context_precision(
        self, question: str, ground_truth: str, retrieved_chunks: list[str]
    ) -> tuple[float, dict]:
        if not retrieved_chunks or not ground_truth:
            return 0.0, {}

        chunks_text = "\n".join(f"[{i+1}] {c[:500]}" for i, c in enumerate(retrieved_chunks))
        raw = await self._call_json(
            _CONTEXT_PRECISION_PROMPT.format(
                question=question, ground_truth=ground_truth, chunks_text=chunks_text
            )
        )
        results = raw.get("results", [])
        if not results:
            return 0.0, raw

        useful_flags = [
            r.get("useful", False)
            for r in sorted(results, key=lambda x: x.get("index", 0))
        ]
        # Weighted precision@k
        score = sum(
            (sum(useful_flags[:k+1]) / (k+1)) * useful_flags[k]
            for k in range(len(useful_flags))
        ) / max(sum(useful_flags), 1)
        return round(min(score, 1.0), 4), raw

    # ── Context Recall ───────────────────────────────────────────────────────

    async def score_context_recall(
        self, ground_truth: str, retrieved_chunks: list[str]
    ) -> tuple[float, dict]:
        if not retrieved_chunks or not ground_truth:
            return 0.0, {}

        retrieved_context = "\n\n".join(c[:800] for c in retrieved_chunks)
        raw = await self._call_json(
            _CONTEXT_RECALL_PROMPT.format(
                ground_truth=ground_truth, retrieved_context=retrieved_context
            )
        )
        statements = raw.get("statements", [])
        if not statements:
            return 0.0, raw

        supported = sum(1 for s in statements if s.get("supported"))
        return round(supported / len(statements), 4), raw
