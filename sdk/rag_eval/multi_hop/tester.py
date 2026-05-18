"""
多跳召回测试执行器 v4

策略：调用 dagent 的 /agent/chat SSE 接口，让 Agent 自主决定搜几次、用什么 query。
解析 SSE 流中的 TOOL_END 事件，收集每一跳的召回文档，和期望 hop 做对比。
"""
import asyncio
import json
import time
from dataclasses import dataclass, field

import aiohttp

from .parser import MultiHopQAPair, Hop


@dataclass
class HopResult:
    section_path: str
    file_id: str | None
    file_name: str | None
    contribution: str
    expected_chunk_id: str = ""   # 期望命中的切片ID
    hit: bool = False             # 文件级命中
    hit_at_hop: int | None = None
    chunk_hit: bool = False       # 切片级命中
    chunk_hit_at_hop: int | None = None


@dataclass
class ActualHop:
    """Agent 实际执行的一跳"""
    hop_index: int
    query: str
    retrieved: list[dict]


@dataclass
class MultiHopResult:
    qid: str
    question: str
    answer: str
    type: str
    top_k: int
    hop_results: list[HopResult]
    actual_hops: list[ActualHop] = field(default_factory=list)
    agent_answer: str = ""
    latency_ms: int = 0
    error: str | None = None

    @property
    def hop_count(self) -> int:
        return len(self.hop_results)

    @property
    def actual_hop_count(self) -> int:
        return len(self.actual_hops)

    @property
    def hop_hit_count(self) -> int:
        return sum(1 for h in self.hop_results if h.hit)

    @property
    def chunk_hit_count(self) -> int:
        return sum(1 for h in self.hop_results if h.chunk_hit)

    @property
    def full_hit(self) -> bool:
        mappable = [h for h in self.hop_results if h.file_id]
        return len(mappable) > 0 and all(h.hit for h in mappable)

    @property
    def full_chunk_hit(self) -> bool:
        mappable = [h for h in self.hop_results if h.expected_chunk_id]
        return len(mappable) > 0 and all(h.chunk_hit for h in mappable)

    @property
    def partial_hit(self) -> bool:
        return any(h.hit for h in self.hop_results)

    @property
    def partial_chunk_hit(self) -> bool:
        return any(h.chunk_hit for h in self.hop_results)

    @property
    def retrieved(self) -> list[dict]:
        """所有跳的召回结果合并去重"""
        seen: set[str] = set()
        merged = []
        for ah in self.actual_hops:
            for doc in ah.retrieved:
                key = doc.get("file_id", "") + doc.get("headers", "")
                if key not in seen:
                    seen.add(key)
                    merged.append(doc)
        return merged

    @property
    def retrieved_file_ids(self) -> set[str]:
        return {r.get("file_id", "") for r in self.retrieved if r.get("file_id")}

    @property
    def best_cosine_sim(self) -> float | None:
        sims = [1.0 - r.get("cosine_distance_1", 1.0)
                for r in self.retrieved if r.get("cosine_distance_1") is not None]
        return round(max(sims), 4) if sims else None


async def _parse_agent_chat_sse(
    session: aiohttp.ClientSession,
    url: str,
    payload: dict,
    timeout_s: int = 300,
) -> tuple[list[ActualHop], str]:
    """
    调用 /agent/chat SSE 接口，解析流中的事件。

    返回：(actual_hops, agent_answer)

    SSE 格式：每行一条 `data: {...}` 消息，行间以单个 \n 分隔（不是 \n\n）。
    """
    import re as _re

    actual_hops: list[ActualHop] = []
    answer_chunks: list[str] = []
    tool_query = ""
    hop_index = 0

    async with session.post(
        url, json=payload,
        timeout=aiohttp.ClientTimeout(total=timeout_s),
    ) as resp:
        resp.raise_for_status()
        # 逐行读取：服务端每行一条 data: 消息
        line_buf = ""
        async for raw in resp.content:
            line_buf += raw.decode("utf-8", errors="replace")
            # 按换行切割，保留末尾不完整行
            while "\n" in line_buf:
                line, line_buf = line_buf.split("\n", 1)
                line = line.rstrip("\r")
                if not line.startswith("data:"):
                    continue
                data_str = line[5:].strip()
                if not data_str or data_str == "[DONE]":
                    continue
                try:
                    parsed = json.loads(data_str)
                except json.JSONDecodeError:
                    continue

                mt = parsed.get("message_type", "")
                is_chunk = parsed.get("is_chunk_data", False)
                data = parsed.get("data", "")

                # 收集 Agent 最终回答
                if is_chunk and mt not in ("THINKING_CHUNK", "EVENT"):
                    if isinstance(data, str):
                        answer_chunks.append(data)

                # 收集 TOOL_CHUNK 中的 query 参数
                if mt == "TOOL_CHUNK" and is_chunk and isinstance(data, str):
                    tool_query += data

                # 解析 EVENT
                if mt == "EVENT" and not is_chunk:
                    try:
                        ed = json.loads(data) if isinstance(data, str) else data
                    except (json.JSONDecodeError, TypeError):
                        continue
                    if not isinstance(ed, dict):
                        continue
                    ename = ed.get("event_name", "")

                    if ename == "TOOL_START":
                        tool_query = ""

                    elif ename == "TOOL_END":
                        edata = ed.get("event_data")
                        docs = []
                        if isinstance(edata, dict) and "items" in edata:
                            for item in edata["items"]:
                                file_id = str(item.get("file_id") or "")
                                chunk_id = str(item.get("paragraph_chunk_id") or "")
                                # 跳过外链类工具（无 file_id/chunk_id）
                                if not file_id and not chunk_id:
                                    continue
                                docs.append({
                                    "file_id": file_id,
                                    "headers": item.get("headers", ""),
                                    "paragraph_md5": item.get("paragraph_md5", ""),
                                    "paragraph_chunk_id": chunk_id,
                                })

                        # 只记录真正召回了知识切片的 hop
                        if docs:
                            hop_index += 1
                            query_match = _re.search(
                                r"<query>(.*?)</query>", tool_query, _re.DOTALL
                            )
                            query_text = (
                                query_match.group(1).strip()
                                if query_match
                                else tool_query.strip()
                            )
                            actual_hops.append(ActualHop(
                                hop_index=hop_index,
                                query=query_text,
                                retrieved=docs,
                            ))
                        tool_query = ""

    agent_answer = "".join(answer_chunks).strip()
    return actual_hops, agent_answer


class MultiHopTester:
    def __init__(self, env_url: str, org_id: str, d_user_id: str = "test",
                 agent_id: str = "", llm_type: str = "deepseek_v3"):
        self.env_url = env_url.rstrip("/")
        self.org_id = org_id
        self.agent_id = agent_id
        self.llm_type = llm_type
        self.headers = {
            "Content-Type": "application/json",
            "d-user-id": d_user_id,
            "org-id": org_id,
        }

    async def run(
        self,
        qa_pairs: list[MultiHopQAPair],
        file_map: dict[str, dict | None],
        top_k: int = 10,
        concurrency: int = 5,
        result_cb=None,
    ) -> list[MultiHopResult]:
        results: list[MultiHopResult] = []
        sem = asyncio.Semaphore(concurrency)
        total = len(qa_pairs)
        done = 0

        connector = aiohttp.TCPConnector(ssl=False)
        async with aiohttp.ClientSession(
            headers=self.headers, connector=connector
        ) as session:

            async def _test_one(qa: MultiHopQAPair) -> MultiHopResult:
                nonlocal done

                hop_results = []
                for hop in qa.hops:
                    mapping = file_map.get(hop.section_path)
                    hop_results.append(HopResult(
                        section_path=hop.section_path,
                        file_id=mapping["file_id"] if mapping else None,
                        file_name=mapping["file_name"] if mapping else None,
                        contribution=hop.contribution,
                        expected_chunk_id=hop.chunk_id or "",
                    ))

                result = MultiHopResult(
                    qid=qa.qid,
                    question=qa.question,
                    answer=qa.answer,
                    type=qa.type,
                    top_k=top_k,
                    hop_results=hop_results,
                )

                async with sem:
                    start = time.monotonic()
                    try:
                        import uuid
                        # 构建 chat URL：如果 env_url 以 /dagent 结尾，则拼接 /agent/chat，否则拼接 /dagent/agent/chat
                        base = self.env_url.rstrip("/")
                        if base.endswith("/dagent"):
                            chat_url = f"{base}/agent/chat"
                        else:
                            chat_url = f"{base}/dagent/agent/chat"
                        payload = {
                            "task": qa.question,
                            "agent_id": self.agent_id,
                            "chat_id": uuid.uuid4().hex,
                            "llm_type": self.llm_type,
                        }

                        actual_hops, agent_answer = await _parse_agent_chat_sse(
                            session, chat_url, payload, timeout_s=300,
                        )
                        result.actual_hops = actual_hops
                        result.agent_answer = agent_answer
                        result.latency_ms = int(
                            (time.monotonic() - start) * 1000
                        )

                        # 文件级命中：期望文件是否出现在任意一跳召回中
                        for hr in result.hop_results:
                            if hr.file_id:
                                for ah in actual_hops:
                                    if any(
                                        d.get("file_id") == hr.file_id
                                        for d in ah.retrieved
                                    ):
                                        hr.hit = True
                                        hr.hit_at_hop = ah.hop_index
                                        break
                            # 切片级命中：期望 chunk_id 是否出现在任意一跳召回中
                            if hr.expected_chunk_id:
                                for ah in actual_hops:
                                    if any(
                                        d.get("paragraph_chunk_id") == hr.expected_chunk_id
                                        for d in ah.retrieved
                                    ):
                                        hr.chunk_hit = True
                                        hr.chunk_hit_at_hop = ah.hop_index
                                        break

                    except Exception as e:
                        result.error = str(e)
                        result.latency_ms = int(
                            (time.monotonic() - start) * 1000
                        )

                done += 1
                if result_cb:
                    await result_cb(result, done, total)
                return result

            tasks = [_test_one(qa) for qa in qa_pairs]
            for coro in asyncio.as_completed(tasks):
                results.append(await coro)

        return results
