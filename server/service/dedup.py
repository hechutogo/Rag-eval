# -*- coding: utf-8 -*-
"""
Question deduplication service.

使用 正则归一化 + 向量余弦相似度 两阶段查重：
1) 正则归一化：去除标点/空白/常见中文疑问助词后字符串完全相等，判为重复（sim=1.0）。
2) 向量相似度：对归一化后仍不同的问题，批量 embedding + 计算 cosine；
   >= similarity_threshold 判为重复。

相比 LLM 查重：更快、更便宜、结果确定，且可批量。
"""
import asyncio
import re
from typing import Callable, Optional

import numpy as np


# 空白 + ASCII/中英文全角标点
_PUNCT_RE = re.compile(
    r'[\s　 -⁯　-〿＀-￯'
    r'\-_=+*&^%$#@!\\/?.,;:\'"`~<>()\[\]{}]+'
)
# 结尾的疑问助词和语气词
_TAIL_PARTICLE_RE = re.compile(r'(?:吗|呢|啊|呀|哪|么|嘛|吧)+[?？。!！]*$')
# 开头的礼貌/引导词
_LEADING_ASK_RE = re.compile(r'^(?:请问一下|请问|问一下|那么|然后|所以)')


def _normalize(text: str) -> str:
    """问题文本的规范形式（用于正则查重）。"""
    if not text:
        return ""
    s = text.strip().lower()
    s = _LEADING_ASK_RE.sub("", s)
    s = _TAIL_PARTICLE_RE.sub("", s)
    s = _PUNCT_RE.sub("", s)
    return s


def _regex_duplicate_id(
    new_question: str,
    existing_questions: list[tuple[str, str]],
) -> Optional[str]:
    """规范化后的字符串与已有问题完全相等则判重，返回该已有问题 id。"""
    norm_new = _normalize(new_question)
    if not norm_new:
        return None
    for qid, existing_q in existing_questions:
        if _normalize(existing_q) == norm_new:
            return qid
    return None


async def _embed_texts(
    embed_client,
    model: str,
    texts: list[str],
    batch_size: int = 64,
) -> list[np.ndarray]:
    """批量 embedding，返回 L2 归一化后的向量列表（顺序与输入一致）。"""
    if not texts:
        return []
    out: list[np.ndarray] = []
    for i in range(0, len(texts), batch_size):
        batch = texts[i:i + batch_size]
        resp = await embed_client.embeddings.create(model=model, input=batch)
        for item in resp.data:
            v = np.asarray(item.embedding, dtype=np.float32)
            n = np.linalg.norm(v)
            if n > 0:
                v = v / n
            out.append(v)
    return out


async def deduplicate_questions_by_chunk(
    new_questions_by_chunk: dict[str, list[dict]],  # {chunk_id: [{id, question, ...}]}
    existing_questions_by_chunk: dict[str, list[tuple[str, str]]],  # {chunk_id: [(id, question)]}
    embed_client,
    embed_model: str,
    similarity_threshold: float = 0.85,
    max_parallel_chunks: int = 5,
    stop_check: Optional[Callable[[], bool]] = None,
    pause_check: Optional[Callable[[], bool]] = None,  # New: check if paused
    on_progress: Optional[Callable] = None,  # async callback(done, total)
) -> dict[str, tuple[Optional[str], float]]:
    """
    按切片并行查重。

    对每个切片：
      - 先用正则归一化做精确查重（新 vs 已有，新 vs 新同批）。
      - 剩余的问题批量 embedding，逐一与已有问题、该批内更早的问题计算 cosine，
        取最大值；>= threshold 判重。

    Returns:
        {new_question_id: (dup_of_id_or_None, similarity)}
    """
    chunk_sem = asyncio.Semaphore(max_parallel_chunks)
    results: dict[str, tuple[Optional[str], float]] = {}
    stopped = False
    done_count = 0
    total = sum(len(qs) for qs in new_questions_by_chunk.values())
    progress_lock = asyncio.Lock()

    async def bump_progress(n: int):
        nonlocal done_count
        async with progress_lock:
            done_count += n
            if on_progress:
                await on_progress(done_count, total)

    async def dedup_one_chunk(chunk_id: str, new_questions: list[dict]):
        nonlocal stopped
        if stopped or (stop_check and stop_check()):
            stopped = True
            return

        # Check pause before starting chunk
        if pause_check and await pause_check():
            stopped = True
            return

        existing = existing_questions_by_chunk.get(chunk_id, [])

        async with chunk_sem:
            if stopped or (stop_check and stop_check()):
                stopped = True
                return

            # Check pause again after acquiring semaphore
            if pause_check and await pause_check():
                stopped = True
                return

            # ── Step 1: 正则归一化查重 ─────────────────────────────────
            seen_norm: dict[str, str] = {}   # 归一化后的字符串 -> 首次出现该形式的新问题 id
            remaining: list[dict] = []

            for q in new_questions:
                # 与已有问题做规范化比对
                ex_id = _regex_duplicate_id(q["question"], existing)
                if ex_id:
                    results[q["id"]] = (ex_id, 1.0)
                    continue
                # 与同批次更早的新问题比对
                norm = _normalize(q["question"])
                if norm and norm in seen_norm:
                    results[q["id"]] = (seen_norm[norm], 1.0)
                    continue
                if norm:
                    seen_norm[norm] = q["id"]
                remaining.append(q)

            # ── Step 2: 向量相似度查重 ─────────────────────────────────
            if remaining:
                try:
                    new_texts = [q["question"] for q in remaining]
                    new_ids = [q["id"] for q in remaining]
                    existing_texts = [q for _, q in existing]
                    existing_ids = [qid for qid, _ in existing]

                    all_vecs = await _embed_texts(
                        embed_client, embed_model, new_texts + existing_texts
                    )
                    new_vecs = all_vecs[:len(new_texts)]
                    ex_vecs = all_vecs[len(new_texts):]

                    for i, nv in enumerate(new_vecs):
                        best_id: Optional[str] = None
                        best_sim = 0.0
                        # vs 已有问题
                        for ex_id, ev in zip(existing_ids, ex_vecs):
                            sim = float(np.dot(nv, ev))
                            if sim > best_sim:
                                best_sim = sim
                                best_id = ex_id
                        # vs 同批次更早的新问题（捕获批内近似重复）
                        for j in range(i):
                            sim = float(np.dot(nv, new_vecs[j]))
                            if sim > best_sim:
                                best_sim = sim
                                best_id = new_ids[j]

                        if best_id is not None and best_sim >= similarity_threshold:
                            results[new_ids[i]] = (best_id, round(best_sim, 4))
                        else:
                            results[new_ids[i]] = (None, 0.0)
                except Exception as e:
                    print(f"[WARN] Vector dedup failed for chunk {chunk_id}: {e}")
                    for q in remaining:
                        results.setdefault(q["id"], (None, 0.0))

        await bump_progress(len(new_questions))

    tasks = [
        dedup_one_chunk(chunk_id, questions)
        for chunk_id, questions in new_questions_by_chunk.items()
    ]
    await asyncio.gather(*tasks)
    return results
