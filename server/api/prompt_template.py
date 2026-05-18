"""
提示词模板管理 API
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

from models.db import get_db, _now, _id

router = APIRouter(prefix="/api/prompt-template", tags=["提示词模板"])

DEFAULT_CONTENT = """1. 每个问题必须真正跨越多个章节，单独看任何一个章节都无法完整回答
2. 问题类型可以是：comparison（比较型）、reasoning（推理型）、aggregation（聚合型）
3. 答案要综合所有章节的信息，准确完整
4. 每个 hop 说明该章节对回答问题的具体贡献
5. quality_score 为你对该问题质量的评估（0-1）"""


@router.get("/default")
async def get_default():
    """返回内置默认提示词内容"""
    return {"status": 0, "data": {"content": DEFAULT_CONTENT}}


@router.get("/list")
async def list_templates():
    async with get_db() as db:
        rows = await db.execute_fetchall(
            "SELECT * FROM prompt_template ORDER BY created_at DESC"
        )
        return {"status": 0, "data": [dict(r) for r in rows]}


class TemplateReq(BaseModel):
    name: str
    description: Optional[str] = None
    content: str


@router.post("")
async def create_template(req: TemplateReq):
    if not req.content.strip():
        raise HTTPException(status_code=400, detail="content 不能为空")
    row_id = _id()
    now = _now()
    async with get_db() as db:
        await db.execute(
            "INSERT INTO prompt_template (id,name,description,content,created_at,updated_at) VALUES (?,?,?,?,?,?)",
            (row_id, req.name, req.description, req.content, now, now),
        )
        await db.commit()
    return {"status": 0, "data": {"id": row_id}}


@router.put("/{template_id}")
async def update_template(template_id: str, req: TemplateReq):
    if not req.content.strip():
        raise HTTPException(status_code=400, detail="content 不能为空")
    async with get_db() as db:
        rows = await db.execute_fetchall(
            "SELECT id FROM prompt_template WHERE id=?", (template_id,)
        )
        if not rows:
            raise HTTPException(status_code=404, detail="模板不存在")
        await db.execute(
            "UPDATE prompt_template SET name=?,description=?,content=?,updated_at=? WHERE id=?",
            (req.name, req.description, req.content, _now(), template_id),
        )
        await db.commit()
    return {"status": 0, "data": True}


@router.delete("/{template_id}")
async def delete_template(template_id: str):
    async with get_db() as db:
        await db.execute("DELETE FROM prompt_template WHERE id=?", (template_id,))
        await db.commit()
    return {"status": 0, "data": True}
