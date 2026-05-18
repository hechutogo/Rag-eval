from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class EvalSample:
    id: str
    question: str
    reference_answer: str
    relevant_chunk_ids: list[str]
    knowledge_hub_id: str
    source_file_id: str | None = None
    metadata: dict = field(default_factory=dict)


@dataclass
class EvalDataset:
    id: str
    name: str
    description: str
    samples: list[EvalSample]
    created_at: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "created_at": self.created_at.isoformat(),
            "samples": [
                {
                    "id": s.id,
                    "question": s.question,
                    "reference_answer": s.reference_answer,
                    "relevant_chunk_ids": s.relevant_chunk_ids,
                    "knowledge_hub_id": s.knowledge_hub_id,
                    "source_file_id": s.source_file_id,
                    "metadata": s.metadata,
                }
                for s in self.samples
            ],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "EvalDataset":
        samples = [
            EvalSample(
                id=s["id"],
                question=s["question"],
                reference_answer=s.get("reference_answer", ""),
                relevant_chunk_ids=s.get("relevant_chunk_ids", []),
                knowledge_hub_id=s.get("knowledge_hub_id", ""),
                source_file_id=s.get("source_file_id"),
                metadata=s.get("metadata", {}),
            )
            for s in data.get("samples", [])
        ]
        return cls(
            id=data["id"],
            name=data["name"],
            description=data.get("description", ""),
            samples=samples,
        )
