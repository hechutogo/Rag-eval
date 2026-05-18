"""
多跳召回测试报告生成。
"""
from dataclasses import dataclass, field
from .tester import MultiHopResult


@dataclass
class MultiHopReport:
    env_url: str
    org_id: str
    top_k: int
    total: int
    error_count: int
    empty_count: int          # retrieved 为空
    full_hit_count: int       # 所有 hop 全部命中
    partial_hit_count: int    # 至少命中 1 个 hop（含全命中）
    avg_hop_hit_rate: float   # 平均每题命中 hop 比例
    avg_latency_ms: float
    avg_best_sim: float | None
    by_type: dict             # {type: {total, full_hit, partial_hit}}
    results: list[MultiHopResult] = field(default_factory=list)

    @property
    def full_hit_rate(self) -> float:
        return round(self.full_hit_count / self.total, 4) if self.total else 0.0

    @property
    def partial_hit_rate(self) -> float:
        return round(self.partial_hit_count / self.total, 4) if self.total else 0.0

    @property
    def empty_rate(self) -> float:
        return round(self.empty_count / self.total, 4) if self.total else 0.0

    def summary(self) -> str:
        lines = [
            "=" * 60,
            "多跳召回测试报告",
            "=" * 60,
            f"环境:        {self.env_url}",
            f"组织:        {self.org_id}",
            f"top_k:       {self.top_k}",
            f"总问题数:    {self.total}",
            f"全命中率:    {self.full_hit_rate:.1%}  ({self.full_hit_count}/{self.total})",
            f"部分命中率:  {self.partial_hit_rate:.1%}  ({self.partial_hit_count}/{self.total})",
            f"空召回率:    {self.empty_rate:.1%}  ({self.empty_count}/{self.total})",
            f"平均hop命中: {self.avg_hop_hit_rate:.1%}",
            f"平均延迟:    {self.avg_latency_ms:.0f} ms",
        ]
        if self.avg_best_sim is not None:
            lines.append(f"平均最佳相似度: {self.avg_best_sim:.4f}")
        if self.error_count:
            lines.append(f"错误数:      {self.error_count}")

        if self.by_type:
            lines.append("")
            lines.append("按类型统计:")
            for qtype, stat in self.by_type.items():
                t = stat["total"]
                fh = stat["full_hit"]
                ph = stat["partial_hit"]
                lines.append(
                    f"  {qtype:<15} 共{t:>4}题  全命中{fh/t:.1%}  部分命中{ph/t:.1%}"
                )

        lines.append("=" * 60)
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {
            "env_url": self.env_url,
            "org_id": self.org_id,
            "top_k": self.top_k,
            "total": self.total,
            "full_hit_count": self.full_hit_count,
            "full_hit_rate": self.full_hit_rate,
            "partial_hit_count": self.partial_hit_count,
            "partial_hit_rate": self.partial_hit_rate,
            "empty_count": self.empty_count,
            "empty_rate": self.empty_rate,
            "error_count": self.error_count,
            "avg_hop_hit_rate": self.avg_hop_hit_rate,
            "avg_latency_ms": self.avg_latency_ms,
            "avg_best_sim": self.avg_best_sim,
            "by_type": self.by_type,
            "results": [_result_to_dict(r) for r in self.results],
        }


def _result_to_dict(r: MultiHopResult) -> dict:
    return {
        "qid": r.qid,
        "question": r.question,
        "type": r.type,
        "full_hit": r.full_hit,
        "partial_hit": r.partial_hit,
        "hop_count": r.hop_count,
        "hop_hit_count": r.hop_hit_count,
        "latency_ms": r.latency_ms,
        "best_cosine_sim": r.best_cosine_sim,
        "error": r.error,
        "hops": [
            {
                "section_path": h.section_path,
                "file_id": h.file_id,
                "file_name": h.file_name,
                "hit": h.hit,
                "contribution": h.contribution,
            }
            for h in r.hop_results
        ],
        "retrieved_file_ids": list(r.retrieved_file_ids),
    }


def build_report(
    results: list[MultiHopResult],
    env_url: str,
    org_id: str,
    top_k: int,
) -> MultiHopReport:
    total = len(results)
    if total == 0:
        return MultiHopReport(
            env_url=env_url, org_id=org_id, top_k=top_k,
            total=0, error_count=0, empty_count=0,
            full_hit_count=0, partial_hit_count=0,
            avg_hop_hit_rate=0.0, avg_latency_ms=0.0,
            avg_best_sim=None, by_type={}, results=[],
        )

    error_count     = sum(1 for r in results if r.error)
    empty_count     = sum(1 for r in results if r.is_empty and not r.error)
    full_hit_count  = sum(1 for r in results if r.full_hit)
    partial_hit_count = sum(1 for r in results if r.partial_hit)

    # 平均 hop 命中率（只统计有 file_id 映射的 hop）
    hop_hit_rates = []
    for r in results:
        mappable = [h for h in r.hop_results if h.file_id]
        if mappable:
            hop_hit_rates.append(sum(1 for h in mappable if h.hit) / len(mappable))
    avg_hop_hit_rate = sum(hop_hit_rates) / len(hop_hit_rates) if hop_hit_rates else 0.0

    valid = [r for r in results if not r.error]
    avg_latency_ms = sum(r.latency_ms for r in valid) / len(valid) if valid else 0.0

    sims = [r.best_cosine_sim for r in valid if r.best_cosine_sim is not None]
    avg_best_sim = round(sum(sims) / len(sims), 4) if sims else None

    # 按类型统计
    by_type: dict = {}
    for r in results:
        t = r.type
        if t not in by_type:
            by_type[t] = {"total": 0, "full_hit": 0, "partial_hit": 0}
        by_type[t]["total"] += 1
        if r.full_hit:
            by_type[t]["full_hit"] += 1
        if r.partial_hit:
            by_type[t]["partial_hit"] += 1

    return MultiHopReport(
        env_url=env_url,
        org_id=org_id,
        top_k=top_k,
        total=total,
        error_count=error_count,
        empty_count=empty_count,
        full_hit_count=full_hit_count,
        partial_hit_count=partial_hit_count,
        avg_hop_hit_rate=round(avg_hop_hit_rate, 4),
        avg_latency_ms=round(avg_latency_ms, 1),
        avg_best_sim=avg_best_sim,
        by_type=by_type,
        results=results,
    )
