from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class SampleResult:
    sample_id: str
    question: str
    reference_answer: str
    # Retrieval
    retrieved_chunk_ids: list[str] = field(default_factory=list)
    retrieved_chunks: list[str] = field(default_factory=list)
    hit_rate: float | None = None
    mrr: float | None = None
    ndcg: float | None = None
    context_precision: float | None = None
    context_recall: float | None = None
    # Generation
    agent_answer: str = ""
    faithfulness: float | None = None
    answer_relevance: float | None = None
    answer_correctness: float | None = None
    groundedness: float | None = None
    latency_ms: int = 0
    # Raw judge output
    judge_detail: dict = field(default_factory=dict)
    error: str | None = None


@dataclass
class EvalReport:
    task_id: str
    dataset_name: str
    sample_count: int
    results: list[SampleResult]
    # Retrieval averages
    avg_hit_rate: float | None = None
    avg_mrr: float | None = None
    avg_ndcg: float | None = None
    avg_context_precision: float | None = None
    avg_context_recall: float | None = None
    # Generation averages
    avg_faithfulness: float | None = None
    avg_answer_relevance: float | None = None
    avg_answer_correctness: float | None = None
    avg_groundedness: float | None = None
    # Composite
    rag_score: float | None = None
    hallucination_rate: float | None = None
    created_at: datetime = field(default_factory=datetime.utcnow)

    def summary(self) -> str:
        lines = [
            "┌─────────────────────────────────────────┐",
            "│           评测报告摘要                    │",
            "├──────────────────────┬──────────────────┤",
            f"│ 样本数               │ {self.sample_count:<16} │",
        ]
        def _row(label, val):
            v = f"{val:.4f}" if val is not None else "N/A"
            return f"│ {label:<20} │ {v:<16} │"

        lines += [
            _row("Hit Rate@K",          self.avg_hit_rate),
            _row("MRR@K",               self.avg_mrr),
            _row("NDCG@K",              self.avg_ndcg),
            _row("Context Precision",   self.avg_context_precision),
            _row("Context Recall",      self.avg_context_recall),
            _row("Faithfulness",        self.avg_faithfulness),
            _row("Answer Relevance",    self.avg_answer_relevance),
            _row("Answer Correctness",  self.avg_answer_correctness),
            _row("Groundedness",        self.avg_groundedness),
            _row("RAG Score",           self.rag_score),
            _row("Hallucination Rate",  self.hallucination_rate),
            "└──────────────────────┴──────────────────┘",
        ]
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "dataset_name": self.dataset_name,
            "sample_count": self.sample_count,
            "created_at": self.created_at.isoformat(),
            "retrieval": {
                "avg_hit_rate": self.avg_hit_rate,
                "avg_mrr": self.avg_mrr,
                "avg_ndcg": self.avg_ndcg,
                "avg_context_precision": self.avg_context_precision,
                "avg_context_recall": self.avg_context_recall,
            },
            "generation": {
                "avg_faithfulness": self.avg_faithfulness,
                "avg_answer_relevance": self.avg_answer_relevance,
                "avg_answer_correctness": self.avg_answer_correctness,
                "avg_groundedness": self.avg_groundedness,
            },
            "composite": {
                "rag_score": self.rag_score,
                "hallucination_rate": self.hallucination_rate,
            },
            "results": [
                {
                    "sample_id": r.sample_id,
                    "question": r.question,
                    "agent_answer": r.agent_answer,
                    "retrieved_chunk_ids": r.retrieved_chunk_ids,
                    "hit_rate": r.hit_rate,
                    "mrr": r.mrr,
                    "ndcg": r.ndcg,
                    "context_precision": r.context_precision,
                    "context_recall": r.context_recall,
                    "faithfulness": r.faithfulness,
                    "answer_relevance": r.answer_relevance,
                    "answer_correctness": r.answer_correctness,
                    "groundedness": r.groundedness,
                    "latency_ms": r.latency_ms,
                    "error": r.error,
                }
                for r in self.results
            ],
        }

    def save(self, path: str):
        import json
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)
        print(f"Report saved to {path}")
