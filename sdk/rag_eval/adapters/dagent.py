import json
import time
import aiohttp
from .base import RAGAdapter, RetrievedChunk, AgentResponse


class DagentAdapter(RAGAdapter):
    """
    对接 dagent 平台的适配器。
    通过 HTTP API 调用，不依赖 dagent 内部代码。
    """

    def __init__(self, base_url: str, org_id: str, token: str = ""):
        self.base_url = base_url.rstrip("/")
        self.org_id = org_id
        self.headers = {"Authorization": f"Bearer {token}"} if token else {}

    async def retrieve(
        self,
        query: str,
        knowledge_hub_id: str,
        top_k: int = 10,
        file_id_list: list[str] | None = None,
        **kwargs,
    ) -> list[RetrievedChunk]:
        payload = {
            "query": query,
            "org_id": self.org_id,
            "top_k": top_k,
        }
        if knowledge_hub_id:
            payload["knowledge_hub_id"] = knowledge_hub_id
        if file_id_list:
            payload["file_id_list"] = file_id_list

        async with aiohttp.ClientSession(headers=self.headers) as session:
            async with session.post(
                f"{self.base_url}/dagent/knowledge/hub/semantic_search_knowledge/detail",
                json=payload,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                resp.raise_for_status()
                data = await resp.json()

        result_data = data.get("data", {})
        standard = result_data.get("standard_answer_results") or []
        related = result_data.get("related_knowledge_rerank_results_top") or []
        all_items = standard + related

        chunks = []
        for item in all_items:
            chunks.append(RetrievedChunk(
                chunk_id=item.get("knowledge_md_header_split_id") or item.get("id", ""),
                content=item.get("active_paragraph_context") or item.get("active_context") or "",
                score=1.0 - (item.get("cosine_distance_1") or 0.0),
                headers=item.get("headers") or "",
                file_id=item.get("file_id") or "",
            ))
        return chunks[:top_k]

    async def chat(
        self,
        query: str,
        agent_id: str,
        llm_type: str = "azure_openai_4o",
        **kwargs,
    ) -> AgentResponse:
        import uuid
        payload = {
            "chat_id": str(uuid.uuid4()),
            "task": query,
            "agent_id": agent_id,
            "org_id": self.org_id,
            "llm_type": llm_type,
            "chat_messages": [{"role": "user", "content": query}],
        }

        answer_parts: list[str] = []
        start = time.monotonic()

        async with aiohttp.ClientSession(headers=self.headers) as session:
            async with session.post(
                f"{self.base_url}/dagent/agent/chat",
                json=payload,
                headers={**self.headers, "Accept": "text/event-stream"},
                timeout=aiohttp.ClientTimeout(total=120),
            ) as resp:
                resp.raise_for_status()
                async for raw_line in resp.content:
                    line = raw_line.decode("utf-8").strip()
                    if not line.startswith("data:"):
                        continue
                    data_str = line[5:].strip()
                    if not data_str or data_str == "[DONE]":
                        continue
                    try:
                        chunk = json.loads(data_str)
                    except json.JSONDecodeError:
                        continue
                    msg_type = chunk.get("message_type", "")
                    if chunk.get("is_chunk_data") or msg_type in ("", "CHUNK"):
                        content = chunk.get("data", "")
                        if isinstance(content, str):
                            answer_parts.append(content)
                    elif msg_type == "EVENT":
                        event = chunk.get("data", {})
                        if isinstance(event, dict) and event.get("event_finish"):
                            break

        latency_ms = int((time.monotonic() - start) * 1000)
        return AgentResponse(
            answer="".join(answer_parts).strip(),
            retrieved_chunks=[],
            latency_ms=latency_ms,
        )

    async def get_chunks_for_file(
        self,
        file_id: str,
        page_size: int = 100,
    ) -> list[dict]:
        """拉取文件的所有 chunk，用于测试集生成"""
        payload = {
            "file_id": file_id,
            "org_id": self.org_id,
            "page": 1,
            "page_size": page_size,
        }
        async with aiohttp.ClientSession(headers=self.headers) as session:
            async with session.post(
                f"{self.base_url}/dagent/knowledge/chunk/page",
                json=payload,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                resp.raise_for_status()
                data = await resp.json()
        # API returns data.data.list, not data.data.records
        return data.get("data", {}).get("list", [])
