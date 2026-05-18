"""
单跳召回测试 API
"""
import asyncio
import json
import sys
from pathlib import Path
from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from fastapi.responses import StreamingResponse
from typing import Optional, Any, List
from pydantic import BaseModel
import aiohttp

# Fix Windows GBK encoding issue
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.stderr.reconfigure(encoding='utf-8', errors='replace')

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "sdk"))
sys.path.insert(0, str(Path(__file__).parent.parent))

from models.db import get_db, _now, _id

router = APIRouter(prefix="/api/single-jump", tags=["单跳召回测试"])


@router.post("/task")
async def create_task(
    file: UploadFile = File(...),
    name: str = Form(""),
    env_url: str = Form(...),
    org_id: str = Form(...),
    d_user_id: str = Form("test"),
    agent_id: str = Form(""),
    top_k: int = Form(64),
    recall_top_k: int = Form(64),
    concurrency: int = Form(20),  # 增加默认并发数到20
    cross_chunk: str = Form("true"),
):
    """上传 MD 问答集文件并创建测试任务

    Args:
        top_k: 用于判断切片/文件是否命中的阈值（默认64）
        recall_top_k: 调用召回API时请求的top_k数量（默认64）
        agent_id: 用于召回测试的 agent ID（可选，为空时直接调用知识库搜索）
    """
    content = await file.read()
    qa_text = content.decode("utf-8")

    cross_chunk_bool = cross_chunk.lower() in ("true", "1", "yes")

    task_id = _id()
    async with get_db() as db:
        await db.execute(
            """INSERT INTO single_jump_task
               (id,name,env_url,org_id,d_user_id,agent_id,top_k,recall_top_k,concurrency,cross_chunk,status,created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (task_id, name or file.filename, env_url, org_id,
             d_user_id, agent_id, top_k, recall_top_k, concurrency, int(cross_chunk_bool),
             "pending", _now()),
        )
        await db.commit()

    # 后台运行
    asyncio.create_task(_run_task(task_id, qa_text, env_url, org_id, d_user_id, agent_id, top_k, recall_top_k, concurrency, cross_chunk_bool))
    return {"status": 0, "data": {"id": task_id}}


@router.post("/task/batch")
async def create_task_batch(
    files: List[UploadFile] = File(...),
    name: str = Form(""),
    env_url: str = Form(...),
    org_id: str = Form(...),
    d_user_id: str = Form("test"),
    agent_id: str = Form(""),
    top_k: int = Form(64),
    recall_top_k: int = Form(64),
    concurrency: int = Form(20),  # 增加默认并发数到20
    cross_chunk: str = Form("true"),
):
    """上传文件夹下多个 MD 问答集文件，合并为一个测试任务"""
    cross_chunk_bool = cross_chunk.lower() in ("true", "1", "yes")

    # 合并所有文件内容，每个文件单独解析后拼接
    all_sections_text = ""
    for f in files:
        if not f.filename.endswith(".md"):
            continue
        content = await f.read()
        all_sections_text += content.decode("utf-8") + "\n"

    if not all_sections_text.strip():
        raise HTTPException(status_code=400, detail="没有有效的 MD 文件")

    task_id = _id()
    task_name = name or f"批量任务({len(files)}个文件)"
    async with get_db() as db:
        await db.execute(
            """INSERT INTO single_jump_task
               (id,name,env_url,org_id,d_user_id,agent_id,top_k,recall_top_k,concurrency,cross_chunk,status,created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (task_id, task_name, env_url, org_id,
             d_user_id, agent_id, top_k, recall_top_k, concurrency, int(cross_chunk_bool),
             "pending", _now()),
        )
        await db.commit()

    asyncio.create_task(_run_task(task_id, all_sections_text, env_url, org_id, d_user_id, agent_id, top_k, recall_top_k, concurrency, cross_chunk_bool))
    return {"status": 0, "data": {"id": task_id}}


@router.get("/task/list")
async def list_tasks():
    async with get_db() as db:
        rows = await db.execute_fetchall(
            "SELECT * FROM single_jump_task ORDER BY created_at DESC"
        )
        return {"status": 0, "data": [dict(r) for r in rows]}


@router.get("/task/{task_id}")
async def get_task(task_id: str):
    async with get_db() as db:
        rows = await db.execute_fetchall(
            "SELECT * FROM single_jump_task WHERE id=?", (task_id,)
        )
        if not rows:
            raise HTTPException(status_code=404, detail="Task not found")
        return {"status": 0, "data": dict(rows[0])}


@router.delete("/task/{task_id}")
async def delete_task(task_id: str):
    async with get_db() as db:
        await db.execute("DELETE FROM single_jump_result WHERE task_id=?", (task_id,))
        await db.execute("DELETE FROM single_jump_task WHERE id=?", (task_id,))
        await db.commit()
    return {"status": 0, "data": True}


@router.get("/task/{task_id}/results")
async def get_results(task_id: str, section: Optional[str] = None):
    async with get_db() as db:
        task_rows = await db.execute_fetchall(
            "SELECT env_url, org_id, d_user_id FROM single_jump_task WHERE id=?",
            (task_id,),
        )
        task = dict(task_rows[0]) if task_rows else {}
        # 优先使用 raw_chunk_headers，如果没有则关联 qa_gen_question 获取
        join_sql = """
            SELECT r.*,
                   COALESCE(r.raw_chunk_headers, q.chunk_headers) as expected_chunk_name
            FROM single_jump_result r
            LEFT JOIN qa_gen_question q ON r.expected_chunk_id = q.chunk_id AND r.question = q.question
            WHERE r.task_id=? {section_filter}
            ORDER BY r.section_path, r.qid
        """
        section_filter = f"AND r.section_path='{section}'" if section else ""
        rows = await db.execute_fetchall(
            join_sql.format(section_filter=section_filter),
            (task_id,),
        )
        # Convert rows to dicts while connection is still open
        row_dicts = [dict(r) for r in rows]

    file_name_map = await _fetch_file_name_map(
        task.get("env_url", ""),
        task.get("org_id", ""),
        task.get("d_user_id", "test"),
    )
    results = []
    for d in row_dicts:
        d["retrieved"] = json.loads(d.get("retrieved") or "[]")
        for item in d["retrieved"]:
            fid = item.get("file_id")
            if fid:
                item["display_file_name"] = item.get("file_name") or file_name_map.get(fid, "")
        if d.get("file_id"):
            d["expected_file_name"] = d.get("file_name") or file_name_map.get(d["file_id"], "")
        results.append(d)
    return {"status": 0, "data": results}


@router.get("/task/{task_id}/sections")
async def get_sections(task_id: str):
    """返回任务的章节列表及每章节的统计"""
    async with get_db() as db:
        rows = await db.execute_fetchall(
            """SELECT section_path, doc_name, file_id, file_name, match_type,
                      COUNT(*) as total,
                      SUM(CASE WHEN error IS NULL AND COALESCE(json_array_length(retrieved), 0) > 0 THEN 1 ELSE 0 END) as recalled,
                      SUM(CASE WHEN error IS NOT NULL THEN 1 ELSE 0 END) as errors,
                      AVG(best_cosine_sim) as avg_sim,
                      SUM(is_file_hit) as file_hits
               FROM single_jump_result
               WHERE task_id=?
               GROUP BY section_path
               ORDER BY section_path""",
            (task_id,),
        )
        return {"status": 0, "data": [dict(r) for r in rows]}


@router.get("/task/{task_id}/summary")
async def get_summary(task_id: str):
    """返回任务的汇总指标"""
    async with get_db() as db:
        task_rows = await db.execute_fetchall(
            "SELECT * FROM single_jump_task WHERE id=?", (task_id,)
        )
        if not task_rows:
            raise HTTPException(status_code=404)
        task = dict(task_rows[0])

        rows = await db.execute_fetchall(
            """SELECT
                COUNT(*) as total,
                SUM(CASE WHEN error IS NULL AND json_array_length(retrieved) > 0 THEN 1 ELSE 0 END) as recalled,
                SUM(CASE WHEN error IS NULL AND COALESCE(json_array_length(retrieved), 0) = 0 THEN 1 ELSE 0 END) as empty,
                SUM(CASE WHEN error IS NOT NULL THEN 1 ELSE 0 END) as errors,
                AVG(best_cosine_sim) as avg_cosine_sim,
                AVG(latency_ms) as avg_latency_ms,
                SUM(is_file_hit) as file_hits,
                SUM(CASE WHEN error IS NULL AND COALESCE(json_array_length(retrieved), 0) > 0 AND is_file_hit=0 THEN 1 ELSE 0 END) as file_miss,
                SUM(is_chunk_hit) as chunk_hits,
                SUM(CASE WHEN expected_chunk_id IS NOT NULL AND expected_chunk_id != '' THEN 1 ELSE 0 END) as has_chunk_id,
                AVG(CASE WHEN is_chunk_hit=1 THEN chunk_hit_rank END) as avg_chunk_hit_rank,
                COUNT(DISTINCT section_path) as total_sections,
                COUNT(DISTINCT CASE WHEN file_id IS NOT NULL THEN section_path END) as matched_sections
               FROM single_jump_result WHERE task_id=?""",
            (task_id,),
        )
        stats = dict(rows[0]) if rows else {}

    total = stats.get("total") or 0
    recalled = stats.get("recalled") or 0
    file_hits = stats.get("file_hits") or 0
    chunk_hits = stats.get("chunk_hits") or 0
    has_chunk_id = stats.get("has_chunk_id") or 0

    return {
        "status": 0,
        "data": {
            **task,
            "total_questions": total,
            "recalled_questions": recalled,
            "empty_questions": stats.get("empty") or 0,
            "error_questions": stats.get("errors") or 0,
            "file_miss_questions": stats.get("file_miss") or 0,
            "recall_rate": round(recalled / total, 4) if total else None,
            "file_hit_rate": round(file_hits / recalled, 4) if recalled else None,
            "chunk_hits": chunk_hits,
            "has_chunk_id_questions": has_chunk_id,
            "chunk_hit_rate": round(chunk_hits / has_chunk_id, 4) if has_chunk_id else None,
            "avg_chunk_hit_rank": round(stats["avg_chunk_hit_rank"], 2) if stats.get("avg_chunk_hit_rank") else None,
            "avg_cosine_sim": round(stats["avg_cosine_sim"], 4) if stats.get("avg_cosine_sim") else None,
            "avg_latency_ms": round(stats["avg_latency_ms"], 1) if stats.get("avg_latency_ms") else None,
            "total_sections": stats.get("total_sections") or 0,
            "matched_sections": stats.get("matched_sections") or 0,
        },
    }


@router.get("/task/{task_id}/export-failed-md")
async def export_failed_md(task_id: str):
    """导出召回失败的问题为 MD 文件"""
    async with get_db() as db:
        task_rows = await db.execute_fetchall(
            "SELECT name FROM single_jump_task WHERE id=?", (task_id,)
        )
        if not task_rows:
            raise HTTPException(status_code=404, detail="Task not found")
        task_name = dict(task_rows[0]).get("name", task_id)

        rows = await db.execute_fetchall(
            """SELECT section_path, doc_name, qid, question, reference_answer
               FROM single_jump_result
               WHERE task_id=? AND error IS NULL AND json_array_length(retrieved)=0
               ORDER BY section_path, qid""",
            (task_id,),
        )
        # Convert rows to dicts while connection is still open
        row_dicts = [dict(r) for r in rows]

    if not row_dicts:
        raise HTTPException(status_code=404, detail="没有召回失败的问题")

    # 按 section_path 分组，重新生成 MD
    from collections import defaultdict
    sections: dict[str, list] = defaultdict(list)
    for d in row_dicts:
        sections[d["section_path"]].append(d)

    lines = []
    for section_path, items in sections.items():
        lines.append(f"## {section_path}")
        lines.append("")
        for item in items:
            lines.append(f"## {item['qid']}: {item['question']}")
            lines.append(f"**{item['qid'].replace('Q', 'A')}:** {item['reference_answer']}")
            lines.append("")
        lines.append("---")
        lines.append("")

    md_content = "\n".join(lines)

    from urllib.parse import quote
    filename = f"failed_{task_name}.md".replace(" ", "_")
    filename_encoded = quote(filename)
    return StreamingResponse(
        iter([md_content.encode("utf-8")]),
        media_type="text/markdown",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{filename_encoded}"},
    )


@router.get("/task/{task_id}/export-file-miss-md")
async def export_file_miss_md(task_id: str):
    """导出文件命中失败的问题为 MD 文件（有召回但未命中预期文件）"""
    async with get_db() as db:
        task_rows = await db.execute_fetchall(
            "SELECT name FROM single_jump_task WHERE id=?", (task_id,)
        )
        if not task_rows:
            raise HTTPException(status_code=404, detail="Task not found")
        task_name = dict(task_rows[0]).get("name", task_id)

        rows = await db.execute_fetchall(
            """SELECT section_path, doc_name, qid, question, reference_answer, file_name
               FROM single_jump_result
               WHERE task_id=? AND error IS NULL AND COALESCE(json_array_length(retrieved), 0)>0 AND is_file_hit=0
               ORDER BY section_path, qid""",
            (task_id,),
        )
        # Convert rows to dicts while connection is still open
        row_dicts = [dict(r) for r in rows]

    if not row_dicts:
        raise HTTPException(status_code=404, detail="没有文件命中失败的问题")

    # 按 section_path 分组，重新生成 MD
    from collections import defaultdict
    sections: dict[str, list] = defaultdict(list)
    for d in row_dicts:
        sections[d["section_path"]].append(d)

    lines = []
    for section_path, items in sections.items():
        lines.append(f"## {section_path}")
        expected_file = items[0].get("file_name", "未知文件") if items else "未知文件"
        lines.append(f"**预期文件:** {expected_file}")
        lines.append("")
        for item in items:
            lines.append(f"## {item['qid']}: {item['question']}")
            lines.append(f"**{item['qid'].replace('Q', 'A')}:** {item['reference_answer']}")
            lines.append("")
        lines.append("---")
        lines.append("")

    md_content = "\n".join(lines)

    from urllib.parse import quote
    filename = f"file_miss_{task_name}.md".replace(" ", "_")
    filename_encoded = quote(filename)
    return StreamingResponse(
        iter([md_content.encode("utf-8")]),
        media_type="text/markdown",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{filename_encoded}"},
    )


@router.get("/task/{task_id}/agent-recall")
async def get_agent_recall(task_id: str, result_id: str, agent_id: str):
    """Fetch online agent recall documents for one question result."""
    if not agent_id:
        raise HTTPException(status_code=400, detail="agent_id is required")
    async with get_db() as db:
        task_rows = await db.execute_fetchall(
            "SELECT env_url, org_id, d_user_id FROM single_jump_task WHERE id=?",
            (task_id,),
        )
        if not task_rows:
            raise HTTPException(status_code=404, detail="Task not found")
        task = dict(task_rows[0])
        result_rows = await db.execute_fetchall(
            "SELECT id, qid, question FROM single_jump_result WHERE id=? AND task_id=?",
            (result_id, task_id),
        )
        if not result_rows:
            raise HTTPException(status_code=404, detail="Result not found")
        result = dict(result_rows[0])
    recalls = await _fetch_agent_recall_docs(
        env_url=task.get("env_url", ""),
        org_id=task.get("org_id", ""),
        d_user_id=task.get("d_user_id", "test"),
        agent_id=agent_id,
        question=result.get("question", ""),
    )
    return {"status": 0, "data": {"qid": result.get("qid"), "question": result.get("question"), "items": recalls}}


@router.get("/task/{task_id}/agents")
async def get_agents(task_id: str):
    """Fetch selectable online agents for the task org."""
    async with get_db() as db:
        task_rows = await db.execute_fetchall(
            "SELECT env_url, org_id, d_user_id FROM single_jump_task WHERE id=?",
            (task_id,),
        )
        if not task_rows:
            raise HTTPException(status_code=404, detail="Task not found")
        task = dict(task_rows[0])
    agents = await _fetch_agent_list(
        env_url=task.get("env_url", ""),
        org_id=task.get("org_id", ""),
        d_user_id=task.get("d_user_id", "test"),
    )
    return {"status": 0, "data": agents}


async def _run_task(task_id: str, qa_text: str, env_url: str, org_id: str,
                    d_user_id: str, agent_id: str, hit_top_k: int, recall_top_k: int, concurrency: int, cross_chunk: bool,
                    prebuilt_file_map: dict = None, prebuilt_chunk_map: dict = None):
    """后台执行单跳测试

    Args:
        prebuilt_file_map: 预构建的 section_path -> {file_id, file_name, match_type} 映射
                          如果提供，则跳过 FileMapper 的自动匹配
        prebuilt_chunk_map: 预构建的 question -> chunk_id 映射，用于切片级别验证
    """
    from rag_eval.single_jump.parser import parse_qa_file_text
    from rag_eval.single_jump.mapper import FileMapper
    from rag_eval.single_jump.tester import RecallTester

    try:
        sections = parse_qa_file_text(qa_text)
        total = sum(len(s.qa_pairs) for s in sections)
        print(f"[{task_id}] Starting single-jump test: {total} questions from {len(sections)} sections")

        async with get_db() as db:
            await db.execute(
                "UPDATE single_jump_task SET status='running', total=? WHERE id=?",
                (total, task_id),
            )
            await db.commit()

        # 文件映射（带缓存）
        mapper = FileMapper(env_url=env_url, org_id=org_id, d_user_id=d_user_id)
        file_count = await mapper.load_files()
        print(f"[{task_id}] Loaded {file_count} files from knowledge base")
        file_name_map = {f["id"]: f["file_name"] for f in mapper.files if f.get("id")}

        file_map = {}
        if prebuilt_file_map:
            # 使用预构建的映射（来自 QA 生成任务）
            for s in sections:
                if s.section_path in prebuilt_file_map:
                    file_map[s.section_path] = prebuilt_file_map[s.section_path]
                else:
                    # 如果预构建映射中没有，尝试自动匹配
                    file_map[s.section_path] = mapper.map_section_to_file(s.section_path)
        else:
            # 使用 FileMapper 自动匹配
            for s in sections:
                if s.section_path not in file_map:
                    file_map[s.section_path] = mapper.map_section_to_file(s.section_path)

        # 如果没有预构建的 chunk_map，尝试从数据库查询 question -> chunk_id 映射
        # 这样可以支持上传的 MD 文件也能做切片级别对比
        chunk_map = prebuilt_chunk_map
        if not chunk_map:
            chunk_map = await _build_chunk_map_from_db(sections)
            if chunk_map:
                print(f"[{task_id}] Built chunk_map with {len(chunk_map)} entries from qa_gen_question table")

        # 执行召回，边跑边写库（每批 result_cb 触发一次 INSERT + progress 更新）
        tester = RecallTester(env_url=env_url, org_id=org_id, d_user_id=d_user_id)
        write_buf: list = []
        FLUSH_SIZE = 100  # 增大批量写入大小以提高性能

        async def flush_buf(buf: list, progress: int):
            async with get_db() as db2:
                for r in buf:
                    mapping = file_map.get(r.section_path)
                    expected_file_id = mapping["file_id"] if mapping else None
                    expected_file_name = mapping["file_name"] if mapping else None
                    is_file_hit = 0
                    if expected_file_id and r.retrieved_file_ids:
                        is_file_hit = 1 if expected_file_id in r.retrieved_file_ids else 0

                    # 切片级别验证：优先用 tester 层已设置的 expected_chunk_id
                    expected_chunk_id = r.expected_chunk_id or (
                        chunk_map.get(r.question) if chunk_map else None
                    )
                    is_chunk_hit = 0
                    chunk_hit_rank = None
                    retrieved_chunk_ids = r.retrieved_chunk_ids
                    if expected_chunk_id:
                        if expected_chunk_id in retrieved_chunk_ids:
                            is_chunk_hit = 1
                            chunk_hit_rank = retrieved_chunk_ids.index(expected_chunk_id) + 1

                    retrieved_with_name = []
                    for item in r.retrieved:
                        copied = dict(item)
                        fid = copied.get("file_id")
                        if fid and not copied.get("file_name"):
                            copied["file_name"] = file_name_map.get(fid, "")
                        retrieved_with_name.append(copied)
                    await db2.execute(
                        """INSERT INTO single_jump_result
                           (id,task_id,section_path,doc_name,file_id,file_name,match_type,qid,question,
                            reference_answer,top_k,hit_top_k,retrieved,latency_ms,error,
                            best_cosine_sim,avg_cosine_sim,is_file_hit,
                            expected_chunk_id,is_chunk_hit,chunk_hit_rank,retrieved_chunk_ids,raw_chunk_headers)
                           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (
                            _id(), task_id, r.section_path, r.doc_name,
                            r.file_id, expected_file_name, r.match_type, r.qid, r.question,
                            r.reference_answer, r.top_k, r.hit_top_k,
                            json.dumps(retrieved_with_name, ensure_ascii=False),
                            r.latency_ms, r.error,
                            r.best_cosine_sim, r.avg_cosine_sim,
                            is_file_hit, expected_chunk_id or "", is_chunk_hit, chunk_hit_rank,
                            json.dumps(retrieved_chunk_ids, ensure_ascii=False),
                            r.raw_chunk_headers or "",
                        ),
                    )
                await db2.execute(
                    "UPDATE single_jump_task SET progress=? WHERE id=?", (progress, task_id)
                )
                await db2.commit()

        async def result_cb(r, done: int, _total: int):
            write_buf.append(r)
            if len(write_buf) >= FLUSH_SIZE or done == _total:
                batch = write_buf.copy()
                write_buf.clear()
                await flush_buf(batch, done)
                # 每100条记录打印一次进度
                if done % 100 == 0 or done == _total:
                    print(f"[{task_id}] Progress: {done}/{_total} ({done*100//_total}%)")

        print(f"[{task_id}] Starting recall test with concurrency={concurrency}, hit_top_k={hit_top_k}, recall_top_k={recall_top_k}, agent_id={agent_id}")
        await tester.run(
            sections=sections,
            file_map=file_map,
            top_k=hit_top_k,
            recall_top_k=recall_top_k,
            concurrency=concurrency,
            cross_chunk=cross_chunk,
            result_cb=result_cb,
            chunk_map=chunk_map,
            agent_id=agent_id,
        )

        # 刷新剩余的缓冲区数据
        if write_buf:
            print(f"[{task_id}] Flushing remaining {len(write_buf)} items from buffer")
            batch = write_buf.copy()
            write_buf.clear()
            await flush_buf(batch, total)

        async with get_db() as db:
            await db.execute(
                "UPDATE single_jump_task SET status='done', finished_at=?, progress=total WHERE id=?",
                (_now(), task_id),
            )
            await db.commit()
        print(f"[{task_id}] Single-jump test completed successfully")

    except Exception as exc:
        print(f"[{task_id}] Single-jump test failed: {exc}")
        import traceback
        traceback.print_exc()
        async with get_db() as db:
            await db.execute(
                "UPDATE single_jump_task SET status='failed', error_message=? WHERE id=?",
                (str(exc), task_id),
            )
            await db.commit()


async def _build_chunk_map_from_db(sections: list) -> dict[str, str]:
    """从 qa_gen_question 表构建 question -> chunk_id 映射

    通过查询 section_path 和 question 匹配的记录，获取对应的 chunk_id。
    这样上传的 MD 文件也能做切片级别对比。
    """
    chunk_map: dict[str, str] = {}
    try:
        async with get_db() as db:
            # 收集所有 section_paths
            section_paths = [s.section_path for s in sections]
            if not section_paths:
                return chunk_map

            # 构建查询条件
            placeholders = ','.join(['?' for _ in section_paths])
            # 查询这些 section_path 对应的所有 question 的 chunk_id
            rows = await db.execute_fetchall(
                f"""SELECT DISTINCT section_path, question, chunk_id
                    FROM qa_gen_question
                    WHERE section_path IN ({placeholders})
                    AND status='approved'
                    AND chunk_id IS NOT NULL
                    AND chunk_id != ''""",
                section_paths
            )

            for row in rows:
                d = dict(row)
                question = d.get("question")
                chunk_id = d.get("chunk_id")
                if question and chunk_id:
                    chunk_map[question] = chunk_id

    except Exception as e:
        # 查询失败不中断主流程，只是没有切片映射
        print(f"[_build_chunk_map_from_db] Warning: failed to build chunk map: {e}")

    return chunk_map


async def _fetch_file_name_map(env_url: str, org_id: str, d_user_id: str) -> dict[str, str]:
    """Fetch knowledge file list and build file_id -> file_name map."""
    if not env_url or not org_id:
        return {}
    url = f"{env_url.rstrip('/')}/dagent/knowledge/file/page"
    headers = {
        "Content-Type": "application/json",
        "d-user-id": d_user_id or "test",
        "org-id": org_id,
    }
    page = 1
    page_size = 100
    file_name_map: dict[str, str] = {}
    try:
        async with aiohttp.ClientSession(headers=headers) as session:
            while True:
                payload = {"current": page, "page_size": page_size, "org_id": org_id}
                async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=20)) as resp:
                    resp.raise_for_status()
                    data = await resp.json()
                # Fix: handle case where data.get("data") returns None
                data_obj = data.get("data") or {}
                items = data_obj.get("list", []) if isinstance(data_obj, dict) else []
                if not items:
                    break
                for item in items:
                    fid = item.get("id")
                    fname = item.get("file_name")
                    if fid and fname:
                        file_name_map[fid] = fname
                if len(items) < page_size:
                    break
                page += 1
    except Exception:
        return {}
    return file_name_map


async def _fetch_agent_recall_docs(
    env_url: str,
    org_id: str,
    d_user_id: str,
    agent_id: str,
    question: str,
) -> list[dict]:
    """
    Fetch recall documents by calling knowledge search API directly.

    Note: We call the knowledge search API instead of agent chat because:
    1. Agent chat SSE stream may have buffering issues on remote servers
    2. For recall comparison, we only need the knowledge search results
    3. This is more reliable and faster than waiting for full agent execution
    """
    if not env_url or not org_id or not question:
        return []

    headers = {
        "Content-Type": "application/json",
        "d-user-id": d_user_id or "test",
        "org-id": org_id,
    }

    # Call knowledge search API directly
    url = f"{env_url.rstrip('/')}/dagent/knowledge/hub/semantic_search_knowledge/detail"
    payload = {
        "query": question,
        "org_id": org_id,
        "top_k": 20,
    }

    try:
        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                resp.raise_for_status()
                data = await resp.json()

                result_data = data.get("data", {})
                standard = result_data.get("standard_answer_results") or []
                rerank_top = result_data.get("related_knowledge_rerank_results_top") or []
                all_items = standard + rerank_top

                # Fetch file name mapping
                file_name_map = await _fetch_file_name_map(env_url, org_id, d_user_id)

                # Convert to our format
                items: list[dict] = []
                for item in all_items[:20]:
                    file_id = item.get("file_id") or item.get("knowledge_file_id") or ""
                    file_name = item.get("file_name") or file_name_map.get(file_id, "")
                    headers_text = item.get("headers") or ""
                    content = item.get("active_paragraph_context") or item.get("active_context") or ""

                    # Calculate similarity from cosine_distance_1
                    sim = None
                    if item.get("cosine_distance_1") is not None:
                        try:
                            sim = round(1.0 - float(item.get("cosine_distance_1")), 4)
                        except Exception:
                            pass

                    items.append({
                        "file_id": file_id,
                        "file_name": file_name,
                        "headers": headers_text,
                        "content": content,
                        "similarity": sim,
                    })

                return items

    except Exception as e:
        print(f"[DEBUG] Exception in _fetch_agent_recall_docs: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return []


def _extract_recall_items_from_events(events: list[dict]) -> list[dict]:
    """Best-effort extraction of recalled chunks/files from agent stream payload."""
    items: list[dict] = []
    seen: set[tuple[str, str]] = set()

    print(f"[DEBUG] _extract_recall_items_from_events: processing {len(events)} events")

    # First, try to extract from TOOL_END event's event_data (structured knowledge reference)
    for idx, event in enumerate(events):
        if event.get("message_type") == "EVENT":
            event_data_raw = event.get("data")
            # Parse JSON string if needed
            if isinstance(event_data_raw, str):
                try:
                    event_data = json.loads(event_data_raw)
                except json.JSONDecodeError:
                    continue
            else:
                event_data = event_data_raw

            if not isinstance(event_data, dict):
                continue

            event_name = event_data.get("event_name")
            print(f"[DEBUG] Event {idx}: event_name={event_name}")

            # Check if this is a TOOL_END event with knowledge reference data
            if event_name == "TOOL_END":
                tool_event_data = event_data.get("event_data")
                print(f"[DEBUG] TOOL_END event_data type: {type(tool_event_data)}, value: {tool_event_data}")

                if isinstance(tool_event_data, dict):
                    # Extract knowledge reference items
                    reference_items = tool_event_data.get("items", [])
                    print(f"[DEBUG] Found {len(reference_items)} reference items")

                    if isinstance(reference_items, list):
                        for item in reference_items:
                            if not isinstance(item, dict):
                                continue
                            file_id = str(item.get("file_id") or "")
                            headers = str(item.get("headers") or "")
                            paragraph_md5 = str(item.get("paragraph_md5") or "")
                            chunk_id = str(item.get("paragraph_chunk_id") or "")

                            print(f"[DEBUG] Processing item: file_id={file_id}, headers={headers[:50]}...")

                            if file_id:
                                key = (file_id, headers[:80])
                                if key not in seen:
                                    seen.add(key)
                                    items.append({
                                        "file_id": file_id,
                                        "file_name": "",  # Will be filled by frontend
                                        "headers": headers,
                                        "content": f"[知识库引用] {headers}",
                                        "similarity": None,
                                        "paragraph_md5": paragraph_md5,
                                        "chunk_id": chunk_id,
                                    })

    # If we found structured knowledge references, return them
    print(f"[DEBUG] Found {len(items)} items from TOOL_END events")
    if items:
        return items[:20]

    # Fallback: walk through all events to find file_id/content pairs
    def walk(obj: Any):
        if isinstance(obj, dict):
            maybe_file_id = str(
                obj.get("file_id")
                or obj.get("source_file_id")
                or obj.get("knowledge_file_id")
                or ""
            )
            maybe_file_name = str(
                obj.get("file_name")
                or obj.get("source_file_name")
                or obj.get("knowledge_file_name")
                or obj.get("doc_name")
                or obj.get("source_name")
                or ""
            )
            maybe_content = str(
                obj.get("active_paragraph_context")
                or obj.get("active_context")
                or obj.get("chunk_content")
                or obj.get("paragraph")
                or obj.get("content")
                or ""
            )
            if maybe_file_id or maybe_file_name:
                key = (maybe_file_id, maybe_content[:80])
                if key not in seen:
                    seen.add(key)
                    sim = None
                    if obj.get("cosine_distance_1") is not None:
                        try:
                            sim = round(1.0 - float(obj.get("cosine_distance_1")), 4)
                        except Exception:
                            sim = None
                    elif obj.get("similarity") is not None:
                        try:
                            sim = round(float(obj.get("similarity")), 4)
                        except Exception:
                            sim = None
                    elif obj.get("score") is not None:
                        try:
                            sim = round(float(obj.get("score")), 4)
                        except Exception:
                            sim = None
                    items.append({
                        "file_id": maybe_file_id,
                        "file_name": maybe_file_name,
                        "headers": obj.get("headers") or "",
                        "content": maybe_content,
                        "similarity": sim,
                    })
            for value in obj.values():
                walk(value)
        elif isinstance(obj, list):
            for value in obj:
                walk(value)

    for event in events:
        walk(event)
    return items[:20]


async def _iter_sse_json_events(stream: aiohttp.StreamReader):
    """Yield JSON objects from SSE stream, line-by-line."""
    buf = ""
    async for raw_chunk in stream:
        buf += raw_chunk.decode("utf-8", errors="ignore")
        while "\n" in buf:
            line, buf = buf.split("\n", 1)
            line = line.rstrip("\r")
            if not line.startswith("data:"):
                continue
            data_str = line[5:].lstrip()
            if not data_str or data_str == "[DONE]":
                continue
            try:
                payload = json.loads(data_str)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                yield payload


async def _fetch_agent_list(env_url: str, org_id: str, d_user_id: str) -> list[dict]:
    """Best-effort fetch of available agents from known dagent endpoints."""
    if not env_url or not org_id:
        return []
    base = env_url.rstrip("/")
    headers = {
        "Content-Type": "application/json",
        "d-user-id": d_user_id or "test",
        "org-id": org_id,
    }
    # Different deployments may expose different endpoints/shapes.
    candidates = [
        ("POST", f"{base}/dagent/agent/page", {"current": 1, "page_size": 100, "org_id": org_id}),
        ("POST", f"{base}/dagent/agent/list", {"org_id": org_id}),
        ("GET", f"{base}/dagent/agent/list?org_id={org_id}", None),
        ("GET", f"{base}/dagent/agent/page?current=1&page_size=100&org_id={org_id}", None),
    ]
    for method, url, payload in candidates:
        try:
            async with aiohttp.ClientSession(headers=headers) as session:
                if method == "POST":
                    async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=12)) as resp:
                        if resp.status >= 400:
                            continue
                        data = await resp.json()
                else:
                    async with session.get(url, timeout=aiohttp.ClientTimeout(total=12)) as resp:
                        if resp.status >= 400:
                            continue
                        data = await resp.json()
            agents = _normalize_agents(data)
            if agents:
                return agents
        except Exception:
            continue
    return []


def _normalize_agents(raw: Any) -> list[dict]:
    """Normalize heterogeneous agent-list payloads to [{id,name}]."""
    if not isinstance(raw, dict):
        return []
    data = raw.get("data", raw)
    items: list[Any] = []
    if isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        if isinstance(data.get("list"), list):
            items = data.get("list", [])
        elif isinstance(data.get("records"), list):
            items = data.get("records", [])
        elif isinstance(data.get("items"), list):
            items = data.get("items", [])
    out: list[dict] = []
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        aid = str(item.get("id") or item.get("agent_id") or item.get("hub_id") or "").strip()
        if not aid or aid in seen:
            continue
        seen.add(aid)
        name = (
            str(item.get("name") or item.get("agent_name") or item.get("title") or item.get("hub_name") or aid)
            .strip()
        )
        out.append({"id": aid, "name": name})
    return out


# ── 从 QA 生成任务创建单跳召回测试 ─────────────────────────────────────────────────


@router.post("/task/from-qa-gen")
async def create_task_from_qa_gen(
    name: str = Form(...),
    env_url: str = Form(...),
    org_id: str = Form(...),
    d_user_id: str = Form("test"),
    agent_id: str = Form(""),
    top_k: int = Form(64),
    recall_top_k: int = Form(64),
    concurrency: int = Form(20),
    cross_chunk: str = Form("true"),
    qa_gen_task_id: str = Form(...),
):
    """直接从 QA 生成任务创建单跳召回测试任务，无需下载上传 MD 文件

    Args:
        top_k: 用于判断切片/文件是否命中的阈值（默认64）
        recall_top_k: 调用召回API时请求的top_k数量（默认64）
        agent_id: 用于召回测试的 agent ID（可选，为空时直接调用知识库搜索）
    """
    cross_chunk_bool = cross_chunk.lower() in ("true", "1", "yes")

    # 1. 验证 QA 生成任务是否存在且有已通过的问题
    async with get_db() as db:
        task_rows = await db.execute_fetchall(
            "SELECT * FROM qa_gen_task WHERE id=?", (qa_gen_task_id,)
        )
        if not task_rows:
            raise HTTPException(status_code=404, detail="QA 生成任务不存在")

        qa_task = dict(task_rows[0])

        # 自动获取 agent_id（如果未提供）
        if not agent_id:
            agent_id = qa_task.get("agent_id", "")
            if agent_id:
                print(f"[from-qa-gen] 自动使用 QA 任务的 agent_id: {agent_id}")

        # 获取已通过的问题（包含 file_id、file_name 和 chunk_id）
        question_rows = await db.execute_fetchall(
            "SELECT section_path, question, reference_answer, file_id, file_name, chunk_id FROM qa_gen_question WHERE task_id=? AND status='approved' ORDER BY section_path, created_at",
            (qa_gen_task_id,)
        )

    if not question_rows:
        raise HTTPException(status_code=400, detail="没有已通过的问题")

    # 2. 构建 MD 格式内容，同时收集 file_id/file_name/chunk_id 映射
    from collections import defaultdict
    sections_dict = defaultdict(list)
    section_file_map = {}  # section_path -> {file_id, file_name}
    question_chunk_map = {}  # question -> chunk_id，用于切片级别验证

    for r in question_rows:
        d = dict(r)
        sections_dict[d["section_path"]].append(d)
        # 保存该 section 的 file_id 和 file_name（如果有）
        if d.get("file_id") and d["section_path"] not in section_file_map:
            section_file_map[d["section_path"]] = {
                "file_id": d["file_id"],
                "file_name": d["file_name"] or ""
            }
        # 保存 question 到 chunk_id 的映射
        if d.get("chunk_id") and d.get("question"):
            question_chunk_map[d["question"]] = d["chunk_id"]

    # 回退：对于旧任务（没有 file_id/file_name），从 Dagent 数据库反查
    missing_sections = [sp for sp in sections_dict if sp not in section_file_map]
    if missing_sections:
        try:
            from .qa_gen_dagent import get_dagent_conn
            import aiomysql
            conn = await get_dagent_conn()
            cursor = await conn.cursor(aiomysql.DictCursor)
            try:
                for sp in missing_sections:
                    # section_path 就是 Dagent 的 headers 字段
                    await cursor.execute(
                        "SELECT DISTINCT file_id, file_name FROM knowledge_md_header_split WHERE headers = %s AND org_id = %s AND delete_time IS NULL LIMIT 1",
                        (sp, org_id),
                    )
                    row = await cursor.fetchone()
                    if row:
                        section_file_map[sp] = {
                            "file_id": row["file_id"],
                            "file_name": row["file_name"] or ""
                        }
            finally:
                await cursor.close()
                conn.close()
        except Exception:
            pass  # 回退失败不影响主流程

    md_lines = []
    # 清理函数：确保文本完全匹配解析器正则表达式 [a-zA-Z0-9_/ .-]+
    import re

    def clean_for_parser(text: str) -> str:
        """清理文本以匹配解析器正则表达式，保留中文字符"""
        if not text:
            return "default"
        # 1. 将非允许字符替换为下划线（保留中文字符）
        cleaned = re.sub(r'[^一-龥a-zA-Z0-9_/ .\-]', '_', text)
        # 2. 去除首尾空格
        cleaned = cleaned.strip()
        # 3. 确保不以点号开头
        if cleaned.startswith('.'):
            cleaned = '_' + cleaned[1:]
        # 4. 如果为空，使用默认值
        return cleaned if cleaned else "default_section"

    # prebuilt_file_map: 使用 file_name 作为 key（解析器会解析出这个值）
    # 直接用 Dagent 的 file_name 作为 section 标识，避免中文路径被破坏
    prebuilt_file_map = {}

    section_index = 0
    for section_path, items in sections_dict.items():
        section_index += 1

        # 获取该 section 的 file_name（如果有）
        file_info = section_file_map.get(section_path)

        if file_info and file_info.get("file_name"):
            # 使用 Dagent 的 file_name 作为 section 标识
            # 例如：samples/sample_gdc.md
            file_name = file_info["file_name"]
            # 去掉扩展名作为 doc_name
            doc_name = file_name.rsplit(".", 1)[0] if "." in file_name else file_name

            # 解析器会解析出 "file_name / doc_name" 格式
            parsed_section_path = f"{file_name} / {doc_name}"

            # 构建映射
            prebuilt_file_map[parsed_section_path] = {
                "file_id": file_info["file_id"],
                "file_name": file_info["file_name"],
                "match_type": "exact_from_qa_gen",
            }

            # 章节标题使用文件名（更清晰）
            chapter_title = f"第{section_index}章 {doc_name.split('/')[-1]}"

            # MD 格式
            md_lines.append(f"# {chapter_title}")
            md_lines.append(f"## {file_name} / {doc_name}")
            md_lines.append(f"# {section_index}. {doc_name.split('/')[-1]}_Document")
        else:
            # 回退：没有 file_name 时，使用清理后的 section_path（旧逻辑）
            clean_section_path = clean_for_parser(section_path)
            raw_doc_name = section_path.split("/")[-1] if "/" in section_path else section_path
            clean_doc_name = clean_for_parser(raw_doc_name)
            parsed_section_path = f"{clean_section_path} / {clean_doc_name}"

            chapter_title = f"第{section_index}章 {clean_doc_name}"

            md_lines.append(f"# {chapter_title}")
            md_lines.append(f"## {parsed_section_path}")
            md_lines.append(f"# {section_index}. {clean_doc_name}_Document")


        # 描述行
        md_lines.append("> Generated from QA generation task")

        # 分隔符
        md_lines.append("---")
        md_lines.append("")

        for i, item in enumerate(items, 1):
            qid = f"Q{i}"
            aid = f"A{i}"
            md_lines.append(f"## {qid}: {item['question']}")
            md_lines.append(f"**{aid}:** {item['reference_answer']}")
            md_lines.append("")

        md_lines.append("---")
        md_lines.append("")

    md_content = "\n".join(md_lines)

    # 3. 创建单跳召回测试任务
    task_id = _id()
    async with get_db() as db:
        await db.execute(
            """INSERT INTO single_jump_task
               (id,name,env_url,org_id,d_user_id,agent_id,top_k,recall_top_k,concurrency,cross_chunk,status,created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (task_id, name, env_url, org_id,
             d_user_id, agent_id, top_k, recall_top_k, concurrency, int(cross_chunk_bool),
             "pending", _now()),
        )
        await db.commit()

    # 4. 后台运行（传递预构建的文件映射和切片映射）
    asyncio.create_task(_run_task(
        task_id, md_content, env_url, org_id,
        d_user_id, agent_id, top_k, recall_top_k, concurrency, cross_chunk_bool,
        prebuilt_file_map=prebuilt_file_map if prebuilt_file_map else None,
        prebuilt_chunk_map=question_chunk_map if question_chunk_map else None,
    ))

    return {"status": 0, "data": {"id": task_id}}
