# -*- coding: utf-8 -*-
"""
从 rag_eval.db 导出指定循环任务批次的问题为单跳召回测试用 Markdown。

默认导出：循环测试_组1_批次1–4 + 组2_批次5–8；版式与 `service.loop_recall_md`、HTTP `/api/loop/.../export` 一致。
"""
from __future__ import annotations

import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

SERVER_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SERVER_ROOT))

from service.loop_recall_md import DEFAULT_LLM_NOTE, append_recall_md_section  # noqa: E402

DB_PATH = SERVER_ROOT / "data" / "rag_eval.db"
OUT_PATH = Path(__file__).resolve().parent.parent.parent / "exports" / "loop_组1组2_共8批次_召回测试问答集.md"

# 循环测试_组1_批次1–4 + 组2_批次5–8（与库中 name 一致）
LOOP_TASK_IDS = (
    "ed60fd467c364945b259ad8835458aa1",  # 组1_批次1
    "e40ddda0d73b4ba690399ebc00c2308f",  # 组1_批次2
    "1dbd2454ac024775a7c00dc376be308d",  # 组1_批次3
    "6f51d327d1aa451883e75ec6067e79d9",  # 组1_批次4
    "7e0a679c851547f68c63e073bd2c8716",  # 组2_批次5
    "9f52a2a526be477c8dfdae27ec978eda",  # 组2_批次6
    "8105a23ee907456ba45ebcd8f3b4ed1b",  # 组2_批次7
    "9d4fcbc5731347a3b5133b72488af6cc",  # 组2_批次8
)


def main() -> None:
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    placeholders = ",".join("?" * len(LOOP_TASK_IDS))
    sql = f"""
    SELECT q.section_path, q.chunk_headers, q.question, q.reference_answer, q.file_name, q.chunk_id,
           q.created_at
    FROM qa_gen_question q
    JOIN loop_round lr ON q.task_id = lr.qa_gen_task_id
    JOIN loop_task lt ON lr.loop_task_id = lt.id
    WHERE lr.loop_task_id IN ({placeholders})
      AND q.status = 'approved'
      AND (q.dup_of IS NULL OR q.dup_of = '')
    ORDER BY q.chunk_headers, q.section_path, q.created_at
    """
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    cur = conn.execute(sql, LOOP_TASK_IDS)

    by_group: dict[str, list[dict]] = defaultdict(list)
    seen_q: set[tuple[str, str]] = set()
    for row in cur:
        d = dict(row)
        gk = (d.get("chunk_headers") or "").strip() or (d.get("section_path") or "default")
        key = (gk, d["question"] or "")
        if key in seen_q:
            continue
        seen_q.add(key)
        by_group[gk].append(d)
    conn.close()

    lines: list[str] = []
    lines.append("# 循环测试组1+组2 共8批次 召回测试问答集")
    lines.append("")
    lines.append(
        "> 由 `export_loop_batches_recall_md.py` 汇总；分组键与循环导出一致（chunk_headers 优先）；"
        "`##` 行在有 file_name 时为 `file_name / doc_name`。"
    )
    lines.append("")

    section_idx = 0
    for gk in sorted(by_group.keys(), key=lambda x: (x or "").lower()):
        rows = by_group[gk]
        if not rows:
            continue
        section_idx += 1
        file_name = (rows[0].get("file_name") or "").strip()
        slice_title = (rows[0].get("chunk_headers") or "").strip() or (rows[0].get("section_path") or gk)
        append_recall_md_section(
            lines,
            section_idx,
            file_name=file_name,
            slice_title=slice_title,
            qa_items=rows,
            meta_lines=[DEFAULT_LLM_NOTE],
        )

    OUT_PATH.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {OUT_PATH} ({section_idx} sections, {len(seen_q)} unique Q&A)")


if __name__ == "__main__":
    main()
