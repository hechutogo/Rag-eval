import asyncio
import uuid
from .schema import EvalSample, EvalDataset
from ..judge.base import LLMJudge

_GEN_PROMPT = """你是一个专业的问答数据集构建专家。
基于以下文档片段，生成 {n} 个高质量的问题和对应的参考答案，用于评测知识库检索系统。

要求：
1. 问题必须能从文档中找到明确答案
2. 包含不同类型：事实性（factual）、推理性（reasoning）、比较性（comparison）
3. 同时生成一个该文档无法回答的问题（unanswerable），answer 填 "该文档中未提及此信息"
4. 参考答案要简洁准确

文档标题：{headers}
文档内容：
{content}

严格按以下 JSON 格式输出：
{{
  "items": [
    {{
      "question": "问题文本",
      "answer": "参考答案",
      "type": "factual | reasoning | comparison | unanswerable",
      "difficulty": "easy | medium | hard"
    }}
  ]
}}"""


class DatasetGenerator:
    def __init__(self, judge: LLMJudge, adapter=None):
        self.judge = judge
        self.adapter = adapter

    async def generate(
        self,
        knowledge_hub_id: str,
        file_id_list: list[str],
        questions_per_chunk: int = 2,
        max_chunks: int = 50,
        dataset_name: str = "Auto Generated Dataset",
        chunk_ids: list[str] | None = None,
        progress_cb=None,
    ) -> EvalDataset:
        """
        遍历知识库切片，用 LLM 自动生成问答对，返回 EvalDataset。
        progress_cb(done, total): 可选进度回调
        chunk_ids: 若指定，只处理这些 chunk（忽略 file_id_list）
        """
        samples: list[EvalSample] = []

        # 收集所有待处理 chunks
        all_chunks: list[dict] = []
        if chunk_ids:
            # 直接用指定的 chunk_ids，从 file_id_list 的第一个 file 拉取后过滤
            for file_id in file_id_list:
                raw = await self.adapter.get_chunks_for_file(file_id, page_size=max_chunks)
                all_chunks.extend(raw)
            all_chunks = [c for c in all_chunks if c.get("id") in chunk_ids]
        else:
            for file_id in file_id_list:
                raw = await self.adapter.get_chunks_for_file(file_id, page_size=max_chunks)
                all_chunks.extend(raw)

        total = len(all_chunks)
        done = 0

        for chunk in all_chunks:
            content = (
                chunk.get("content")
                or chunk.get("paragraph_context")
                or chunk.get("large_paragraph_llm_summary")
                or ""
            )
            headers = chunk.get("headers") or ""
            if not content.strip():
                done += 1
                if progress_cb:
                    await progress_cb(done, total)
                continue

            prompt = _GEN_PROMPT.format(
                n=questions_per_chunk,
                headers=headers,
                content=content[:2000],
            )
            try:
                raw = await self.judge._call_json(prompt)
                for item in raw.get("items", []):
                    if not item.get("question") or not item.get("answer"):
                        continue
                    samples.append(EvalSample(
                        id=uuid.uuid4().hex,
                        question=item["question"],
                        reference_answer=item["answer"],
                        relevant_chunk_ids=[chunk["id"]] if chunk.get("id") else [],
                        knowledge_hub_id=knowledge_hub_id,
                        source_file_id=chunk.get("file_id", ""),
                        metadata={
                            "type": item.get("type", "factual"),
                            "difficulty": item.get("difficulty", "medium"),
                            "chunk_id": chunk.get("id", ""),
                            "chunk_headers": chunk.get("headers", ""),
                            "chunk_content_preview": content[:500] if content else "",
                            "file_name": chunk.get("file_name", ""),
                        },
                    ))
            except Exception:
                pass

            done += 1
            if progress_cb:
                await progress_cb(done, total)
            await asyncio.sleep(0.1)

        return EvalDataset(
            id=uuid.uuid4().hex,
            name=dataset_name,
            description=f"Auto generated from {total} chunk(s), {len(samples)} samples",
            samples=samples,
        )
