"""
Loop task API - Automated QA generation and testing with pause/resume.
"""
import asyncio
import json
from io import BytesIO
from typing import Optional

from fastapi import APIRouter, Form, HTTPException, Query
from fastapi.responses import JSONResponse, StreamingResponse

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "sdk"))

from models.db import get_db, _id, _now
from service.loop_recall_md import DEFAULT_LLM_NOTE, append_recall_md_section
from service.loop_engine import (
    run_loop_task, pause_loop, resume_loop, stop_loop,
    _loop_controls, _update_loop_stats
)

router = APIRouter(prefix="/api/loop", tags=["Loop Task"])


@router.post("/task")
async def create_loop_task(
    name: str = Form(...),
    org_id: str = Form(...),
    judge_config_id: str = Form(...),
    file_ids: str = Form(""),  # comma-separated
    questions_per_section: int = Form(5),
    quality_threshold: float = Form(0.6),
    include_multimodal: bool = Form(True),
    env_url: str = Form(...),
    d_user_id: str = Form("test"),
    agent_id: str = Form(""),  # 用于召回测试的 agent ID
    top_k: int = Form(64),
    recall_top_k: int = Form(64),
    concurrency: int = Form(20),
    cross_chunk: bool = Form(True),
    max_rounds: int = Form(0),
    max_questions: int = Form(0),
    global_dedup: bool = Form(False),  # 是否全局去重（跨任务）
    expected_chunk_count: int = Form(0),  # 本批次切片总数，与 chunk_batches_plan.chunk_count 一致；>0 时校验拉取完整性
):
    """Create and start a loop task.

    Args:
        top_k: 用于判断切片/文件是否命中的阈值（默认64）
        recall_top_k: 调用召回API时请求的top_k数量（默认64）
        agent_id: 用于召回测试的 agent ID（可选，为空时直接调用知识库搜索）
        expected_chunk_count: 可选；与批次 chunk_count 一致时，拉取不足会重试并最终失败，避免静默缺切片
    """

    task_id = _id()
    file_id_list = [f.strip() for f in file_ids.split(",") if f.strip()]
    ecc = int(expected_chunk_count) if expected_chunk_count and int(expected_chunk_count) > 0 else None

    async with get_db() as db:
        await db.execute(
            """INSERT INTO loop_task
               (id,name,org_id,judge_config_id,file_ids,questions_per_section,quality_threshold,
                include_multimodal,env_url,d_user_id,agent_id,top_k,recall_top_k,concurrency,cross_chunk,
                status,current_round,max_rounds,max_questions,total_generated,total_approved,
                total_duplicates,total_tested,total_recalled,total_file_hit,total_file_miss,
                total_recall_failed,global_dedup,expected_chunk_count,created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (task_id, name, org_id, judge_config_id, ",".join(file_id_list),
             questions_per_section, quality_threshold, int(include_multimodal),
             env_url, d_user_id, agent_id, top_k, recall_top_k, concurrency, int(cross_chunk),
             "pending", 0, max_rounds, max_questions,
             0, 0, 0, 0, 0, 0, 0, 0, int(global_dedup), ecc, _now()),
        )
        await db.commit()

    # Start the loop in background
    asyncio.create_task(run_loop_task(
        loop_task_id=task_id,
        org_id=org_id,
        file_ids=file_id_list,
        judge_config_id=judge_config_id,
        questions_per_section=questions_per_section,
        quality_threshold=quality_threshold,
        include_multimodal=include_multimodal,
        env_url=env_url,
        d_user_id=d_user_id,
        agent_id=agent_id,
        top_k=top_k,
        recall_top_k=recall_top_k,
        concurrency=concurrency,
        cross_chunk=cross_chunk,
        max_rounds=max_rounds,
        max_questions=max_questions,
        global_dedup=global_dedup,
    ))

    return {"status": 0, "data": {"id": task_id}}


@router.get("/task/list")
async def list_loop_tasks(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    """List all loop tasks with pagination."""
    offset = (page - 1) * page_size

    async with get_db() as db:
        rows = await db.execute_fetchall(
            """SELECT * FROM loop_task
               ORDER BY created_at DESC
               LIMIT ? OFFSET ?""",
            (page_size, offset),
        )
        total = await db.execute_fetchall(
            "SELECT COUNT(*) as cnt FROM loop_task"
        )

    tasks = []
    for row in rows:
        task = dict(row)
        # Calculate derived metrics
        total_tested = task.get("total_tested") or 0
        total_recalled = task.get("total_recalled") or 0
        total_file_hit = task.get("total_file_hit") or 0
        total_file_miss = task.get("total_file_miss") or 0

        task["recall_rate"] = round(total_recalled / total_tested, 4) if total_tested > 0 else 0
        task["file_hit_rate"] = round(total_file_hit / total_recalled, 4) if total_recalled > 0 else 0
        task["file_miss_rate"] = round(total_file_miss / total_recalled, 4) if total_recalled > 0 else 0

        tasks.append(task)

    return {
        "status": 0,
        "data": {
            "total": total[0]["cnt"] if total else 0,
            "items": tasks,
        },
    }


@router.get("/task/{task_id}")
async def get_loop_task(task_id: str):
    """Get loop task details with cumulative stats."""
    async with get_db() as db:
        rows = await db.execute_fetchall(
            "SELECT * FROM loop_task WHERE id=?", (task_id,)
        )

    if not rows:
        raise HTTPException(status_code=404, detail="Task not found")

    task = dict(rows[0])

    # Calculate rates
    total_tested = task.get("total_tested") or 0
    total_recalled = task.get("total_recalled") or 0
    total_file_hit = task.get("total_file_hit") or 0
    total_file_miss = task.get("total_file_miss") or 0

    task["recall_rate"] = round(total_recalled / total_tested, 4) if total_tested > 0 else 0
    task["file_hit_rate"] = round(total_file_hit / total_recalled, 4) if total_recalled > 0 else 0
    task["file_miss_rate"] = round(total_file_miss / total_recalled, 4) if total_recalled > 0 else 0

    return {"status": 0, "data": task}


@router.post("/task/{task_id}/pause")
async def pause_task(task_id: str):
    """Pause a running loop task."""
    result = await pause_loop(task_id)
    if not result:
        raise HTTPException(status_code=400, detail="Task not running")

    # 返回更新后的任务状态
    async with get_db() as db:
        rows = await db.execute_fetchall(
            "SELECT * FROM loop_task WHERE id=?", (task_id,)
        )
    if not rows:
        raise HTTPException(status_code=404, detail="Task not found")

    task = dict(rows[0])
    return {"status": 0, "data": task}


@router.post("/task/{task_id}/resume")
async def resume_task(task_id: str):
    """Resume a paused loop task."""
    async with get_db() as db:
        rows = await db.execute_fetchall(
            "SELECT status FROM loop_task WHERE id=?", (task_id,)
        )
    if not rows:
        raise HTTPException(status_code=404, detail="Task not found")

    if dict(rows[0])["status"] != "paused":
        raise HTTPException(status_code=400, detail="Task not paused")

    # 立即把状态改成 running，让前端马上看到反馈
    async with get_db() as db:
        await db.execute(
            "UPDATE loop_task SET status='running', paused_at=NULL WHERE id=?",
            (task_id,),
        )
        await db.commit()

    # 尝试唤醒内存中的任务
    result = await resume_loop(task_id)
    if not result:
        # 内存中没有（服务重启过），重新启动任务
        async with get_db() as db:
            task_rows = await db.execute_fetchall(
                "SELECT * FROM loop_task WHERE id=?", (task_id,)
            )
        task = dict(task_rows[0])
        file_ids = [f.strip() for f in (task.get("file_ids") or "").split(",") if f.strip()]

        asyncio.create_task(run_loop_task(
            loop_task_id=task_id,
            org_id=task["org_id"],
            file_ids=file_ids,
            judge_config_id=task["judge_config_id"],
            questions_per_section=task["questions_per_section"],
            quality_threshold=task["quality_threshold"],
            include_multimodal=bool(task["include_multimodal"]),
            env_url=task["env_url"],
            d_user_id=task["d_user_id"],
            agent_id=task.get("agent_id", ""),
            top_k=task["top_k"],
            recall_top_k=task.get("recall_top_k", 64),
            concurrency=task["concurrency"],
            cross_chunk=bool(task["cross_chunk"]),
            max_rounds=task["max_rounds"],
            max_questions=task["max_questions"],
            global_dedup=bool(task.get("global_dedup", 0)),
        ))

    # 返回更新后的任务状态
    async with get_db() as db:
        rows = await db.execute_fetchall(
            "SELECT * FROM loop_task WHERE id=?", (task_id,)
        )
    task = dict(rows[0])
    return {"status": 0, "data": task}


@router.post("/task/{task_id}/stop")
async def stop_task(task_id: str):
    """Stop a loop task permanently."""
    # Check task exists and is running or paused
    async with get_db() as db:
        rows = await db.execute_fetchall(
            "SELECT status FROM loop_task WHERE id=?", (task_id,)
        )
    if not rows:
        raise HTTPException(status_code=404, detail="Task not found")

    status = rows[0]["status"]
    if status not in ("running", "paused"):
        raise HTTPException(status_code=400, detail="Task not running or paused")

    # Try to stop via control structure (if running)
    from service.loop_engine import _loop_controls
    ctrl = _loop_controls.get(task_id)
    if ctrl:
        ctrl["stop"] = True
        ctrl["pause_event"].set()

    # Update database status regardless
    async with get_db() as db:
        await db.execute(
            "UPDATE loop_task SET status='stopped', finished_at=? WHERE id=?",
            (_now(), task_id),
        )
        await db.commit()

    return {"status": 0, "data": True}


@router.delete("/task/{task_id}")
async def delete_task(task_id: str):
    """Delete loop task and all related data."""

    # First stop any running background task
    from service.loop_engine import _loop_controls
    ctrl = _loop_controls.get(task_id)
    if ctrl:
        ctrl["stop"] = True
        ctrl["pause_event"].set()
        _loop_controls.pop(task_id, None)

    async with get_db() as db:
        # Get all rounds to delete related tasks
        rounds = await db.execute_fetchall(
            "SELECT qa_gen_task_id, single_jump_task_id FROM loop_round WHERE loop_task_id=?",
            (task_id,),
        )

        for r in rounds:
            qa_id = r["qa_gen_task_id"]
            sj_id = r["single_jump_task_id"]

            # Delete QA questions
            if qa_id:
                await db.execute(
                    "DELETE FROM qa_gen_question WHERE task_id=?", (qa_id,)
                )
                await db.execute(
                    "DELETE FROM qa_gen_task WHERE id=?", (qa_id,)
                )

            # Delete single-jump results
            if sj_id:
                await db.execute(
                    "DELETE FROM single_jump_result WHERE task_id=?", (sj_id,)
                )
                await db.execute(
                    "DELETE FROM single_jump_task WHERE id=?", (sj_id,)
                )

        # Delete rounds
        await db.execute(
            "DELETE FROM loop_round WHERE loop_task_id=?", (task_id,)
        )

        # Delete task
        await db.execute(
            "DELETE FROM loop_task WHERE id=?", (task_id,)
        )

        await db.commit()

    return {"status": 0, "data": True}


@router.get("/task/{task_id}/rounds")
async def get_rounds(task_id: str):
    """Get all rounds for a loop task."""
    async with get_db() as db:
        rows = await db.execute_fetchall(
            """SELECT * FROM loop_round
               WHERE loop_task_id=?
               ORDER BY round_number""",
            (task_id,),
        )
        # Convert rows to dicts while connection is still open
        rounds = [dict(r) for r in rows]

    return {"status": 0, "data": rounds}


@router.get("/task/{task_id}/questions")
async def get_questions(
    task_id: str,
    status: Optional[str] = Query(None),  # approved, rejected, duplicate
    category: Optional[str] = Query(None),  # hit, file_miss, recall_failed
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    """
    Get questions across all rounds.

    - status: filter by qa_gen_question status
    - category: filter by test result category
    """
    offset = (page - 1) * page_size

    # Build query
    where_clauses = ["lr.loop_task_id = ?"]
    params = [task_id]

    if status:
        if status == "duplicate":
            where_clauses.append("q.dup_of IS NOT NULL")
        else:
            where_clauses.append("q.status = ?")
            params.append(status)

    if category:
        if category == "hit":
            where_clauses.append("r.is_file_hit = 1")
        elif category == "file_miss":
            where_clauses.append("r.is_file_hit = 0 AND COALESCE(json_array_length(r.retrieved), 0) > 0")
        elif category == "recall_failed":
            where_clauses.append("COALESCE(json_array_length(r.retrieved), 0) = 0 AND r.error IS NULL")

    where_sql = " AND ".join(where_clauses)

    async with get_db() as db:
        rows = await db.execute_fetchall(
            f"""SELECT
                q.id, q.section_path, q.question, q.reference_answer,
                q.source_chunk, q.quality_score, q.status,
                q.dup_of, q.dup_similarity,
                q.chunk_headers, q.chunk_id, q.file_name,
                lr.round_number,
                r.is_file_hit, r.retrieved, r.best_cosine_sim, r.latency_ms, r.error,
                r.expected_chunk_id, r.is_chunk_hit, r.chunk_hit_rank
            FROM qa_gen_question q
            JOIN loop_round lr ON q.task_id = lr.qa_gen_task_id
            LEFT JOIN single_jump_result r ON r.rowid = (
                SELECT r2.rowid FROM single_jump_result r2
                WHERE r2.task_id = lr.single_jump_task_id AND r2.question = q.question
                ORDER BY r2.rowid DESC LIMIT 1
            )
            WHERE {where_sql}
            ORDER BY lr.round_number DESC, q.created_at DESC
            LIMIT ? OFFSET ?""",
            (*params, page_size, offset),
        )

        # Convert rows to dicts while connection is still open
        questions = [dict(r) for r in rows]

        # Get total count
        total_rows = await db.execute_fetchall(
            f"""SELECT COUNT(DISTINCT q.id) as cnt
            FROM qa_gen_question q
            JOIN loop_round lr ON q.task_id = lr.qa_gen_task_id
            LEFT JOIN single_jump_result r ON r.rowid = (
                SELECT r2.rowid FROM single_jump_result r2
                WHERE r2.task_id = lr.single_jump_task_id AND r2.question = q.question
                ORDER BY r2.rowid DESC LIMIT 1
            )
            WHERE {where_sql}""",
            params,
        )

    return {
        "status": 0,
        "data": {
            "total": total_rows[0]["cnt"] if total_rows else 0,
            "items": questions,
        },
    }


@router.get("/task/{task_id}/export")
async def export_questions(
    task_id: str,
    category: str = Query("all"),  # all, hit, file_miss, recall_failed
    format: str = Query("md"),  # md, json
):
    """Export questions to MD or JSON format."""

    async with get_db() as db:
        # Check if we have qa_gen_task_id in loop_round
        has_qa_task = await db.execute_fetchall(
            """SELECT COUNT(*) as cnt FROM loop_round
               WHERE loop_task_id=? AND qa_gen_task_id IS NOT NULL""",
            (task_id,)
        )

        use_qa_task = has_qa_task[0]["cnt"] > 0 if has_qa_task else False

        # Build where clause based on category
        if use_qa_task:
            # New tasks: query from qa_gen_question and join single_jump_result for expected_chunk_id
            if category == "hit":
                where_clause = "r.is_file_hit = 1"
            elif category == "file_miss":
                where_clause = "r.is_file_hit = 0 AND COALESCE(json_array_length(r.retrieved), 0) > 0"
            elif category == "recall_failed":
                where_clause = "COALESCE(json_array_length(r.retrieved), 0) = 0 AND r.error IS NULL"
            else:  # all
                where_clause = "1=1"

            # 注意：不要用 JOIN qa_gen_question ON chunk_id，同一 chunk 下多题会行膨胀导致导出重复。
            # single_jump_result 若同一 task 下同题干有多行，只取最新一条（rowid 最大）。
            db_rows = await db.execute_fetchall(
                f"""SELECT
                    q.id as qa_question_id,
                    q.section_path, q.file_name, q.question, q.reference_answer,
                    q.source_chunk, q.quality_score, q.status,
                    q.dup_of, q.dup_similarity,
                    q.chunk_headers, q.chunk_id,
                    lr.round_number,
                    r.is_file_hit, r.retrieved, r.best_cosine_sim,
                    r.expected_chunk_id,
                    (SELECT q2b.chunk_headers FROM qa_gen_question q2b
                     WHERE q2b.chunk_id = r.expected_chunk_id
                       AND q2b.chunk_id IS NOT NULL AND trim(COALESCE(q2b.chunk_headers, '')) != ''
                     LIMIT 1) AS expected_chunk_name
                FROM qa_gen_question q
                JOIN loop_round lr ON q.task_id = lr.qa_gen_task_id
                LEFT JOIN single_jump_result r ON r.rowid = (
                    SELECT r2.rowid FROM single_jump_result r2
                    WHERE r2.task_id = lr.single_jump_task_id AND r2.question = q.question
                    ORDER BY r2.rowid DESC LIMIT 1
                )
                WHERE lr.loop_task_id = ? AND q.status = 'approved' AND {where_clause}
                ORDER BY lr.round_number, q.chunk_headers, q.created_at""",
                (task_id,),
            )
        else:
            # Old tasks: query from single_jump_result directly
            if category == "hit":
                where_clause = "r.is_file_hit = 1"
            elif category == "file_miss":
                where_clause = "r.is_file_hit = 0 AND COALESCE(json_array_length(r.retrieved), 0) > 0"
            elif category == "recall_failed":
                where_clause = "COALESCE(json_array_length(r.retrieved), 0) = 0 AND r.error IS NULL"
            else:  # all
                where_clause = "1=1"

            db_rows = await db.execute_fetchall(
                f"""SELECT
                    r.rowid as result_rowid,
                    r.section_path, r.file_name, r.question, r.reference_answer,
                    '' as source_chunk, 1.0 as quality_score, 'approved' as status,
                    NULL as dup_of, NULL as dup_similarity,
                    COALESCE(r.raw_chunk_headers, r.section_path) as chunk_headers,
                    r.expected_chunk_id as chunk_id,
                    lr.round_number,
                    r.is_file_hit, r.retrieved, r.best_cosine_sim,
                    r.expected_chunk_id,
                    (SELECT qb.chunk_headers FROM qa_gen_question qb
                     WHERE qb.chunk_id = r.expected_chunk_id LIMIT 1) AS expected_chunk_name
                FROM single_jump_result r
                JOIN loop_round lr ON r.task_id = lr.single_jump_task_id
                WHERE lr.loop_task_id = ? AND {where_clause}
                ORDER BY lr.round_number, r.section_path""",
                (task_id,),
            )

        # Convert rows to dicts while connection is still open
        rows = [dict(row) for row in db_rows]

    if not rows:
        # Return empty response if no data
        from fastapi.responses import PlainTextResponse
        return PlainTextResponse(
            "没有符合条件的数据",
            status_code=404
        )

    # Group by section
    from collections import defaultdict
    sections: dict[str, list] = defaultdict(list)
    for row in rows:
        # Use chunk_headers as the grouping key if available, otherwise use section_path
        section_key = row.get("chunk_headers") or row.get("section_path") or row.get("file_name") or "default"
        sections[section_key].append(row)

    if format == "json":
        # JSON export
        data = {
            "task_id": task_id,
            "category": category,
            "exported_at": _now(),
            "questions": [],
        }
        for section_path, items in sections.items():
            for item in items:
                data["questions"].append({
                    "section_path": section_path,
                    "file_name": item.get("file_name"),
                    "round": item["round_number"],
                    "question": item["question"],
                    "reference_answer": item["reference_answer"],
                    "source_chunk": item["source_chunk"],
                    "quality_score": item["quality_score"],
                    "status": item["status"],
                    "is_duplicate": bool(item.get("dup_of")),
                    "dup_similarity": item.get("dup_similarity"),
                    "is_file_hit": bool(item.get("is_file_hit")),
                    "recall_results": json.loads(item["retrieved"]) if item.get("retrieved") else [],
                    "best_cosine_sim": item["best_cosine_sim"],
                    "expected_chunk_id": item.get("expected_chunk_id"),
                    "expected_chunk_name": item.get("expected_chunk_name"),
                    "chunk_id": item.get("chunk_id") or item.get("expected_chunk_id"),
                })

        content = json.dumps(data, ensure_ascii=False, indent=2)
        filename = f"loop_{task_id}_{category}.json"
        media_type = "application/json"

    else:
        # MD export：与单跳解析器、循环内单跳 MD、离线脚本同一套 loop_recall_md
        lines: list[str] = []

        def _after_answer(_i: int, item: dict):
            if item.get("expected_chunk_name"):
                yield f"> 预期切片: {item['expected_chunk_name']}"
            sc = item.get("source_chunk")
            if sc:
                yield f"> Source: {str(sc)[:200]}..."

        section_index = 0
        for section_key, items in sections.items():
            section_index += 1
            file_name = (items[0].get("file_name") or "").strip()
            slice_title = (items[0].get("chunk_headers") or "").strip() or section_key
            meta = [f"> 代表轮次: {items[0]['round_number']}", DEFAULT_LLM_NOTE]
            if category != "all":
                meta.insert(0, f"> 导出分类: {category}")
            qa_items = [
                {
                    "question": it["question"],
                    "reference_answer": it["reference_answer"],
                    "chunk_id": (it.get("chunk_id") or it.get("expected_chunk_id") or ""),
                }
                for it in items
            ]
            append_recall_md_section(
                lines,
                section_index,
                file_name=file_name,
                slice_title=slice_title,
                qa_items=qa_items,
                meta_lines=meta,
                after_answer_lines=_after_answer,
            )

        content = "\n".join(lines)
        filename = f"loop_{task_id}_{category}.md"
        media_type = "text/markdown"

    from urllib.parse import quote
    filename_encoded = quote(filename)

    return StreamingResponse(
        BytesIO(content.encode("utf-8")),
        media_type=media_type,
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{filename_encoded}"},
    )
