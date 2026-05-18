"""
解析 EVB 知识库问答集 MD 文件，提取结构化问答对。

文件格式：
  # 第N章 章节名
  ## chapter_path / doc_name   ← 知识库文件标识
  # 文档标题
  > 由 LLM 自动生成的问答对
  ---
  ## Q1: 问题
  **A1:** 答案
"""
import re
from dataclasses import dataclass, field


@dataclass
class QAPair:
    qid: str          # Q1, Q2 ...
    question: str
    answer: str
    expected_chunk_id: str | None = None  # 期望命中的切片ID，从MD元数据解析


@dataclass
class Section:
    chapter: str      # 第一章 前言
    section_path: str # preface / overview
    doc_name: str     # overview（最后一段，用于匹配文件名）
    doc_title: str    # 1. 前言
    qa_pairs: list[QAPair] = field(default_factory=list)
    raw_chunk_headers: str | None = None  # 原始切片标题（从元数据解析）


def parse_qa_file(filepath: str) -> list[Section]:
    with open(filepath, encoding="utf-8") as f:
        content = f.read()
    return parse_qa_file_text(content)


def parse_qa_file_text(content: str) -> list[Section]:
    """从文本内容解析问答对（用于 API 上传）"""
    sections: list[Section] = []
    current_chapter = ""
    current_section: Section | None = None
    current_q: str | None = None
    current_q_text: str | None = None
    current_q_chunk_id: str | None = None  # 当前问答对期望的 chunk_id
    answer_lines: list[str] = []

    def _flush_qa():
        nonlocal current_q, current_q_text, answer_lines, current_q_chunk_id
        if current_section and current_q and current_q_text:
            ans = " ".join(answer_lines).strip()
            # 去掉 **A1:** 前缀
            ans = re.sub(r"^\*\*A\d+:\*\*\s*", "", ans)
            current_section.qa_pairs.append(QAPair(
                qid=current_q,
                question=current_q_text,
                answer=ans,
                expected_chunk_id=current_q_chunk_id,
            ))
        current_q = None
        current_q_text = None
        answer_lines = []
        current_q_chunk_id = None

    for line in content.splitlines():
        # 章节标题：# 第N章 ...
        m = re.match(r"^# (第.+章.+)$", line)
        if m:
            current_chapter = m.group(1).strip()
            continue

        # 知识库标识：## chapter / doc_name（排除 ## Q1: 问题 这种问答行）
        # 允许逗号、反引号、括号、问号等切片标题常见符号，避免把中文路径清洗成下划线后才能解析
        m = re.match(r"^## (?!Q\d+:)(.+)$", line)
        if m:
            _flush_qa()
            if current_section:
                sections.append(current_section)
            path = m.group(1).strip()
            parts = [p.strip() for p in path.split("/")]
            doc_name = parts[-1] if parts else path
            current_section = Section(
                chapter=current_chapter,
                section_path=path,
                doc_name=doc_name,
                doc_title="",
            )
            continue

        # 元数据行：> 原始切片标题: xxx
        m = re.match(r"^> 原始切片标题: (.+)$", line)
        if m and current_section:
            current_section.raw_chunk_headers = m.group(1).strip()
            continue

        # 文档标题：# N. 标题
        m = re.match(r"^# (\d[\d\.]*\s+.+)$", line)
        if m and current_section and not current_section.doc_title:
            current_section.doc_title = m.group(1).strip()
            continue

        # 问题行：## Q1: 问题内容
        m = re.match(r"^## (Q\d+):\s*(.+)$", line)
        if m:
            _flush_qa()
            current_q = m.group(1)
            current_q_text = m.group(2).strip()
            continue

        # chunk_id 元数据行：> chunk_id: xxx
        m = re.match(r"^> chunk_id:\s*(\S+)$", line)
        if m and current_q:
            current_q_chunk_id = m.group(1).strip()
            continue

        # 答案行：**A1:** 答案内容
        if current_q and re.match(r"^\*\*A\d+:\*\*", line):
            ans = re.sub(r"^\*\*A\d+:\*\*\s*", "", line).strip()
            answer_lines = [ans]
            continue

        # 答案续行（非空、非分隔符、非新问题）
        if current_q and answer_lines is not None and line.strip() and not line.startswith("#") and line != "---":
            answer_lines.append(line.strip())

    _flush_qa()
    if current_section:
        sections.append(current_section)

    return sections
