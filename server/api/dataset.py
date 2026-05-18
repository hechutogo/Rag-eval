import json
import sys
from pathlib import Path
from fastapi import APIRouter, HTTPException, UploadFile, File
from pydantic import BaseModel
from typing import Optional

# Add parent directory to sys.path for relative imports
sys.path.insert(0, str(Path(__file__).parent.parent))
from models.db import get_db, _now, _id

router = APIRouter(prefix="/api/dataset", tags=["测试集管理"])


class CreateDatasetReq(BaseModel):
    name: str
    description: Optional[str] = ""


class AddSampleReq(BaseModel):
    dataset_id: str
    question: str
    reference_answer: str
    relevant_chunk_ids: list[str] = []
    knowledge_hub_id: str
    source_file_id: Optional[str] = None
    metadata: dict = {}


class GenerateReq(BaseModel):
    dataset_id: str
    platform_config_id: str
    judge_config_id: str
    knowledge_hub_id: str
    file_id_list: list[str]
    chunk_ids: list[str] = []
    questions_per_chunk: int = 2
    max_chunks: int = 50


@router.post("/create")
async def create_dataset(req: CreateDatasetReq):
    async with get_db() as db:
        row_id = _id()
        await db.execute(
            "INSERT INTO eval_dataset (id,name,description,sample_count,created_at) VALUES (?,?,?,0,?)",
            (row_id, req.name, req.description, _now()),
        )
        await db.commit()
    return {"status": 0, "data": {"id": row_id}}


@router.get("/list")
async def list_datasets():
    async with get_db() as db:
        rows = await db.execute_fetchall(
            "SELECT * FROM eval_dataset ORDER BY created_at DESC"
        )
        return {"status": 0, "data": [dict(r) for r in rows]}


# ── Fixed-path routes MUST come before /{dataset_id} ────────────────────────

@router.get("/chunks-preview")
async def chunks_preview(platform_config_id: str, knowledge_hub_id: str):
    """Proxy: fetch chunks from the RAG platform for preview/selection"""
    import aiohttp
    async with get_db() as db:
        rows = await db.execute_fetchall(
            "SELECT * FROM platform_config WHERE id=?", (platform_config_id,)
        )
    if not rows:
        raise HTTPException(status_code=404, detail="Platform config not found")
    cfg = dict(rows[0])
    base_url = cfg["base_url"].rstrip("/")
    org_id = cfg.get("org_id", "")

    # Build headers with org-id for dagent API
    headers = {
        "Content-Type": "application/json",
        "org-id": org_id,
        "d-user-id": "test",
    }

    all_chunks = []

    # Use dagent file/page endpoint to get all files, then fetch chunks for each
    try:
        async with aiohttp.ClientSession(headers=headers) as session:
            page = 1
            page_size = 100
            while True:
                async with session.post(
                    f"{base_url}/dagent/knowledge/file/page",
                    json={"current": page, "page_size": page_size, "org_id": org_id},
                    timeout=aiohttp.ClientTimeout(total=15),
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        files = data.get("data", {}).get("list", [])
                        if not files:
                            break
                        # Fetch chunks for each file
                        for f in files:
                            try:
                                async with session.post(
                                    f"{base_url}/dagent/knowledge/chunk/page",
                                    json={"file_id": f["id"], "org_id": org_id, "page_size": 200},
                                    timeout=aiohttp.ClientTimeout(total=15),
                                ) as cr:
                                    if cr.status == 200:
                                        cd = await cr.json()
                                        for c in cd.get("data", {}).get("list", []):
                                            c["file_id"] = c.get("file_id", f["id"])
                                            c["file_name"] = f.get("file_name", "")
                                            c["content"] = c.get("paragraph_context") or c.get("content", "")
                                            all_chunks.append(c)
                            except Exception:
                                continue
                        if len(files) < page_size:
                            break
                        page += 1
                    else:
                        break
        if all_chunks:
            return {"status": 0, "data": all_chunks}
    except Exception as e:
        print(f"[chunks_preview] Error: {e}")

    return {"status": 0, "data": []}


@router.post("/generate")
async def generate_dataset(req: GenerateReq):
    """Trigger async LLM generation — returns gen_task_id for progress tracking"""
    import asyncio
    from ..service.task_service import run_generate_task

    gen_task_id = _id()
    async with get_db() as db:
        await db.execute(
            "INSERT INTO generate_task (id,dataset_id,status,created_at) VALUES (?,?,'pending',?)",
            (gen_task_id, req.dataset_id, _now()),
        )
        await db.commit()

    params = req.dict()
    params["gen_task_id"] = gen_task_id
    asyncio.create_task(run_generate_task(params))
    return {"status": 0, "data": {"gen_task_id": gen_task_id}}


@router.get("/generate/{gen_task_id}")
async def get_generate_progress(gen_task_id: str):
    """Poll generation task progress"""
    async with get_db() as db:
        rows = await db.execute_fetchall(
            "SELECT * FROM generate_task WHERE id=?", (gen_task_id,)
        )
        if not rows:
            raise HTTPException(status_code=404, detail="Generate task not found")
        return {"status": 0, "data": dict(rows[0])}


@router.get("/generate-tasks/{dataset_id}")
async def list_generate_tasks(dataset_id: str):
    """List all generate tasks for a dataset"""
    async with get_db() as db:
        rows = await db.execute_fetchall(
            "SELECT * FROM generate_task WHERE dataset_id=? ORDER BY created_at DESC",
            (dataset_id,),
        )
        return {"status": 0, "data": [dict(r) for r in rows]}


@router.post("/sample/add")
async def add_sample(req: AddSampleReq):
    async with get_db() as db:
        row_id = _id()
        await db.execute(
            """INSERT INTO eval_sample
               (id,dataset_id,question,reference_answer,relevant_chunk_ids,knowledge_hub_id,source_file_id,metadata)
               VALUES (?,?,?,?,?,?,?,?)""",
            (row_id, req.dataset_id, req.question, req.reference_answer,
             json.dumps(req.relevant_chunk_ids, ensure_ascii=False),
             req.knowledge_hub_id, req.source_file_id,
             json.dumps(req.metadata, ensure_ascii=False)),
        )
        await db.execute(
            "UPDATE eval_dataset SET sample_count=sample_count+1 WHERE id=?",
            (req.dataset_id,),
        )
        await db.commit()
    return {"status": 0, "data": {"id": row_id}}


@router.post("/import")
async def import_dataset(file: UploadFile = File(...)):
    """Upload a JSON file exported by the SDK (EvalDataset.to_dict())"""
    content = await file.read()
    data = json.loads(content)

    async with get_db() as db:
        ds_id = data.get("id") or _id()
        await db.execute(
            "INSERT OR REPLACE INTO eval_dataset (id,name,description,sample_count,created_at) VALUES (?,?,?,?,?)",
            (ds_id, data["name"], data.get("description", ""), len(data.get("samples", [])), _now()),
        )
        for s in data.get("samples", []):
            await db.execute(
                """INSERT OR REPLACE INTO eval_sample
                   (id,dataset_id,question,reference_answer,relevant_chunk_ids,knowledge_hub_id,source_file_id,metadata)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (s.get("id") or _id(), ds_id, s["question"], s.get("reference_answer", ""),
                 json.dumps(s.get("relevant_chunk_ids", []), ensure_ascii=False),
                 s.get("knowledge_hub_id", ""), s.get("source_file_id"),
                 json.dumps(s.get("metadata", {}), ensure_ascii=False)),
            )
        await db.commit()
    return {"status": 0, "data": {"id": ds_id, "imported": len(data.get("samples", []))}}


# ── Dynamic path routes MUST come last ──────────────────────────────────────

@router.get("/{dataset_id}")
async def get_dataset(dataset_id: str):
    async with get_db() as db:
        rows = await db.execute_fetchall(
            "SELECT * FROM eval_sample WHERE dataset_id=?", (dataset_id,)
        )
        ds = await db.execute_fetchall(
            "SELECT * FROM eval_dataset WHERE id=?", (dataset_id,)
        )
        if not ds:
            raise HTTPException(status_code=404, detail="Dataset not found")
        samples = [
            {**dict(r), "relevant_chunk_ids": json.loads(r["relevant_chunk_ids"]),
             "metadata": json.loads(r["metadata"])}
            for r in rows
        ]
        return {"status": 0, "data": {**dict(ds[0]), "samples": samples}}


@router.delete("/{dataset_id}")
async def delete_dataset(dataset_id: str):
    async with get_db() as db:
        await db.execute("DELETE FROM eval_sample WHERE dataset_id=?", (dataset_id,))
        await db.execute("DELETE FROM eval_dataset WHERE id=?", (dataset_id,))
        await db.commit()
    return {"status": 0, "data": True}
