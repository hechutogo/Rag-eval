"""
多跳问答生成 API

支持两种数据源：
1. 上传知识库 MD 文件（与 qa_gen 相同格式）
2. 从 Dagent 远程数据库拉取段落，按文件分组生成跨文件多跳问答对
"""
import asyncio
import json
import re
import sys
from pathlib import Path
from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).parent.parent))
from models.db import get_db, _now, _id
from api.qa_gen_dagent import get_dagent_conn, _fetch_paragraphs

router = APIRouter(prefix="/api/multi-hop-gen", tags=["多跳问答生成"])


# ── 任务 CRUD ─────────────────────────────────────────────────────────────────

@router.post("/task")
async def create_task(
    file: UploadFile = File(...),
    name: str = Form(""),
    judge_config_id: str = Form(...),
    hops_per_question: int = Form(2),
    questions_per_group: int = Form(3),
    quality_threshold: float = Form(0.6),
    prompt_template_id: str = Form(""),
):
    content = await file.read()
    md_text = content.decode("utf-8")

    task_id = _id()
    async with get_db() as db:
        await db.execute(
            """INSERT INTO multi_hop_gen_task
               (id,name,source,judge_config_id,hops_per_question,questions_per_group,
                quality_threshold,prompt_template_id,status,created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (task_id, name or file.filename, "file", judge_config_id,
             hops_per_question, questions_per_group, quality_threshold,
             prompt_template_id or None, "pending", _now()),
        )
        await db.commit()

    asyncio.create_task(_run_task(task_id, md_text))
    return {"status": 0, "data": {"id": task_id}}


# ── Dagent 数据源接口 ──────────────────────────────────────────────────────────

@router.get("/dagent/stats")
async def get_dagent_stats(org_id: str, env_url: str = ""):
    """获取 Dagent 知识库统计信息（通过 HTTP API）"""
    import aiohttp

    base_url = (env_url or "https://dagent.d-robotics.cc").rstrip("/")

    headers = {
        "Content-Type": "application/json",
        "org-id": org_id,
        "d-user-id": "test",
    }

    try:
        async with aiohttp.ClientSession(headers=headers) as session:
            page = 1
            page_size = 100
            total_files = 0
            total_paragraphs = 0

            while True:
                async with session.post(
                    f"{base_url}/dagent/knowledge/file/page",
                    json={"current": page, "page_size": page_size, "org_id": org_id},
                    timeout=aiohttp.ClientTimeout(total=15),
                ) as resp:
                    if resp.status != 200:
                        break
                    data = await resp.json()
                    files = data.get("data", {}).get("list", [])
                    if not files:
                        break

                    total_files += len(files)

                    for f in files:
                        try:
                            async with session.post(
                                f"{base_url}/dagent/knowledge/chunk/page",
                                json={"file_id": f["id"], "org_id": org_id, "page": 1, "page_size": 1},
                                timeout=aiohttp.ClientTimeout(total=10),
                            ) as cr:
                                if cr.status == 200:
                                    cd = await cr.json()
                                    total_paragraphs += cd.get("data", {}).get("total", 0)
                        except Exception:
                            pass

                    if len(files) < page_size:
                        break
                    page += 1

            return {"status": 0, "data": {
                "file_count": total_files,
                "paragraph_count": total_paragraphs,
                "total_images": 0,
                "paragraphs_with_pic_text": 0,
            }}
    except Exception as e:
        print(f"[get_dagent_stats] Error: {e}")
        return {"status": 0, "data": {}}


@router.get("/dagent/files")
async def list_dagent_files(org_id: str, env_url: str = ""):
    """列出 Dagent 中某组织下已处理完成的文件（通过 HTTP API）"""
    import aiohttp

    base_url = (env_url or "https://dagent.d-robotics.cc").rstrip("/")

    headers = {
        "Content-Type": "application/json",
        "org-id": org_id,
        "d-user-id": "test",
    }

    all_files = []

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
                    if resp.status != 200:
                        break
                    data = await resp.json()
                    files = data.get("data", {}).get("list", [])
                    if not files:
                        break

                    for f in files:
                        all_files.append({
                            "id": f.get("id"),
                            "file_name": f.get("file_name"),
                            "file_type": f.get("file_type"),
                            "file_clean_status": f.get("file_clean_status", "").lower(),
                            "file_bytes": f.get("file_bytes", 0),
                            "create_time": f.get("create_time"),
                        })

                    if len(files) < page_size:
                        break
                    page += 1

        return {"status": 0, "data": all_files}
    except Exception as e:
        print(f"[list_dagent_files] Error: {e}")
        return {"status": 0, "data": []}


@router.post("/task/from-dagent")
async def create_task_from_dagent(
    org_id: str = Form(...),
    env_url: str = Form(""),
    name: str = Form(""),
    judge_config_id: str = Form(...),
    file_ids: str = Form(""),
    hops_per_question: int = Form(2),
    questions_per_group: int = Form(3),
    quality_threshold: float = Form(0.6),
    prompt_template_id: str = Form(""),
):
    """从 Dagent 知识库创建多跳问答生成任务"""
    task_id = _id()
    file_id_list = [f.strip() for f in file_ids.split(",") if f.strip()]

    async with get_db() as db:
        await db.execute(
            """INSERT INTO multi_hop_gen_task
               (id,name,source,judge_config_id,org_id,file_ids,
                hops_per_question,questions_per_group,quality_threshold,
                prompt_template_id,status,created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (task_id, name or f"Dagent多跳({org_id[:8]}...)", "dagent",
             judge_config_id, org_id, file_ids,
             hops_per_question, questions_per_group, quality_threshold,
             prompt_template_id or None, "pending", _now()),
        )
        await db.commit()

    asyncio.create_task(_run_dagent_task(task_id, org_id, file_id_list, env_url))
    return {"status": 0, "data": {"id": task_id}}


@router.get("/task/list")
async def list_tasks():
    async with get_db() as db:
        rows = await db.execute_fetchall(
            "SELECT * FROM multi_hop_gen_task ORDER BY created_at DESC"
        )
        return {"status": 0, "data": [dict(r) for r in rows]}


@router.get("/task/{task_id}")
async def get_task(task_id: str):
    async with get_db() as db:
        rows = await db.execute_fetchall(
            "SELECT * FROM multi_hop_gen_task WHERE id=?", (task_id,)
        )
        if not rows:
            raise HTTPException(status_code=404, detail="Task not found")
        return {"status": 0, "data": dict(rows[0])}


@router.delete("/task/{task_id}")
async def delete_task(task_id: str):
    async with get_db() as db:
        await db.execute("DELETE FROM multi_hop_gen_question WHERE task_id=?", (task_id,))
        await db.execute("DELETE FROM multi_hop_gen_task WHERE id=?", (task_id,))
        await db.commit()
    return {"status": 0}


# ── 问题列表 ──────────────────────────────────────────────────────────────────

@router.get("/task/{task_id}/questions")
async def list_questions(
    task_id: str,
    status: Optional[str] = None,
    page: int = 1,
    page_size: int = 50,
):
    conditions = ["task_id=?"]
    params: list = [task_id]
    if status:
        conditions.append("status=?")
        params.append(status)
    where = " AND ".join(conditions)
    offset = (page - 1) * page_size

    async with get_db() as db:
        count_rows = await db.execute_fetchall(
            f"SELECT COUNT(*) as cnt FROM multi_hop_gen_question WHERE {where}", params
        )
        total = dict(count_rows[0])["cnt"]
        rows = await db.execute_fetchall(
            f"""SELECT * FROM multi_hop_gen_question WHERE {where}
                ORDER BY created_at LIMIT ? OFFSET ?""",
            params + [page_size, offset],
        )

        items = []
        for r in rows:
            d = dict(r)
            d["hops"] = json.loads(d.get("hops") or "[]")
            d["source_sections"] = json.loads(d.get("source_sections") or "[]")
            items.append(d)

    return {"status": 0, "data": {"total": total, "items": items}}


# ── 审核操作 ──────────────────────────────────────────────────────────────────

@router.post("/question/{question_id}/approve")
async def approve_question(question_id: str):
    async with get_db() as db:
        rows = await db.execute_fetchall(
            "SELECT task_id FROM multi_hop_gen_question WHERE id=?", (question_id,)
        )
        if not rows:
            raise HTTPException(status_code=404)
        task_id = dict(rows[0])["task_id"]
        await db.execute(
            "UPDATE multi_hop_gen_question SET status='approved', updated_at=? WHERE id=?",
            (_now(), question_id),
        )
        await _sync_approved(db, task_id)
        await db.commit()
    return {"status": 0}


@router.post("/question/{question_id}/reject")
async def reject_question(question_id: str):
    async with get_db() as db:
        rows = await db.execute_fetchall(
            "SELECT task_id FROM multi_hop_gen_question WHERE id=?", (question_id,)
        )
        if not rows:
            raise HTTPException(status_code=404)
        task_id = dict(rows[0])["task_id"]
        await db.execute(
            "UPDATE multi_hop_gen_question SET status='rejected', updated_at=? WHERE id=?",
            (_now(), question_id),
        )
        await _sync_approved(db, task_id)
        await db.commit()
    return {"status": 0}


class QuestionEditReq(BaseModel):
    question: Optional[str] = None
    answer: Optional[str] = None
    type: Optional[str] = None


@router.put("/question/{question_id}")
async def edit_question(question_id: str, req: QuestionEditReq):
    async with get_db() as db:
        rows = await db.execute_fetchall(
            "SELECT task_id FROM multi_hop_gen_question WHERE id=?", (question_id,)
        )
        if not rows:
            raise HTTPException(status_code=404)
        task_id = dict(rows[0])["task_id"]
        updates, params = [], []
        if req.question is not None:
            updates.append("question=?"); params.append(req.question)
        if req.answer is not None:
            updates.append("answer=?"); params.append(req.answer)
        if req.type is not None:
            updates.append("type=?"); params.append(req.type)
        if not updates:
            raise HTTPException(status_code=400, detail="No fields to update")
        updates += ["status='approved'", "updated_at=?"]
        params += [_now(), question_id]
        await db.execute(
            f"UPDATE multi_hop_gen_question SET {', '.join(updates)} WHERE id=?", params
        )
        await _sync_approved(db, task_id)
        await db.commit()
    return {"status": 0}


@router.post("/task/{task_id}/batch-approve")
async def batch_approve(task_id: str, min_quality: float = 0.0):
    async with get_db() as db:
        await db.execute(
            """UPDATE multi_hop_gen_question SET status='approved', updated_at=?
               WHERE task_id=? AND status='pending'
               AND (quality_score IS NULL OR quality_score >= ?)""",
            (_now(), task_id, min_quality),
        )
        await _sync_approved(db, task_id)
        await db.commit()
    return {"status": 0}


# ── 导出 MD ───────────────────────────────────────────────────────────────────

@router.get("/task/{task_id}/export-md")
async def export_md(task_id: str):
    """导出已通过的多跳问答对为标准 MD 格式（可直接用于多跳召回测试）"""
    async with get_db() as db:
        task_rows = await db.execute_fetchall(
            "SELECT name FROM multi_hop_gen_task WHERE id=?", (task_id,)
        )
        if not task_rows:
            raise HTTPException(status_code=404)
        task_name = dict(task_rows[0]).get("name", task_id)

        rows = await db.execute_fetchall(
            """SELECT * FROM multi_hop_gen_question
               WHERE task_id=? AND status='approved'
               ORDER BY created_at""",
            (task_id,),
        )
        # Convert rows to dicts while connection is still open
        row_dicts = [dict(r) for r in rows]

    if not row_dicts:
        raise HTTPException(status_code=404, detail="没有已通过的问题")

    lines = []
    for i, d in enumerate(row_dicts, 1):
        hops = json.loads(d.get("hops") or "[]")
        qid = d.get("qid") or f"MH{i}"
        lines.append(f"## {qid}")
        lines.append(f"**类型:** {d.get('type', 'reasoning')}")
        lines.append(f"**问题:** {d['question']}")
        lines.append(f"**答案:** {d['answer']}")
        for j, hop in enumerate(hops, 1):
            section = hop.get("section_path", "")
            contrib = hop.get("contribution", "")
            chunk_id = hop.get("chunk_id") or hop.get("paragraph_chunk_id") or ""
            if chunk_id:
                lines.append(f"**Hop{j}:** {section} | {contrib} | {chunk_id}")
            else:
                lines.append(f"**Hop{j}:** {section} | {contrib}")
        lines.append("---")
        lines.append("")

    md_content = "\n".join(lines)
    filename_encoded = quote(f"multi_hop_{task_name}.md".replace(" ", "_"))
    return StreamingResponse(
        iter([md_content.encode("utf-8")]),
        media_type="text/markdown",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{filename_encoded}"},
    )


class CreateTestReq(BaseModel):
    env_url: str
    org_id: str
    agent_id: str
    llm_type: str = "deepseek_v3"
    d_user_id: str = "test"
    top_k: int = 10
    concurrency: int = 5
    name: str = ""


@router.post("/task/{task_id}/create-test")
async def create_test_from_gen(task_id: str, req: CreateTestReq):
    """将已通过的多跳问答对直接创建为召回测试任务"""
    async with get_db() as db:
        task_rows = await db.execute_fetchall(
            "SELECT name FROM multi_hop_gen_task WHERE id=?", (task_id,)
        )
        if not task_rows:
            raise HTTPException(status_code=404, detail="生成任务不存在")
        task_name = dict(task_rows[0]).get("name", task_id)

        rows = await db.execute_fetchall(
            """SELECT * FROM multi_hop_gen_question
               WHERE task_id=? AND status='approved'
               ORDER BY created_at""",
            (task_id,),
        )
        # Convert rows to dicts while connection is still open
        row_dicts = [dict(r) for r in rows]

    if not row_dicts:
        raise HTTPException(status_code=400, detail="没有已通过的问题，请先审核通过至少一个问题")

    # 构建 MD 内容
    lines = []
    for i, d in enumerate(row_dicts, 1):
        hops = json.loads(d.get("hops") or "[]")
        qid = d.get("qid") or f"MH{i}"
        lines.append(f"## {qid}")
        lines.append(f"**类型:** {d.get('type', 'reasoning')}")
        lines.append(f"**问题:** {d['question']}")
        lines.append(f"**答案:** {d['answer']}")
        for j, hop in enumerate(hops, 1):
            section = hop.get("section_path", "")
            contrib = hop.get("contribution", "")
            chunk_id = hop.get("chunk_id") or hop.get("paragraph_chunk_id") or ""
            if chunk_id:
                lines.append(f"**Hop{j}:** {section} | {contrib} | {chunk_id}")
            else:
                lines.append(f"**Hop{j}:** {section} | {contrib}")
        lines.append("---")
        lines.append("")
    md_content = "\n".join(lines)

    # 直接写入 multi_hop_task 并触发后台任务
    from api.multi_hop import _run_task as _run_test_task
    test_name = req.name or f"{task_name}-召回测试"
    test_task_id = _id()

    async with get_db() as db:
        await db.execute(
            """INSERT INTO multi_hop_task
               (id,name,env_url,org_id,d_user_id,agent_id,llm_type,top_k,concurrency,status,created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (test_task_id, test_name, req.env_url, req.org_id,
             req.d_user_id, req.agent_id, req.llm_type,
             req.top_k, req.concurrency, "pending", _now()),
        )
        await db.commit()

    asyncio.create_task(_run_test_task(
        test_task_id, md_content, req.env_url, req.org_id,
        req.d_user_id, req.agent_id, req.llm_type,
        req.top_k, req.concurrency,
    ))

    return {"status": 0, "data": {"test_task_id": test_task_id, "question_count": len(row_dicts)}}


# ── 内部：运行生成任务 ─────────────────────────────────────────────────────────

async def _run_task(task_id: str, md_text: str):
    try:
        # 获取任务配置
        async with get_db() as db:
            cfg_rows = await db.execute_fetchall(
                "SELECT t.*, j.base_url, j.api_key, j.model "
                "FROM multi_hop_gen_task t JOIN judge_config j ON t.judge_config_id=j.id "
                "WHERE t.id=?",
                (task_id,),
            )
        if not cfg_rows:
            raise ValueError("judge_config not found")
        cfg = dict(cfg_rows[0])
        hops_per_question = cfg["hops_per_question"]
        questions_per_group = cfg["questions_per_group"]
        quality_threshold = cfg["quality_threshold"]
        requirements = await _load_requirements(cfg.get("prompt_template_id"))

        # 切分章节
        sections = _parse_knowledge_md(md_text)
        if len(sections) < hops_per_question:
            raise ValueError(f"文档章节数（{len(sections)}）少于 hops_per_question（{hops_per_question}），无法生成多跳问题")

        # 将章节分组：每组 hops_per_question 个，滑动窗口
        import random
        groups = _make_groups(sections, hops_per_question)
        total = len(groups)

        async with get_db() as db:
            await db.execute(
                "UPDATE multi_hop_gen_task SET status='running', total=? WHERE id=?",
                (total, task_id),
            )
            await db.commit()

        sem = asyncio.Semaphore(3)
        done = 0
        question_counter = [0]

        async def gen_group(group: list[tuple[str, str]]):
            nonlocal done
            async with sem:
                questions = await _generate_multi_hop_questions(
                    cfg=cfg,
                    sections=group,
                    n=questions_per_group,
                    hops=hops_per_question,
                    requirements=requirements,
                )
                async with get_db() as db2:
                    for q in questions:
                        question_counter[0] += 1
                        qid = f"MH{question_counter[0]}"
                        quality_score = q.get("quality_score", 0.8)
                        status = "approved" if quality_score >= quality_threshold else "pending"
                        source_sections = [s for s, _ in group]
                        await db2.execute(
                            """INSERT INTO multi_hop_gen_question
                               (id,task_id,qid,question,answer,type,hops,source_sections,
                                quality_score,status,created_at)
                               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                            (
                                _id(), task_id, qid,
                                q["question"], q["answer"], q.get("type", "reasoning"),
                                json.dumps(q.get("hops", []), ensure_ascii=False),
                                json.dumps(source_sections, ensure_ascii=False),
                                quality_score, status, _now(),
                            ),
                        )
                    done += 1
                    await db2.execute(
                        "UPDATE multi_hop_gen_task SET progress=? WHERE id=?", (done, task_id)
                    )
                    await _sync_approved(db2, task_id)
                    await db2.commit()

        await asyncio.gather(*[gen_group(g) for g in groups])

        async with get_db() as db:
            await db.execute(
                "UPDATE multi_hop_gen_task SET status='done', finished_at=? WHERE id=?",
                (_now(), task_id),
            )
            await db.commit()

    except Exception as exc:
        async with get_db() as db:
            await db.execute(
                "UPDATE multi_hop_gen_task SET status='failed', error_message=? WHERE id=?",
                (str(exc), task_id),
            )
            await db.commit()


def _parse_knowledge_md(md_text: str) -> list[tuple[str, str]]:
    """按 ## 标题切分章节，返回 (section_path, content) 列表"""
    lines = md_text.splitlines()
    sections: list[tuple[str, str]] = []
    current_path: list[str] = []
    current_lines: list[str] = []
    current_level = 0

    for line in lines:
        m = re.match(r'^(#{1,4})\s+(.+)', line)
        if m:
            if current_path and current_lines:
                content = "\n".join(current_lines).strip()
                if content:
                    sections.append(("/".join(current_path), content))
            level = len(m.group(1))
            title = m.group(2).strip()
            if level > current_level:
                current_path.append(title)
            elif level == current_level:
                current_path = current_path[:level - 1] + [title]
            else:
                current_path = current_path[:level - 1] + [title]
            current_level = level
            current_lines = []
        else:
            current_lines.append(line)

    if current_path and current_lines:
        content = "\n".join(current_lines).strip()
        if content:
            sections.append(("/".join(current_path), content))

    return sections


def _make_groups(
    sections: list[tuple[str, str]],
    hops: int,
) -> list[list[tuple[str, str]]]:
    """
    将章节列表组合成多跳分组。
    策略：随机采样，每组 hops 个不同章节，最多生成 min(len*2, 50) 组避免过多。
    """
    import random
    n = len(sections)
    max_groups = min(n * 2, 60)
    groups = []
    seen: set[frozenset] = set()

    # 先做滑动窗口（相邻章节更可能有关联）
    for i in range(n - hops + 1):
        group = sections[i:i + hops]
        key = frozenset(s for s, _ in group)
        if key not in seen:
            seen.add(key)
            groups.append(group)

    # 再随机补充
    attempts = 0
    while len(groups) < max_groups and attempts < max_groups * 3:
        attempts += 1
        idxs = random.sample(range(n), min(hops, n))
        group = [sections[i] for i in sorted(idxs)]
        key = frozenset(s for s, _ in group)
        if key not in seen:
            seen.add(key)
            groups.append(group)

    return groups


async def _load_requirements(prompt_template_id: str | None) -> str:
    """从数据库加载提示词模板内容，无模板则返回内置默认"""
    from api.prompt_template import DEFAULT_CONTENT
    if not prompt_template_id:
        return DEFAULT_CONTENT
    async with get_db() as db:
        rows = await db.execute_fetchall(
            "SELECT content FROM prompt_template WHERE id=?", (prompt_template_id,)
        )
        if rows:
            return dict(rows[0])["content"]
    return DEFAULT_CONTENT


async def _generate_multi_hop_questions(
    cfg: dict,
    sections: list[tuple[str, str]],
    n: int,
    hops: int,
    requirements: str = "",
) -> list[dict]:
    """调用 LLM 生成多跳问答对"""
    import aiohttp

    base_url = cfg.get("base_url", "").rstrip("/")
    api_key = cfg.get("api_key", "")
    model = cfg.get("model", "gpt-4o-mini")

    # 构建章节描述
    section_blocks = []
    for i, (path, content) in enumerate(sections, 1):
        truncated = content[:1500] if len(content) > 1500 else content
        section_blocks.append(f"【章节{i}】路径：{path}\n{truncated}")
    sections_text = "\n\n".join(section_blocks)

    hop_labels = "、".join([f"章节{i+1}" for i in range(hops)])
    type_examples = "comparison（比较型）、reasoning（推理型）、aggregation（聚合型）"

    prompt = f"""你是一个专业的技术文档多跳问答生成专家。

以下是来自同一知识库的 {hops} 个不同章节，请生成 {n} 个需要同时参考这 {hops} 个章节才能完整回答的多跳问题。

{sections_text}

要求：
{requirements}

只输出 JSON 数组，不要有其他内容：
[
  {{
    "question": "问题文本",
    "answer": "综合多个章节的参考答案",
    "type": "comparison",
    "quality_score": 0.85,
    "hops": [
      {{"section_path": "{sections[0][0] if sections else ''}", "contribution": "该章节提供了..."}},
      {{"section_path": "{sections[1][0] if len(sections) > 1 else ''}", "contribution": "该章节提供了..."}}
    ]
  }}
]"""

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.4,
    }

    try:
        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.post(
                f"{base_url}/chat/completions",
                json=payload,
                timeout=aiohttp.ClientTimeout(total=90),
            ) as resp:
                resp.raise_for_status()
                data = await resp.json()

        text = data["choices"][0]["message"]["content"].strip()
        m = re.search(r'\[.*\]', text, re.DOTALL)
        if not m:
            return []
        questions = json.loads(m.group())
        result = []
        for q in questions:
            if not isinstance(q, dict):
                continue
            if not q.get("question") or not q.get("answer"):
                continue
            hops_data = q.get("hops", [])
            # 校验 hops 数量
            if len(hops_data) < 2:
                continue
            result.append({
                "question": str(q["question"]).strip(),
                "answer": str(q["answer"]).strip(),
                "type": str(q.get("type", "reasoning")).strip(),
                "quality_score": float(q.get("quality_score", 0.8)),
                "hops": [
                    {
                        "section_path": str(h.get("section_path", "")).strip(),
                        "contribution": str(h.get("contribution", "")).strip(),
                    }
                    for h in hops_data if isinstance(h, dict)
                ],
            })
        return result
    except Exception:
        return []


async def _sync_approved(db, task_id: str):
    rows = await db.execute_fetchall(
        "SELECT COUNT(*) as cnt FROM multi_hop_gen_question WHERE task_id=? AND status='approved'",
        (task_id,),
    )
    approved = dict(rows[0])["cnt"] if rows else 0
    await db.execute(
        "UPDATE multi_hop_gen_task SET approved=? WHERE id=?", (approved, task_id)
    )


async def _run_dagent_task(task_id: str, org_id: str, file_id_list: list[str], env_url: str = ""):
    """
    从 Dagent 拉取段落，按文件分组后跨文件生成多跳问答对。

    分组策略：
    - 将段落按 file_name 聚合成文件级 section
    - 每组随机选 hops_per_question 个不同文件的 section 组合
    - 调用 LLM 生成跨文件多跳问题
    """
    try:
        # 获取任务配置
        async with get_db() as db:
            cfg_rows = await db.execute_fetchall(
                "SELECT t.*, j.base_url, j.api_key, j.model "
                "FROM multi_hop_gen_task t JOIN judge_config j ON t.judge_config_id=j.id "
                "WHERE t.id=?",
                (task_id,),
            )
        if not cfg_rows:
            raise ValueError("judge_config not found")
        cfg = dict(cfg_rows[0])
        hops_per_question = cfg["hops_per_question"]
        questions_per_group = cfg["questions_per_group"]
        quality_threshold = cfg["quality_threshold"]
        requirements = await _load_requirements(cfg.get("prompt_template_id"))

        # 1. 从 Dagent 拉取段落
        paragraphs = await _fetch_paragraphs(org_id, file_id_list, env_url)
        if not paragraphs:
            raise ValueError("未获取到任何段落，请检查 org_id 和文件选择")

        # 2. 按文件聚合段落 -> file_sections: {file_name: [(section_path, content), ...]}
        from collections import defaultdict
        file_sections: dict[str, list[tuple[str, str]]] = defaultdict(list)
        for para in paragraphs:
            file_name = para.get("file_name") or para.get("file_id", "unknown")
            headers = (para.get("headers") or "").strip()
            text = (para.get("paragraph_context") or "").strip()
            pic = (para.get("paragraph_pic_semantics_context") or "").strip()
            if not text:
                continue
            content = text
            if pic:
                content += f"\n\n[图片描述] {pic[:500]}"
            section_path = f"{file_name}/{headers}" if headers else file_name
            file_sections[file_name].append((section_path, content[:2000]))

        # 每个文件取最具代表性的段落（最长的前 N 个）
        file_repr: dict[str, tuple[str, str]] = {}
        for fname, secs in file_sections.items():
            # 取内容最长的段落作为该文件的代表
            best = max(secs, key=lambda x: len(x[1]))
            file_repr[fname] = best

        file_names = list(file_repr.keys())
        if len(file_names) < hops_per_question:
            raise ValueError(
                f"文件数（{len(file_names)}）少于 hops_per_question（{hops_per_question}），"
                "请减少 Hop 数或选择更多文件"
            )

        # 3. 生成跨文件分组
        sections_flat = list(file_repr.values())  # [(section_path, content), ...]
        groups = _make_groups(sections_flat, hops_per_question)
        total = len(groups)

        async with get_db() as db:
            await db.execute(
                "UPDATE multi_hop_gen_task SET status='running', total=? WHERE id=?",
                (total, task_id),
            )
            await db.commit()

        # 4. 并发生成
        sem = asyncio.Semaphore(3)
        done = 0
        question_counter = [0]

        async def gen_group(group: list[tuple[str, str]]):
            nonlocal done
            async with sem:
                questions = await _generate_multi_hop_questions(
                    cfg=cfg,
                    sections=group,
                    n=questions_per_group,
                    hops=hops_per_question,
                    requirements=requirements,
                )
                async with get_db() as db2:
                    for q in questions:
                        question_counter[0] += 1
                        qid = f"MH{question_counter[0]}"
                        quality_score = q.get("quality_score", 0.8)
                        status = "approved" if quality_score >= quality_threshold else "pending"
                        source_sections = [s for s, _ in group]
                        await db2.execute(
                            """INSERT INTO multi_hop_gen_question
                               (id,task_id,qid,question,answer,type,hops,source_sections,
                                quality_score,status,created_at)
                               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                            (
                                _id(), task_id, qid,
                                q["question"], q["answer"], q.get("type", "reasoning"),
                                json.dumps(q.get("hops", []), ensure_ascii=False),
                                json.dumps(source_sections, ensure_ascii=False),
                                quality_score, status, _now(),
                            ),
                        )
                    done += 1
                    await db2.execute(
                        "UPDATE multi_hop_gen_task SET progress=? WHERE id=?", (done, task_id)
                    )
                    await _sync_approved(db2, task_id)
                    await db2.commit()

        await asyncio.gather(*[gen_group(g) for g in groups])

        async with get_db() as db:
            await db.execute(
                "UPDATE multi_hop_gen_task SET status='done', finished_at=? WHERE id=?",
                (_now(), task_id),
            )
            await db.commit()

    except Exception as exc:
        async with get_db() as db:
            await db.execute(
                "UPDATE multi_hop_gen_task SET status='failed', error_message=? WHERE id=?",
                (str(exc), task_id),
            )
            await db.commit()
