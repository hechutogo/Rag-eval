import asyncio
import json
from abc import ABC, abstractmethod
from openai import AsyncOpenAI


class LLMJudge(ABC):
    @abstractmethod
    async def score_faithfulness(self, answer: str, context: list[str]) -> tuple[float, dict]:
        ...

    @abstractmethod
    async def score_relevance(self, question: str, answer: str) -> tuple[float, dict]:
        ...

    @abstractmethod
    async def score_correctness(self, answer: str, reference: str) -> tuple[float, dict]:
        ...

    @abstractmethod
    async def score_groundedness(self, answer: str, chunks: list[dict]) -> tuple[float, dict]:
        ...
