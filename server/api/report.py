import json
import sys
from pathlib import Path
from fastapi import APIRouter, HTTPException

# Add parent directory to sys.path for relative imports
sys.path.insert(0, str(Path(__file__).parent.parent))
from models.db import get_db

router = APIRouter(prefix="/api/report", tags=["评测报告"])


@router.get("/{task_id}")
async def get_report(task_id: str):
    async with get_db() as db:
        rows = await db.execute_fetchall(
            "SELECT * FROM eval_report WHERE task_id=?", (task_id,)
        )
        if not rows:
            raise HTTPException(status_code=404, detail="Report not found. Task may still be running.")
        return {"status": 0, "data": dict(rows[0])}


@router.get("/{task_id}/items")
async def get_report_items(task_id: str):
    async with get_db() as db:
        rows = await db.execute_fetchall(
            "SELECT * FROM eval_result WHERE task_id=? ORDER BY rowid ASC", (task_id,)
        )
        items = []
        for r in rows:
            d = dict(r)
            d["retrieved_chunks"] = json.loads(d["retrieved_chunks"] or "[]")
            d["judge_detail"] = json.loads(d["judge_detail"] or "{}")
            items.append(d)
        return {"status": 0, "data": {"total": len(items), "records": items}}
