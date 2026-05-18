"""
报告生成器：汇总召回测试结果，输出结构化报告。
"""
import json
from dataclasses import dataclass, field
from datetime import datetime
from .tester import RecallResult


@dataclass
class SectionStats:
    section_path: str
    doc_name: str
    file_id: str | None
    match_type: str | None
    total: int = 0
    recalled: int = 0       # 有召回结果的问题数
    empty: int = 0          # 空召回数
    errors: int = 0
    avg_cosine_sim: float | None = None
    avg_latency_ms: float | None = None


@dataclass
class SingleJumpReport:
    env_url: str
    org_id: str
    qa_file: str
    top_k: int
    cross_chunk: bool
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())

    total_questions: int = 0
    total_sections: int = 0
    matched_sections: int = 0       # 成功映射到 file_id 的章节数
    unmatched_sections: int = 0
    recalled_questions: int = 0     # 有召回结果的问题数
    empty_questions: int = 0
    error_questions: int = 0

    recall_rate: float | None = None        # recalled / total
    empty_rate: float | None = None
    section_match_rate: float | None = None
    avg_cosine_sim: float | None = None
    avg_latency_ms: float | None = None

    section_stats: list[SectionStats] = field(default_factory=list)
    low_quality_results: list[dict] = field(default_factory=list)
    suspicious_results: list[dict] = field(default_factory=list)
    unmatched_section_list: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = {
            "env_url": self.env_url,
            "org_id": self.org_id,
            "qa_file": self.qa_file,
            "top_k": self.top_k,
            "cross_chunk": self.cross_chunk,
            "created_at": self.created_at,
            "summary": {
                "total_questions": self.total_questions,
                "total_sections": self.total_sections,
                "matched_sections": self.matched_sections,
                "unmatched_sections": self.unmatched_sections,
                "recalled_questions": self.recalled_questions,
                "empty_questions": self.empty_questions,
                "error_questions": self.error_questions,
                "recall_rate": self.recall_rate,
                "empty_rate": self.empty_rate,
                "section_match_rate": self.section_match_rate,
                "avg_cosine_sim": self.avg_cosine_sim,
                "avg_latency_ms": self.avg_latency_ms,
            },
            "section_stats": [
                {
                    "section_path": s.section_path,
                    "doc_name": s.doc_name,
                    "file_id": s.file_id,
                    "match_type": s.match_type,
                    "total": s.total,
                    "recalled": s.recalled,
                    "empty": s.empty,
                    "errors": s.errors,
                    "avg_cosine_sim": s.avg_cosine_sim,
                    "avg_latency_ms": s.avg_latency_ms,
                }
                for s in self.section_stats
            ],
            "unmatched_sections": self.unmatched_section_list,
            "low_quality_count": len(self.low_quality_results),
            "suspicious_count": len(self.suspicious_results),
        }
        return d

    def save(self, path: str):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)

    def summary_text(self) -> str:
        lines = [
            "=" * 60,
            "  单跳召回测试报告",
            "=" * 60,
            f"  环境地址        : {self.env_url}",
            f"  总问题数        : {self.total_questions}",
            f"  总章节数        : {self.total_sections}",
            f"  章节匹配率      : {self.section_match_rate:.1%}" if self.section_match_rate is not None else "  章节匹配率      : N/A",
            f"  召回率          : {self.recall_rate:.1%}" if self.recall_rate is not None else "  召回率          : N/A",
            f"  空召回率        : {self.empty_rate:.1%}" if self.empty_rate is not None else "  空召回率        : N/A",
            f"  平均余弦相似度  : {self.avg_cosine_sim:.4f}" if self.avg_cosine_sim is not None else "  平均余弦相似度  : N/A",
            f"  平均延迟        : {self.avg_latency_ms:.0f}ms" if self.avg_latency_ms is not None else "  平均延迟        : N/A",
            f"  低质量样例      : {len(self.low_quality_results)}",
            f"  可疑样例        : {len(self.suspicious_results)}",
            "=" * 60,
        ]
        if self.unmatched_section_list:
            lines.append(f"  未匹配章节 ({len(self.unmatched_section_list)}):")
            for s in self.unmatched_section_list[:10]:
                lines.append(f"    - {s}")
            if len(self.unmatched_section_list) > 10:
                lines.append(f"    ... 共 {len(self.unmatched_section_list)} 个")
        return "\n".join(lines)


def build_report(
    results: list[RecallResult],
    env_url: str,
    org_id: str,
    qa_file: str,
    top_k: int,
    cross_chunk: bool,
    quality_info: dict | None = None,
) -> SingleJumpReport:
    report = SingleJumpReport(
        env_url=env_url,
        org_id=org_id,
        qa_file=qa_file,
        top_k=top_k,
        cross_chunk=cross_chunk,
    )

    # 按章节分组
    section_map: dict[str, SectionStats] = {}
    for r in results:
        key = r.section_path
        if key not in section_map:
            section_map[key] = SectionStats(
                section_path=r.section_path,
                doc_name=r.doc_name,
                file_id=r.file_id,
                match_type=r.match_type,
            )
        s = section_map[key]
        s.total += 1
        if r.error:
            s.errors += 1
        elif r.is_empty:
            s.empty += 1
        else:
            s.recalled += 1

    # 计算章节平均指标
    for key, s in section_map.items():
        sec_results = [r for r in results if r.section_path == key and not r.error and not r.is_empty]
        sims = [r.best_cosine_sim for r in sec_results if r.best_cosine_sim is not None]
        lats = [r.latency_ms for r in sec_results if r.latency_ms]
        s.avg_cosine_sim = round(sum(sims) / len(sims), 4) if sims else None
        s.avg_latency_ms = round(sum(lats) / len(lats), 1) if lats else None

    report.section_stats = list(section_map.values())
    report.total_sections = len(section_map)
    report.matched_sections = sum(1 for s in report.section_stats if s.file_id)
    report.unmatched_sections = report.total_sections - report.matched_sections
    report.unmatched_section_list = [
        s.section_path for s in report.section_stats if not s.file_id
    ]

    # 全局统计
    report.total_questions = len(results)
    report.recalled_questions = sum(1 for r in results if not r.error and not r.is_empty)
    report.empty_questions = sum(1 for r in results if not r.error and r.is_empty)
    report.error_questions = sum(1 for r in results if r.error)

    if report.total_questions > 0:
        report.recall_rate = round(report.recalled_questions / report.total_questions, 4)
        report.empty_rate = round(report.empty_questions / report.total_questions, 4)
    if report.total_sections > 0:
        report.section_match_rate = round(report.matched_sections / report.total_sections, 4)

    all_sims = [r.best_cosine_sim for r in results if r.best_cosine_sim is not None]
    all_lats = [r.latency_ms for r in results if r.latency_ms]
    report.avg_cosine_sim = round(sum(all_sims) / len(all_sims), 4) if all_sims else None
    report.avg_latency_ms = round(sum(all_lats) / len(all_lats), 1) if all_lats else None

    if quality_info:
        report.low_quality_results = [
            {"section": r.section_path, "qid": r.qid, "question": r.question, "sim": r.best_cosine_sim}
            for r in quality_info.get("low_quality", [])
        ]
        report.suspicious_results = [
            {"section": r.section_path, "qid": r.qid, "question": r.question,
             "expected_file": r.file_id, "retrieved_files": r.retrieved_file_ids}
            for r in quality_info.get("suspicious", [])
        ]

    return report
