"""
多跳召回测试 API
"""
import asyncio
import json
import sys
from pathlib import Path
from fastapi import APIRouter, HTTPException, UploadFile, File, Form

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "sdk"))
sys.path.insert(0, str(Path(__file__).parent.parent))

from models.db import get_db, _now, _id

router = APIRouter(prefix="/api/multi-hop", tags=["多跳召回测试"])


@router.get("/dagent/agents")
async def list_dagent_agents(env_url: str, org_id: str, d_user_id: str = "test"):
    """从 dagent 平台拉取可用的 Agent 列表"""
    import aiohttp
    url = f"{env_url.rstrip('/')}/dagent/agent/page"
    headers = {
        "Content-Type": "application/json",
        "d-user-id": d_user_id,
        "org-id": org_id,
    }
    payload = {"current": 1, "page_size": 100, "org_id": org_id}
    try:
        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                resp.raise_for_status()
                data = await resp.json()
        agents = data.get("data", {}).get("list", [])
        return {"status": 0, "data": [
            {"id": a.get("id"), "name": a.get("agent_name"), "type": a.get("agent_type"), "description": a.get("agent_description")}
            for a in agents
        ]}
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"无法连接 dagent: {e}")


@router.post("/task")
async def create_task(
    file: UploadFile = File(...),
    name: str = Form(""),
    env_url: str = Form(...),
    org_id: str = Form(...),
    d_user_id: str = Form("test"),
    agent_id: str = Form(...),
    llm_type: str = Form("deepseek_v3"),
    top_k: int = Form(10),
    concurrency: int = Form(5),
):
    content = await file.read()
    qa_text = content.decode("utf-8")

    task_id = _id()
    async with get_db() as db:
        await db.execute(
            """INSERT INTO multi_hop_task
               (id,name,env_url,org_id,d_user_id,agent_id,llm_type,top_k,concurrency,status,created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (task_id, name or file.filename, env_url, org_id,
             d_user_id, agent_id, llm_type, top_k, concurrency, "pending", _now()),
        )
        await db.commit()

    asyncio.create_task(_run_task(
        task_id, qa_text, env_url, org_id, d_user_id, agent_id, llm_type, top_k, concurrency
    ))
    return {"status": 0, "data": {"id": task_id}}


@router.get("/task/list")
async def list_tasks():
    async with get_db() as db:
        rows = await db.execute_fetchall(
            "SELECT * FROM multi_hop_task ORDER BY created_at DESC"
        )
        return {"status": 0, "data": [dict(r) for r in rows]}


@router.get("/task/{task_id}")
async def get_task(task_id: str):
    async with get_db() as db:
        rows = await db.execute_fetchall(
            "SELECT * FROM multi_hop_task WHERE id=?", (task_id,)
        )
        if not rows:
            raise HTTPException(status_code=404, detail="Task not found")
        return {"status": 0, "data": dict(rows[0])}


@router.delete("/task/{task_id}")
async def delete_task(task_id: str):
    async with get_db() as db:
        await db.execute("DELETE FROM multi_hop_result WHERE task_id=?", (task_id,))
        await db.execute("DELETE FROM multi_hop_task WHERE id=?", (task_id,))
        await db.commit()
    return {"status": 0}


@router.get("/task/{task_id}/results")
async def get_results(task_id: str):
    async with get_db() as db:
        rows = await db.execute_fetchall(
            "SELECT * FROM multi_hop_result WHERE task_id=? ORDER BY qid",
            (task_id,),
        )
        results = []
        for r in rows:
            d = dict(r)
            d["hops"] = json.loads(d.get("hops") or "[]")
            d["actual_hops"] = json.loads(d.get("actual_hops") or "[]")
            d["retrieved"] = json.loads(d.get("retrieved") or "[]")
            results.append(d)
        return {"status": 0, "data": results}


@router.get("/task/{task_id}/summary")
async def get_summary(task_id: str):
    async with get_db() as db:
        task_rows = await db.execute_fetchall(
            "SELECT * FROM multi_hop_task WHERE id=?", (task_id,)
        )
        if not task_rows:
            raise HTTPException(status_code=404)
        task = dict(task_rows[0])

        rows = await db.execute_fetchall(
            """SELECT
                COUNT(*) as total,
                SUM(CASE WHEN error IS NOT NULL THEN 1 ELSE 0 END) as errors,
                SUM(full_hit) as full_hit_count,
                SUM(partial_hit) as partial_hit_count,
                SUM(full_chunk_hit) as full_chunk_hit_count,
                SUM(partial_chunk_hit) as partial_chunk_hit_count,
                AVG(CASE WHEN hop_count > 0 THEN CAST(hop_hit_count AS REAL) / hop_count ELSE 0 END) as avg_hop_hit_rate,
                AVG(CASE WHEN hop_count > 0 THEN CAST(chunk_hit_count AS REAL) / hop_count ELSE 0 END) as avg_chunk_hit_rate,
                AVG(latency_ms) as avg_latency_ms
               FROM multi_hop_result WHERE task_id=?""",
            (task_id,),
        )
        stats = dict(rows[0]) if rows else {}

        total = stats.get("total") or 0
        full_hit = stats.get("full_hit_count") or 0
        partial_hit = stats.get("partial_hit_count") or 0
        full_chunk_hit = stats.get("full_chunk_hit_count") or 0
        partial_chunk_hit = stats.get("partial_chunk_hit_count") or 0

        return {
            "status": 0,
            "data": {
                "task": task,
                "total": total,
                "full_hit_count": full_hit,
                "full_hit_rate": round(full_hit / total, 4) if total else 0.0,
                "partial_hit_count": partial_hit,
                "partial_hit_rate": round(partial_hit / total, 4) if total else 0.0,
                "full_chunk_hit_count": full_chunk_hit,
                "full_chunk_hit_rate": round(full_chunk_hit / total, 4) if total else 0.0,
                "partial_chunk_hit_count": partial_chunk_hit,
                "partial_chunk_hit_rate": round(partial_chunk_hit / total, 4) if total else 0.0,
                "error_count": stats.get("errors") or 0,
                "avg_hop_hit_rate": round(stats.get("avg_hop_hit_rate") or 0.0, 4),
                "avg_chunk_hit_rate": round(stats.get("avg_chunk_hit_rate") or 0.0, 4),
                "avg_latency_ms": round(stats.get("avg_latency_ms") or 0.0, 1),
            }
        }


# ── 后台执行 ───────────────────────────────────────────────────────────────────

async def _run_task(task_id: str, qa_text: str, env_url: str, org_id: str,
                    d_user_id: str, agent_id: str, llm_type: str,
                    top_k: int, concurrency: int):
    try:
        from rag_eval.multi_hop.parser import parse_multi_hop_text
        from rag_eval.multi_hop.tester import MultiHopTester
        from rag_eval.single_jump.mapper import FileMapper

        case = parse_multi_hop_text(qa_text)
        qa_pairs = case.qa_pairs
        if not qa_pairs:
            raise ValueError("未解析到任何多跳问答对")

        total = len(qa_pairs)
        async with get_db() as db:
            await db.execute(
                "UPDATE multi_hop_task SET status='running', total=? WHERE id=?",
                (total, task_id),
            )
            await db.commit()

        mapper = FileMapper(env_url, org_id, d_user_id)
        await mapper.load_files()
        all_paths = {hop.section_path for qa in qa_pairs for hop in qa.hops}
        file_map = {path: mapper.map_section_to_file(path) for path in all_paths}

        tester = MultiHopTester(
            env_url, org_id, d_user_id,
            agent_id=agent_id, llm_type=llm_type or "deepseek_v3",
        )

        write_buf = []
        FLUSH_SIZE = 20

        async def flush_buf(buf: list, progress: int):
            async with get_db() as db2:
                for r in buf:
                    await db2.execute(
                        """INSERT INTO multi_hop_result
                           (id,task_id,qid,question,answer,type,top_k,
                            hops,actual_hops,retrieved,agent_answer,
                            latency_ms,error,best_cosine_sim,
                            full_hit,partial_hit,hop_count,hop_hit_count,
                            chunk_hit_count,full_chunk_hit,partial_chunk_hit)
                           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (
                            _id(), task_id, r.qid, r.question, r.answer, r.type, r.top_k,
                            json.dumps([{
                                "section_path": h.section_path,
                                "file_id": h.file_id,
                                "file_name": h.file_name,
                                "hit": h.hit,
                                "hit_at_hop": h.hit_at_hop,
                                "contribution": h.contribution,
                                "expected_chunk_id": h.expected_chunk_id,
                                "chunk_hit": h.chunk_hit,
                                "chunk_hit_at_hop": h.chunk_hit_at_hop,
                            } for h in r.hop_results], ensure_ascii=False),
                            json.dumps([{
                                "hop_index": ah.hop_index,
                                "query": ah.query,
                                "retrieved": ah.retrieved,
                            } for ah in r.actual_hops], ensure_ascii=False),
                            json.dumps(r.retrieved, ensure_ascii=False),
                            r.agent_answer or "",
                            r.latency_ms, r.error, r.best_cosine_sim,
                            int(r.full_hit), int(r.partial_hit),
                            r.hop_count, r.hop_hit_count,
                            r.chunk_hit_count,
                            int(r.full_chunk_hit), int(r.partial_chunk_hit),
                        ),
                    )
                await db2.execute(
                    "UPDATE multi_hop_task SET progress=? WHERE id=?", (progress, task_id)
                )
                await db2.commit()

        async def on_result(r, done, _total):
            write_buf.append(r)
            if len(write_buf) >= FLUSH_SIZE or done == _total:
                buf = write_buf[:]
                write_buf.clear()
                await flush_buf(buf, done)

        await tester.run(
            qa_pairs, file_map,
            top_k=top_k, concurrency=concurrency,
            result_cb=on_result,
        )

        if write_buf:
            await flush_buf(write_buf, total)

        async with get_db() as db:
            await db.execute(
                "UPDATE multi_hop_task SET status='done', finished_at=? WHERE id=?",
                (_now(), task_id),
            )
            await db.commit()

    except Exception as exc:
        async with get_db() as db:
            await db.execute(
                "UPDATE multi_hop_task SET status='failed', error_message=? WHERE id=?",
                (str(exc), task_id),
            )
            await db.commit()
