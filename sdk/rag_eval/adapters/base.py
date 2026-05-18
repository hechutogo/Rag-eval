from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class RetrievedChunk:
    chunk_id: str
    content: str
    score: float
    headers: str = ""
    file_id: str = ""


@dataclass
class AgentResponse:
    answer: str
    retrieved_chunks: list[RetrievedChunk] = field(default_factory=list)
    latency_ms: int = 0


class RAGAdapter(ABC):
    """
    任何 RAG 平台都需要实现这两个方法。
    框架通过此接口与平台交互，不依赖平台内部实现。
    """

    @abstractmethod
    async def retrieve(
        self,
        query: str,
        knowledge_hub_id: str,
        top_k: int = 10,
        **kwargs,
    ) -> list[RetrievedChunk]:
        """调用平台检索接口，返回召回的切片列表"""
        ...

    @abstractmethod
    async def chat(
        self,
        query: str,
        agent_id: str,
        **kwargs,
    ) -> AgentResponse:
        """调用平台 Agent 对话接口，返回回复和引用的切片"""
        ...
