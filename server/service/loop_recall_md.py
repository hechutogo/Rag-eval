# -*- coding: utf-8 -*-
"""
循环测试相关：生成与单跳召回解析器一致的 Markdown 片段。

约定（与 rag_eval.single_jump.parser 对齐）：
- `##` 行在有 `file_name` 时为 `{file_name} / {doc_name}`，便于 FileMapper；
- 完整中文切片名写在 `# 第N章` 与 `> 原始切片标题`；
- 每条问答带可选的 `> chunk_id:`，便于切片级命中校验。
"""
from __future__ import annotations

import re
from collections.abc import Callable, Iterable

DEFAULT_LLM_NOTE = "> 由 LLM 自动生成的问答对"


def doc_name_from_file_name(file_name: str) -> str:
    """知识库路径去扩展名，用于 `## xxx.md / xxx` 的右侧。"""
    fn = (file_name or "").strip()
    if not fn:
        return "document"
    base = fn.rsplit("/", 1)[-1]
    return base.rsplit(".", 1)[0] if "." in base else base


def chapter_title_suffix(slice_title: str, max_len: int = 80) -> str:
    """章节行 `# 第N章 …` 的展示用短标题。"""
    s = (slice_title or "").strip() or "未命名切片"
    s = re.sub(r"\s+", " ", s)
    return s if len(s) <= max_len else s[: max_len - 1] + "…"


def recall_parsed_section_path(file_name: str, slice_title: str) -> tuple[str, str]:
    """
    Returns:
        parsed: `##` 行正文（即解析后的 section_path，与 prebuilt_file_map 键一致）
        doc_suffix: 用于 `# N. {doc_suffix}_Document` 的末段名
    """
    fn = (file_name or "").strip()
    st = (slice_title or "").strip() or "default"
    if fn:
        doc_name = doc_name_from_file_name(fn)
        parsed = f"{fn} / {doc_name}"
        doc_suffix = doc_name.split("/")[-1]
        return parsed, doc_suffix
    raw_doc = st.split("/")[-1].strip() if "/" in st else st
    parsed = f"{st} / {raw_doc}"
    doc_suffix = raw_doc
    return parsed, doc_suffix


def append_recall_md_section(
    lines: list[str],
    section_index: int,
    *,
    file_name: str,
    slice_title: str,
    qa_items: list[dict],
    meta_lines: list[str] | None = None,
    after_answer_lines: Callable[[int, dict], Iterable[str]] | None = None,
) -> str:
    """
    向 lines 追加一个完整 section，返回解析用 section_path（与 `##` 行一致）。

    qa_items: 每项含 question、reference_answer；可选 chunk_id。

    meta_lines: 写在 `# N. xxx_Document` 之后、`---` 之前；None 时仅写入 DEFAULT_LLM_NOTE。

    after_answer_lines: 在每条 `**An:**` 之后、该问答块空行之前插入的额外行。
    """
    parsed, doc_suffix = recall_parsed_section_path(file_name, slice_title)
    ch = chapter_title_suffix(slice_title)
    lines.append(f"# 第{section_index}章 {ch}")
    lines.append(f"## {parsed}")
    st = (slice_title or "").strip()
    if st:
        lines.append(f"> 原始切片标题: {st}")
    lines.append(f"# {section_index}. {doc_suffix}_Document")
    for meta in meta_lines if meta_lines is not None else [DEFAULT_LLM_NOTE]:
        lines.append(meta)
    lines.append("---")
    lines.append("")

    for i, item in enumerate(qa_items, 1):
        lines.append(f"## Q{i}: {item['question']}")
        cid = (item.get("chunk_id") or "").strip()
        if cid:
            lines.append(f"> chunk_id: {cid}")
        lines.append(f"**A{i}:** {item['reference_answer']}")
        if after_answer_lines:
            for L in after_answer_lines(i, item):
                if L:
                    lines.append(L)
        lines.append("")

    lines.append("---")
    lines.append("")
    return parsed
