import json
import sys
from pathlib import Path
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

# Add parent directory to sys.path for relative imports
sys.path.insert(0, str(Path(__file__).parent.parent))
from models.db import get_db, _now, _id

router = APIRouter(prefix="/api/config", tags=["配置管理"])


# ── Platform Config ───────────────────────────────────────────────────────────

class PlatformConfigReq(BaseModel):
    name: str
    type: str = "dagent"
    base_url: str
    org_id: Optional[str] = None
    token: Optional[str] = None


@router.post("/platform")
async def create_platform_config(req: PlatformConfigReq):
    async with get_db() as db:
        row_id = _id()
        await db.execute(
            "INSERT INTO platform_config (id,name,type,base_url,org_id,token,created_at) VALUES (?,?,?,?,?,?,?)",
            (row_id, req.name, req.type, req.base_url, req.org_id, req.token, _now()),
        )
        await db.commit()
    return {"status": 0, "data": {"id": row_id}}


@router.get("/platform")
async def list_platform_configs():
    async with get_db() as db:
        rows = await db.execute_fetchall("SELECT * FROM platform_config ORDER BY created_at DESC")
        return {"status": 0, "data": [dict(r) for r in rows]}


@router.delete("/platform/{config_id}")
async def delete_platform_config(config_id: str):
    async with get_db() as db:
        await db.execute("DELETE FROM platform_config WHERE id=?", (config_id,))
        await db.commit()
    return {"status": 0, "data": True}


# ── Judge Config ──────────────────────────────────────────────────────────────

class JudgeConfigReq(BaseModel):
    name: str
    base_url: str
    api_key: str
    model: str
    embed_base_url: Optional[str] = ""
    embed_api_key: Optional[str] = ""
    embed_model: Optional[str] = "text-embedding-3-small"


@router.post("/judge")
async def create_judge_config(req: JudgeConfigReq):
    async with get_db() as db:
        row_id = _id()
        await db.execute(
            "INSERT INTO judge_config (id,name,base_url,api_key,model,embed_base_url,embed_api_key,embed_model,created_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (row_id, req.name, req.base_url, req.api_key, req.model, req.embed_base_url, req.embed_api_key, req.embed_model, _now()),
        )
        await db.commit()
    return {"status": 0, "data": {"id": row_id}}


@router.get("/judge")
async def list_judge_configs():
    async with get_db() as db:
        rows = await db.execute_fetchall("SELECT id,name,base_url,model,embed_base_url,embed_model,created_at FROM judge_config ORDER BY created_at DESC")
        return {"status": 0, "data": [dict(r) for r in rows]}


@router.delete("/judge/{config_id}")
async def delete_judge_config(config_id: str):
    async with get_db() as db:
        await db.execute("DELETE FROM judge_config WHERE id=?", (config_id,))
        await db.commit()
    return {"status": 0, "data": True}
