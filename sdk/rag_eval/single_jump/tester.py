"""
召回测试执行器：对每条问答对调用 dagent 语义召回接口，记录结果。
"""
import asyncio
import json
import sys
import time
from dataclasses import dataclass, field
import aiohttp

# Fix Windows GBK encoding issue
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.stderr.reconfigure(encoding='utf-8', errors='replace')

from .parser import Section, QAPair


@dataclass
class RecallResult:
    section_path: str
    doc_name: str
    file_id: str | None
    match_type: str | None        # exact / contains / fuzzy / unmatched
    qid: str
    question: str
    reference_answer: str
    top_k: int                    # 用于判断命中的top_k值
    hit_top_k: int                # 用于判断切片是否命中的top_k阈值（可能不同于召回时的top_k）
    retrieved: list[dict] = field(default_factory=list)   # 召回的切片列表（全部，不截断）
    latency_ms: int = 0
    error: str | None = None
    expected_chunk_id: str | None = None  # 期望命中的切片ID
    raw_chunk_headers: str | None = None  # 原始切片标题（从元数据解析）

    # 计算属性
    @property
    def best_cosine_sim(self) -> float | None:
        sims = [1.0 - r.get("cosine_distance_1", 1.0) for r in self.retrieved if r.get("cosine_distance_1") is not None]
        return round(max(sims), 4) if sims else None

    @property
    def avg_cosine_sim(self) -> float | None:
        sims = [1.0 - r.get("cosine_distance_1", 1.0) for r in self.retrieved if r.get("cosine_distance_1") is not None]
        return round(sum(sims) / len(sims), 4) if sims else None

    @property
    def is_empty(self) -> bool:
        return len(self.retrieved) == 0

    @property
    def retrieved_file_ids(self) -> list[str]:
        return list({r.get("file_id", "") for r in self.retrieved if r.get("file_id")})

    @property
    def retrieved_chunk_ids(self) -> list[str]:
        """获取召回的所有切片ID"""
        chunk_ids = []
        for r in self.retrieved:
            chunk_id = r.get("knowledge_md_header_split_id") or r.get("id") or r.get("chunk_id")
            if chunk_id:
                chunk_ids.append(chunk_id)
        return chunk_ids

    @property
    def is_chunk_hit(self) -> bool:
        """检查期望切片是否在召回结果的前hit_top_k个结果中"""
        if not self.expected_chunk_id:
            return False
        return self.expected_chunk_id in self.retrieved_chunk_ids[:self.hit_top_k]

    @property
    def chunk_hit_rank(self) -> int | None:
        """返回期望切片在召回结果中的排名（1-based），未命中返回None

        只在hit_top_k范围内查找，超出范围视为未命中
        """
        if not self.expected_chunk_id:
            return None
        try:
            idx = self.retrieved_chunk_ids[:self.hit_top_k].index(self.expected_chunk_id)
            return idx + 1
        except ValueError:
            return None

    @property
    def is_file_hit(self) -> bool:
        """检查期望文件是否在召回结果的前hit_top_k个结果中"""
        if not self.file_id:
            return False
        # 获取前hit_top_k个结果的file_ids
        top_file_ids = []
        for r in self.retrieved[:self.hit_top_k]:
            fid = r.get("file_id")
            if fid:
                top_file_ids.append(fid)
        return self.file_id in top_file_ids


class RecallTester:
    def __init__(self, env_url: str, org_id: str, d_user_id: str = "test"):
        self.env_url = env_url.rstrip("/")
        self.org_id = org_id
        self.headers = {
            "Content-Type": "application/json",
            "d-user-id": d_user_id,
            "org-id": org_id,
        }

    async def _recall_one(
        self,
        session: aiohttp.ClientSession,
        question: str,
        file_id_list: list[str] | None,
        recall_top_k: int,  # 用于API调用时的top_k，可以设置较大值获取所有结果
        agent_id: str = "",  # 用于召回测试的 agent ID
    ) -> tuple[list[dict], int]:
        # 如果提供了 agent_id，使用 agent chat API 进行召回
        if agent_id:
            return await self._recall_via_agent(session, question, agent_id, recall_top_k)

        # 否则直接使用知识库搜索 API
        url = f"{self.env_url}/dagent/knowledge/hub/semantic_search_knowledge/detail"
        payload: dict = {
            "query": question,
            "org_id": self.org_id,
            "top_k": recall_top_k,
        }
        if file_id_list:
            payload["file_id_list"] = file_id_list

        start = time.monotonic()
        # 增加超时时间到60秒，并添加重试逻辑
        max_retries = 3
        last_error = None

        for attempt in range(max_retries):
            try:
                async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=60)) as resp:
                    resp.raise_for_status()
                    data = await resp.json()
                break  # 成功则跳出重试循环
            except asyncio.TimeoutError as e:
                last_error = e
                print(f"[DEBUG] Recall timeout (attempt {attempt+1}/{max_retries}) for: {question[:50]}...")
                if attempt < max_retries - 1:
                    await asyncio.sleep(2 ** attempt)  # 指数退避: 1s, 2s, 4s
                else:
                    raise  # 最后一次重试失败，抛出异常
            except Exception as e:
                raise  # 其他异常直接抛出

        latency_ms = int((time.monotonic() - start) * 1000)

        # 检查 API 返回的业务错误码
        code = data.get("code")
        if code is not None and code != 0:
            msg = data.get("msg", "Unknown error")
            raise Exception(f"API error: code={code}, msg={msg}")

        result_data = data.get("data", {}) or {}

        # 调试：如果结果为空，打印调试信息
        if not result_data or (not result_data.get("standard_answer_results") and not result_data.get("related_knowledge_rerank_results_top")):
            print(f"[DEBUG] Empty/No results for question: {question[:50]}...")
            print(f"[DEBUG] Response code: {data.get('code')}, msg: {data.get('msg')}")
            print(f"[DEBUG] org_id used: {self.org_id}")
            print(f"[DEBUG] Request payload: {payload}")
            print(f"[DEBUG] Response data keys: {list(data.keys())}")
            if result_data:
                print(f"[DEBUG] result_data keys: {list(result_data.keys())}")

        standard = result_data.get("standard_answer_results") or []
        rerank_top = result_data.get("related_knowledge_rerank_results_top") or []
        all_items = standard + rerank_top

        # 调试：记录召回结果数量
        if len(all_items) == 0:
            print(f"[DEBUG] No recall results for: {question[:50]}... (standard={len(standard)}, rerank={len(rerank_top)})")

        return all_items, latency_ms

    async def _recall_via_agent(
        self,
        session: aiohttp.ClientSession,
        question: str,
        agent_id: str,
        recall_top_k: int,
    ) -> tuple[list[dict], int]:
        """通过 Agent chat SSE 接口获取召回结果。

        解析策略：
        - 逐行读取 SSE（服务端单 `\n` 分隔，不是双换行）
        - 每个 EVENT.event_name == "TOOL_END" 的 event_data.items 里有一批 chunk
        - Agent 可能多轮工具调用，每次 TOOL_END 都累加；按 (file_id, paragraph_chunk_id) 去重
        - 顺序保留首次出现位置（作为伪 rank），用于命中排名统计
        """
        import uuid
        payload = {
            "chat_id": uuid.uuid4().hex,
            "task": question,
            "agent_id": agent_id,
            "llm_type": "deepseek_v3",
        }

        start = time.monotonic()
        items: list[dict] = []
        seen: set[tuple[str, str]] = set()

        try:
            async with session.post(
                f"{self.env_url}/dagent/agent/chat",
                json=payload,
                headers={"Accept": "text/event-stream"},
                timeout=aiohttp.ClientTimeout(total=300),
            ) as resp:
                resp.raise_for_status()
                line_buf = ""
                async for raw in resp.content:
                    line_buf += raw.decode("utf-8", errors="replace")
                    while "\n" in line_buf:
                        line, line_buf = line_buf.split("\n", 1)
                        line = line.rstrip("\r")
                        if not line.startswith("data:"):
                            continue
                        data_str = line[5:].strip()
                        if not data_str or data_str == "[DONE]":
                            continue
                        try:
                            chunk = json.loads(data_str)
                        except json.JSONDecodeError:
                            continue
                        if chunk.get("message_type") != "EVENT" or chunk.get("is_chunk_data"):
                            continue
                        event_data_raw = chunk.get("data")
                        if isinstance(event_data_raw, str):
                            try:
                                event_data = json.loads(event_data_raw)
                            except json.JSONDecodeError:
                                continue
                        else:
                            event_data = event_data_raw
                        if not isinstance(event_data, dict):
                            continue
                        if event_data.get("event_name") != "TOOL_END":
                            continue
                        tool_event_data = event_data.get("event_data")
                        if not isinstance(tool_event_data, dict):
                            continue
                        reference_items = tool_event_data.get("items") or []
                        if not isinstance(reference_items, list):
                            continue
                        for item in reference_items:
                            if not isinstance(item, dict):
                                continue
                            file_id = str(item.get("file_id") or "")
                            chunk_id = str(
                                item.get("paragraph_chunk_id")
                                or item.get("knowledge_md_header_split_id")
                                or ""
                            )
                            # 跳过不带 file_id/chunk_id 的外链类条目（只有 file_name+url）
                            if not file_id and not chunk_id:
                                continue
                            key = (file_id, chunk_id)
                            if key in seen:
                                continue
                            seen.add(key)
                            items.append({
                                "file_id": file_id,
                                "file_name": "",
                                "headers": str(item.get("headers") or ""),
                                "content": item.get("active_paragraph_context")
                                    or item.get("active_context") or "",
                                "knowledge_md_header_split_id": chunk_id,
                                "id": chunk_id,
                                "paragraph_md5": str(item.get("paragraph_md5") or ""),
                                "cosine_distance_1": None,
                            })
        except Exception as e:
            print(f"[DEBUG] Agent recall error: {e}")

        latency_ms = int((time.monotonic() - start) * 1000)
        return items[:recall_top_k], latency_ms

    async def run(
        self,
        sections: list[Section],
        file_map: dict[str, dict | None],
        top_k: int = 5,           # 用于判断命中的top_k阈值
        recall_top_k: int = 100,  # 用于API调用时的top_k，默认100获取更多结果
        concurrency: int = 20,     # 增加默认并发数到20
        cross_chunk: bool = False,  # 保留参数兼容旧调用，但不再控制搜索范围
        result_cb=None,
        progress_cb=None,  # 保留兼容旧调用
        chunk_map: dict[str, str] | None = None,  # question -> expected_chunk_id
        agent_id: str = "",  # 用于召回测试的 agent ID
    ) -> list[RecallResult]:
        results: list[RecallResult] = []
        sem = asyncio.Semaphore(concurrency)
        total = sum(len(s.qa_pairs) for s in sections)
        done = 0

        async with aiohttp.ClientSession(headers=self.headers) as session:
            async def _test_one(section: Section, qa: QAPair) -> RecallResult:
                nonlocal done
                mapping = file_map.get(section.section_path)
                file_id = mapping["file_id"] if mapping else None
                match_type = mapping["match_type"] if mapping else "unmatched"

                # 优先使用 QAPair 上已注入的 chunk_id，其次从 chunk_map 查找
                expected_chunk_id = qa.expected_chunk_id or (
                    chunk_map.get(qa.question) if chunk_map else None
                )

                result = RecallResult(
                    section_path=section.section_path,
                    doc_name=section.doc_name,
                    file_id=file_id,
                    match_type=match_type,
                    qid=qa.qid,
                    question=qa.question,
                    reference_answer=qa.answer,
                    top_k=top_k,
                    hit_top_k=top_k,  # 用于判断命中的阈值
                    expected_chunk_id=expected_chunk_id,
                    raw_chunk_headers=section.raw_chunk_headers,
                )

                # 始终全库搜索（不传 file_id_list），以切片命中为主要指标
                # 使用较大的 recall_top_k 获取所有召回结果
                async with sem:
                    try:
                        chunks, latency = await self._recall_one(session, qa.question, None, recall_top_k, agent_id)
                        result.retrieved = chunks
                        result.latency_ms = latency
                        # 调试：记录召回结果数量
                        if len(chunks) == 0:
                            print(f"[DEBUG] Empty recall for question: {qa.question[:60]}... (section: {section.section_path[:40]}...)")
                    except Exception as e:
                        result.error = str(e)
                        print(f"[DEBUG] Recall error for question: {qa.question[:60]}... Error: {e}")

                done += 1
                if result_cb:
                    await result_cb(result, done, total)
                elif progress_cb and (done % 10 == 0 or done == total):
                    await progress_cb(done, total)
                return result

            tasks = [
                _test_one(section, qa)
                for section in sections
                for qa in section.qa_pairs
            ]
            for coro in asyncio.as_completed(tasks):
                results.append(await coro)

        return results
