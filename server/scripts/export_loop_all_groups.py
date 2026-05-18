#!/usr/bin/env python3
"""Export all loop-test Q&A batches for remote dagent from SQLite (fast path)."""
from __future__ import annotations

import json
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
DB_PATH = ROOT / "server" / "data" / "rag_eval.db"
PLAN_PATH = ROOT / "docs" / "task_groups_plan.json"
EXPORT_DIR = ROOT / "docs" / "exports"
sys.path.insert(0, str(ROOT / "server"))
sys.path.insert(0, str(ROOT / "server" / "service"))
from loop_recall_md import DEFAULT_LLM_NOTE, append_recall_md_section  # noqa: E402


def get_task_questions_fast(conn: sqlite3.Connection, task_id: str) -> list[dict]:
    """Approved Q&A from qa_gen_question; fallback to single_jump_result for legacy tasks."""
    cursor = conn.cursor()
    cursor.execute(
        """SELECT COUNT(*) as cnt FROM loop_round
           WHERE loop_task_id=? AND qa_gen_task_id IS NOT NULL""",
        (task_id,),
    )
    if cursor.fetchone()["cnt"] > 0:
        cursor.execute(
            """SELECT
                q.id as qa_question_id,
                q.section_path, q.file_name, q.question, q.reference_answer,
                q.source_chunk, q.quality_score, q.status,
                q.dup_of, q.dup_similarity,
                q.chunk_headers, q.chunk_id, q.file_id,
                lr.round_number
            FROM qa_gen_question q
            JOIN loop_round lr ON q.task_id = lr.qa_gen_task_id
            WHERE lr.loop_task_id = ? AND q.status = 'approved'
            ORDER BY lr.round_number, q.chunk_headers, q.created_at""",
            (task_id,),
        )
        return [dict(row) for row in cursor.fetchall()]

    cursor.execute(
        """SELECT
            r.section_path, r.file_name, r.question, r.reference_answer,
            COALESCE(r.raw_chunk_headers, r.section_path) as chunk_headers,
            r.expected_chunk_id as chunk_id,
            lr.round_number
        FROM single_jump_result r
        JOIN loop_round lr ON r.task_id = lr.single_jump_task_id
        WHERE lr.loop_task_id = ?
        ORDER BY lr.round_number, r.section_path""",
        (task_id,),
    )
    rows = []
    for row in cursor.fetchall():
        d = dict(row)
        d.setdefault("quality_score", 1.0)
        d.setdefault("status", "approved")
        rows.append(d)
    return rows


def rows_to_md(rows: list[dict]) -> str:
    if not rows:
        return ""
    sections: dict[str, list] = defaultdict(list)
    for row in rows:
        key = row.get("chunk_headers") or row.get("section_path") or row.get("file_name") or "default"
        sections[key].append(row)

    lines: list[str] = []
    for section_index, (section_key, items) in enumerate(sections.items(), 1):
        file_name = (items[0].get("file_name") or "").strip()
        slice_title = (items[0].get("chunk_headers") or "").strip() or section_key
        meta = [f"> 代表轮次: {items[0]['round_number']}", DEFAULT_LLM_NOTE]
        qa_items = [
            {
                "question": it["question"],
                "reference_answer": it["reference_answer"],
                "chunk_id": (it.get("chunk_id") or ""),
            }
            for it in items
        ]
        append_recall_md_section(
            lines, section_index,
            file_name=file_name, slice_title=slice_title,
            qa_items=qa_items, meta_lines=meta,
        )
    return "\n".join(lines)


def rows_to_json_questions(rows: list[dict]) -> list[dict]:
    return [
        {
            "section_path": r.get("section_path"),
            "file_name": r.get("file_name"),
            "file_id": r.get("file_id"),
            "chunk_headers": r.get("chunk_headers"),
            "chunk_id": r.get("chunk_id"),
            "round": r.get("round_number"),
            "question": r["question"],
            "reference_answer": r["reference_answer"],
            "source_chunk": r.get("source_chunk"),
            "quality_score": r.get("quality_score"),
            "status": r.get("status"),
            "is_duplicate": bool(r.get("dup_of")),
            "dup_similarity": r.get("dup_similarity"),
            "qa_question_id": r.get("qa_question_id"),
        }
        for r in rows
    ]


def resolve_task_id_from_db(conn: sqlite3.Connection, group_id: int, batch_id: int) -> dict | None:
    """Pick the loop_task with most approved questions when duplicates exist."""
    name = f"循环测试_组{group_id}_批次{batch_id}"
    cur = conn.cursor()
    cur.execute(
        """SELECT id, name, status, total_approved, env_url, created_at
           FROM loop_task
           WHERE name=? AND env_url LIKE '%dagent%'
           ORDER BY total_approved DESC, created_at DESC
           LIMIT 1""",
        (name,),
    )
    row = cur.fetchone()
    return dict(row) if row else None


def build_export_plan(conn: sqlite3.Connection, plan: dict) -> list[dict]:
    """Merge task_groups_plan with DB tasks for pending groups missing task_ids."""
    groups_by_id = {g["task_group_id"]: dict(g) for g in plan.get("task_groups") or []}
    for gid in range(1, 15):
        if gid not in groups_by_id:
            groups_by_id[gid] = {"task_group_id": gid, "batch_ids": [], "status": "unknown", "task_ids": []}

    for gid, group in groups_by_id.items():
        batch_ids = list(group.get("batch_ids") or [])
        plan_tasks = {t["batch_id"]: t for t in (group.get("task_ids") or [])}

        # Infer batch ids from DB when plan only has pending stub
        if not batch_ids:
            cur = conn.cursor()
            cur.execute(
                """SELECT DISTINCT CAST(substr(name, instr(name, '批次') + 2) AS INTEGER) AS bid
                   FROM loop_task
                   WHERE name LIKE ? AND env_url LIKE '%dagent%'
                   ORDER BY bid""",
                (f"循环测试_组{gid}_批次%",),
            )
            batch_ids = [r["bid"] for r in cur.fetchall() if r["bid"]]

        merged_tasks = []
        for bid in sorted(batch_ids):
            if bid in plan_tasks and plan_tasks[bid].get("task_id"):
                merged_tasks.append(plan_tasks[bid])
                continue
            db_task = resolve_task_id_from_db(conn, gid, bid)
            if db_task:
                merged_tasks.append({
                    "batch_id": bid,
                    "task_id": db_task["id"],
                    "task_name": db_task["name"],
                    "db_status": db_task["status"],
                    "total_approved": db_task["total_approved"],
                })
        group["task_ids"] = merged_tasks
        group["batch_ids"] = batch_ids

    return [groups_by_id[i] for i in sorted(groups_by_id)]


def main():
    if not DB_PATH.exists():
        print(f"Database not found: {DB_PATH}")
        sys.exit(1)

    plan = json.loads(PLAN_PATH.read_text(encoding="utf-8")) if PLAN_PATH.exists() else {}
    exported_at = datetime.now().isoformat()
    env = plan.get("environment", "")
    org_id = plan.get("org_id", "")

    EXPORT_DIR.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only=ON")
    export_groups = build_export_plan(conn, plan)

    md_parts = [
        "# 远程 dagent 循环测试 — 全部组别批次问答集汇总\n",
        f"\n> 导出时间: {exported_at}\n> 环境: {env}\n> 组织ID: {org_id}\n> 说明: 已批准问答（qa_gen_question.status=approved）\n\n---\n",
    ]
    json_export = {
        "exported_at": exported_at,
        "environment": env,
        "org_id": org_id,
        "source_db": str(DB_PATH),
        "task_groups": [],
        "summary": {"groups": 0, "batches": 0, "batches_with_data": 0, "total_questions": 0},
    }

    total_batches = batches_with_data = total_questions = 0

    for group in export_groups:
        gid = group.get("task_group_id")
        gstatus = group.get("status", "unknown")
        group_entry = {
            "task_group_id": gid,
            "status": gstatus,
            "batch_ids": group.get("batch_ids", []),
            "total_chunks": group.get("total_chunks"),
            "total_files": group.get("total_files"),
            "completed_at": group.get("completed_at"),
            "batches": [],
        }
        json_export["task_groups"].append(group_entry)
        json_export["summary"]["groups"] += 1

        md_parts.append(f"\n# 任务组 {gid}（{gstatus}）\n批次: {group.get('batch_ids', [])}\n")

        for ti in group.get("task_ids") or []:
            task_id, task_name, batch_id = ti["task_id"], ti.get("task_name"), ti.get("batch_id")
            total_batches += 1
            print(f"组{gid} 批次{batch_id} {task_name}", flush=True)
            rows = get_task_questions_fast(conn, task_id)
            n = len(rows)
            total_questions += n
            group_entry["batches"].append({
                "batch_id": batch_id,
                "task_id": task_id,
                "task_name": task_name,
                "chunk_count": ti.get("chunk_count"),
                "question_count": n,
                "questions": rows_to_json_questions(rows),
            })
            if n:
                batches_with_data += 1
                md_parts.append(f"\n## 批次 {batch_id}: {task_name}（{n} 题）\n\n{rows_to_md(rows)}\n\n---\n")
            else:
                md_parts.append(f"\n## 批次 {batch_id}: {task_name}（无数据）\n\n---\n")

    conn.close()
    json_export["summary"].update(
        batches=total_batches,
        batches_with_data=batches_with_data,
        total_questions=total_questions,
    )

    md_path = EXPORT_DIR / "loop_dagent_全部组别批次_问答集汇总.md"
    json_path = EXPORT_DIR / "loop_dagent_全部组别批次_问答集汇总.json"
    md_path.write_text("".join(md_parts), encoding="utf-8")
    json_path.write_text(json.dumps(json_export, ensure_ascii=False, indent=2), encoding="utf-8")

    print("=" * 60)
    print(f"完成: {json_export['summary']['groups']} 组, {batches_with_data}/{total_batches} 批有数据, {total_questions} 题")
    print(md_path)
    print(json_path)


if __name__ == "__main__":
    main()
