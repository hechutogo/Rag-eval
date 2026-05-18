"""
多跳问答 MD 文件解析器。

文件格式：
  ## MH1
  **类型:** comparison
  **问题:** A 产品和 B 产品的接口规格有何差异？
  **答案:** A 产品...，B 产品...
  **Hop1:** linux_development / bsp_develop | 该片段提供了 A 产品的接口规格
  **Hop2:** hardware / interface_spec | 该片段提供了 B 产品的接口规格
  ---
"""
import re
from dataclasses import dataclass, field


@dataclass
class Hop:
    section_path: str   # 对应知识库文件的路径标识，与单跳 section_path 格式一致
    contribution: str   # 该 hop 提供了什么信息
    chunk_id: str = ""  # 期望命中的切片 ID（paragraph_chunk_id）；为空则退化为仅文件级命中


@dataclass
class MultiHopQAPair:
    qid: str            # MH1, MH2, ...
    question: str
    answer: str
    hops: list[Hop]     # 至少 2 个
    type: str = "reasoning"   # comparison / reasoning / aggregation


@dataclass
class MultiHopCase:
    """一组多跳问答对，对应一个 MD 文件"""
    qa_pairs: list[MultiHopQAPair] = field(default_factory=list)


def parse_multi_hop_file(filepath: str) -> MultiHopCase:
    with open(filepath, encoding="utf-8") as f:
        content = f.read()
    return parse_multi_hop_text(content)


def parse_multi_hop_text(content: str) -> MultiHopCase:
    """从文本内容解析多跳问答对"""
    case = MultiHopCase()
    current: dict | None = None

    def _flush():
        if not current:
            return
        qid      = current.get("qid", "")
        question = current.get("question", "").strip()
        answer   = current.get("answer", "").strip()
        hops     = current.get("hops", [])
        qtype    = current.get("type", "reasoning")
        if qid and question and answer and len(hops) >= 2:
            case.qa_pairs.append(MultiHopQAPair(
                qid=qid,
                question=question,
                answer=answer,
                hops=hops,
                type=qtype,
            ))

    for line in content.splitlines():
        # 新问题块：## MH1
        m = re.match(r"^## (MH\d+)\s*$", line)
        if m:
            _flush()
            current = {"qid": m.group(1), "hops": []}
            continue

        if current is None:
            continue

        # 类型
        m = re.match(r"^\*\*类型[:：]\*\*\s*(.+)$", line)
        if m:
            current["type"] = m.group(1).strip()
            continue

        # 问题
        m = re.match(r"^\*\*问题[:：]\*\*\s*(.+)$", line)
        if m:
            current["question"] = m.group(1).strip()
            continue

        # 答案
        m = re.match(r"^\*\*答案[:：]\*\*\s*(.+)$", line)
        if m:
            current["answer"] = m.group(1).strip()
            continue

        # Hop：**Hop1:** section_path | contribution [| chunk_id]
        m = re.match(r"^\*\*Hop\d+[:：]\*\*\s*(.+)$", line)
        if m:
            raw = m.group(1).strip()
            parts = [p.strip() for p in raw.split("|")]
            path = parts[0] if parts else ""
            contrib = parts[1] if len(parts) > 1 else ""
            chunk_id = parts[2] if len(parts) > 2 else ""
            current["hops"].append(Hop(
                section_path=path,
                contribution=contrib,
                chunk_id=chunk_id,
            ))
            continue

    _flush()
    return case


def dump_multi_hop_md(qa_pairs: list[MultiHopQAPair]) -> str:
    """将多跳问答对序列化为 MD 格式（用于生成/导出）"""
    lines = []
    for qa in qa_pairs:
        lines.append(f"## {qa.qid}")
        lines.append(f"**类型:** {qa.type}")
        lines.append(f"**问题:** {qa.question}")
        lines.append(f"**答案:** {qa.answer}")
        for i, hop in enumerate(qa.hops, 1):
            if hop.chunk_id:
                lines.append(f"**Hop{i}:** {hop.section_path} | {hop.contribution} | {hop.chunk_id}")
            else:
                lines.append(f"**Hop{i}:** {hop.section_path} | {hop.contribution}")
        lines.append("---")
        lines.append("")
    return "\n".join(lines)
