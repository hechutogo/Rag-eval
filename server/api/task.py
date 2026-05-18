import asyncio
import json
import sys
from pathlib import Path
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

# Add parent directory to sys.path for relative imports
sys.path.insert(0, str(Path(__file__).parent.parent))
from models.db import get_db, _now, _id

router = APIRouter(prefix="/api/task", tags=["评测任务"])


class RunTaskReq(BaseModel):
    name: Optional[str] = None
    dataset_id: str
    platform_config_id: str
    judge_config_id: str
    agent_id: str
    knowledge_hub_id: str
    file_id_list: list[str] = []
    top_k: int = 10
    eval_retrieval: bool = True
    eval_generation: bool = True
    selected_metrics: list[str] = []
    concurrency: int = 3


def _task_dict(r) -> dict:
    d = dict(r)
    d["file_id_list"] = json.loads(r["file_id_list"] or "[]")
    d["selected_metrics"] = json.loads(r["selected_metrics"] or "[]")
    return d


@router.post("/run")
async def run_task(req: RunTaskReq):
    async with get_db() as db:
        task_id = _id()
        await db.execute(
            """INSERT INTO eval_task
               (id,name,dataset_id,platform_config_id,judge_config_id,agent_id,
                knowledge_hub_id,file_id_list,top_k,eval_retrieval,eval_generation,
                selected_metrics,concurrency,status,progress,total,created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,'pending',0,0,?)""",
            (task_id, req.name, req.dataset_id, req.platform_config_id,
             req.judge_config_id, req.agent_id, req.knowledge_hub_id,
             json.dumps(req.file_id_list), req.top_k,
             int(req.eval_retrieval), int(req.eval_generation),
             json.dumps(req.selected_metrics),
             req.concurrency, _now()),
        )
        await db.commit()

    import importlib
    task_svc = importlib.import_module("service.task_service")
    asyncio.create_task(task_svc.run_eval_task(task_id))
    return {"status": 0, "data": {"id": task_id}}


@router.get("/list")
async def list_tasks():
    async with get_db() as db:
        rows = await db.execute_fetchall(
            "SELECT * FROM eval_task ORDER BY created_at DESC"
        )
        return {"status": 0, "data": [_task_dict(r) for r in rows]}


@router.get("/{task_id}")
async def get_task(task_id: str):
    async with get_db() as db:
        rows = await db.execute_fetchall(
            "SELECT * FROM eval_task WHERE id=?", (task_id,)
        )
        if not rows:
            raise HTTPException(status_code=404, detail="Task not found")
        return {"status": 0, "data": _task_dict(rows[0])}


@router.delete("/{task_id}")
async def delete_task(task_id: str):
    async with get_db() as db:
        await db.execute("DELETE FROM eval_result WHERE task_id=?", (task_id,))
        await db.execute("DELETE FROM eval_report WHERE task_id=?", (task_id,))
        await db.execute("DELETE FROM eval_task WHERE id=?", (task_id,))
        await db.commit()
    return {"status": 0, "data": True}
