"""
问题生成 API
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

# Add parent directory to sys.path for relative imports
sys.path.insert(0, str(Path(__file__).parent.parent))
from models.db import get_db, _now, _id

router = APIRouter(prefix="/api/qa-gen", tags=["问题生成"])


# ── 任务 CRUD ─────────────────────────────────────────────────────────────────

@router.post("/task")
async def create_task(
    file: UploadFile = File(...),
    name: str = Form(""),
    judge_config_id: str = Form(...),
    questions_per_section: int = Form(5),
    quality_threshold: float = Form(0.6),
):
    content = await file.read()
    md_text = content.decode("utf-8")

    task_id = _id()
    async with get_db() as db:
        await db.execute(
            """INSERT INTO qa_gen_task
               (id,name,judge_config_id,questions_per_section,quality_threshold,status,created_at)
               VALUES (?,?,?,?,?,?,?)""",
            (task_id, name or file.filename, judge_config_id,
             questions_per_section, quality_threshold, "pending", _now()),
        )
        await db.commit()

    asyncio.create_task(_run_task(task_id, md_text))
    return {"status": 0, "data": {"id": task_id}}


@router.get("/task/list")
async def list_tasks():
    async with get_db() as db:
        rows = await db.execute_fetchall(
            "SELECT * FROM qa_gen_task ORDER BY created_at DESC"
        )
        return {"status": 0, "data": [dict(r) for r in rows]}


class CreateDatasetReq(BaseModel):
    name: str
    knowledge_hub_id: str = ""
    description: str = ""


@router.post("/task/{task_id}/create-dataset")
async def create_dataset_from_qa_gen(task_id: str, req: CreateDatasetReq):
    """根据 QA 生成任务创建评测数据集"""
    async with get_db() as db:
        # 检查任务是否存在
        rows = await db.execute_fetchall(
            "SELECT * FROM qa_gen_task WHERE id=?", (task_id,)
        )
        if not rows:
            raise HTTPException(status_code=404, detail="QA 生成任务不存在")

        # 获取已通过的问题
        question_rows = await db.execute_fetchall(
            "SELECT * FROM qa_gen_question WHERE task_id=? AND status='approved'",
            (task_id,)
        )
        if not question_rows:
            raise HTTPException(status_code=400, detail="没有已通过的问题")

        # 创建数据集
        dataset_id = _id()
        await db.execute(
            "INSERT INTO eval_dataset (id,name,description,sample_count,created_at) VALUES (?,?,?,?,?)",
            (dataset_id, req.name, req.description, len(question_rows), _now()),
        )

        # 添加样本
        for q in question_rows:
            q_dict = dict(q)
            sample_id = _id()
            await db.execute(
                """INSERT INTO eval_sample
                   (id,dataset_id,question,reference_answer,relevant_chunk_ids,knowledge_hub_id,source_file_id,metadata)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (sample_id, dataset_id, q_dict["question"], q_dict["reference_answer"],
                 json.dumps([], ensure_ascii=False), req.knowledge_hub_id,
                 None, json.dumps({"source": "qa_gen", "qa_gen_task_id": task_id}, ensure_ascii=False)),
            )

        await db.commit()

    return {"status": 0, "data": {"dataset_id": dataset_id, "sample_count": len(question_rows)}}


@router.get("/task/{task_id}")
async def get_task(task_id: str):
    async with get_db() as db:
        rows = await db.execute_fetchall(
            "SELECT * FROM qa_gen_task WHERE id=?", (task_id,)
        )
        if not rows:
            raise HTTPException(status_code=404, detail="Task not found")
        return {"status": 0, "data": dict(rows[0])}


@router.delete("/task/{task_id}")
async def delete_task(task_id: str):
    async with get_db() as db:
        await db.execute("DELETE FROM qa_gen_question WHERE task_id=?", (task_id,))
        await db.execute("DELETE FROM qa_gen_task WHERE id=?", (task_id,))
        await db.commit()
    return {"status": 0, "data": True}


# ── 问题列表 ──────────────────────────────────────────────────────────────────

@router.get("/task/{task_id}/questions")
async def list_questions(
    task_id: str,
    status: Optional[str] = None,
    section: Optional[str] = None,
    page: int = 1,
    page_size: int = 50,
):
    conditions = ["task_id=?"]
    params: list = [task_id]
    if status:
        conditions.append("status=?")
        params.append(status)
    if section:
        conditions.append("section_path=?")
        params.append(section)
    where = " AND ".join(conditions)
    offset = (page - 1) * page_size

    async with get_db() as db:
        count_rows = await db.execute_fetchall(
            f"SELECT COUNT(*) as cnt FROM qa_gen_question WHERE {where}", params
        )
        total = dict(count_rows[0])["cnt"]
        rows = await db.execute_fetchall(
            f"""SELECT id,task_id,section_path,question,reference_answer,source_chunk,
                       quality_score,quality_detail,dup_of,dup_similarity,status,created_at,updated_at,
                       chunk_headers,chunk_id,file_id,file_name
                FROM qa_gen_question WHERE {where}
                ORDER BY section_path, created_at
                LIMIT ? OFFSET ?""",
            params + [page_size, offset],
        )

        items = []
        for r in rows:
            d = dict(r)
            if d.get("quality_detail"):
                try:
                    d["quality_detail"] = json.loads(d["quality_detail"])
                except Exception:
                    pass
            items.append(d)

    return {"status": 0, "data": {"total": total, "items": items}}


@router.get("/task/{task_id}/sections")
async def list_sections(task_id: str):
    """返回任务下各章节的问题统计"""
    async with get_db() as db:
        rows = await db.execute_fetchall(
            """SELECT section_path,
                      COUNT(*) as total,
                      SUM(CASE WHEN status='approved' THEN 1 ELSE 0 END) as approved,
                      SUM(CASE WHEN status='rejected' THEN 1 ELSE 0 END) as rejected,
                      SUM(CASE WHEN status='pending' THEN 1 ELSE 0 END) as pending,
                      SUM(CASE WHEN dup_of IS NOT NULL THEN 1 ELSE 0 END) as duplicates,
                      AVG(quality_score) as avg_quality
               FROM qa_gen_question WHERE task_id=?
               GROUP BY section_path ORDER BY section_path""",
            (task_id,),
        )
        return {"status": 0, "data": [dict(r) for r in rows]}


# ── 审核操作 ──────────────────────────────────────────────────────────────────

@router.post("/question/{question_id}/approve")
async def approve_question(question_id: str):
    async with get_db() as db:
        rows = await db.execute_fetchall(
            "SELECT task_id FROM qa_gen_question WHERE id=?", (question_id,)
        )
        if not rows:
            raise HTTPException(status_code=404, detail="Question not found")
        task_id = dict(rows[0])["task_id"]
        await db.execute(
            "UPDATE qa_gen_question SET status='approved', updated_at=? WHERE id=?",
            (_now(), question_id),
        )
        await _sync_approved_count(db, task_id)
        await db.commit()
    return {"status": 0, "data": True}


@router.post("/question/{question_id}/reject")
async def reject_question(question_id: str):
    async with get_db() as db:
        rows = await db.execute_fetchall(
            "SELECT task_id FROM qa_gen_question WHERE id=?", (question_id,)
        )
        if not rows:
            raise HTTPException(status_code=404, detail="Question not found")
        task_id = dict(rows[0])["task_id"]
        await db.execute(
            "UPDATE qa_gen_question SET status='rejected', updated_at=? WHERE id=?",
            (_now(), question_id),
        )
        await _sync_approved_count(db, task_id)
        await db.commit()
    return {"status": 0, "data": True}


class QuestionEditReq(BaseModel):
    question: Optional[str] = None
    reference_answer: Optional[str] = None


@router.put("/question/{question_id}")
async def edit_question(question_id: str, req: QuestionEditReq):
    async with get_db() as db:
        rows = await db.execute_fetchall(
            "SELECT task_id FROM qa_gen_question WHERE id=?", (question_id,)
        )
        if not rows:
            raise HTTPException(status_code=404, detail="Question not found")
        task_id = dict(rows[0])["task_id"]
        updates = []
        params = []
        if req.question is not None:
            updates.append("question=?")
            params.append(req.question)
        if req.reference_answer is not None:
            updates.append("reference_answer=?")
            params.append(req.reference_answer)
        if not updates:
            raise HTTPException(status_code=400, detail="No fields to update")
        updates.append("status='approved'")
        updates.append("updated_at=?")
        params.append(_now())
        params.append(question_id)
        await db.execute(
            f"UPDATE qa_gen_question SET {', '.join(updates)} WHERE id=?", params
        )
        await _sync_approved_count(db, task_id)
        await db.commit()
    return {"status": 0, "data": True}


@router.post("/task/{task_id}/batch-approve")
async def batch_approve(task_id: str, min_quality: float = 0.0):
    """批量通过：通过 quality_score >= min_quality 且非重复的 pending 问题"""
    async with get_db() as db:
        await db.execute(
            """UPDATE qa_gen_question SET status='approved', updated_at=?
               WHERE task_id=? AND status='pending' AND dup_of IS NULL
               AND (quality_score IS NULL OR quality_score >= ?)""",
            (_now(), task_id, min_quality),
        )
        await _sync_approved_count(db, task_id)
        await db.commit()
    return {"status": 0, "data": True}


# ── 导出 MD ───────────────────────────────────────────────────────────────────

@router.get("/task/{task_id}/export-md")
async def export_md(task_id: str):
    """导出已通过的问题为标准 MD 格式（与单跳测试输入格式一致）"""
    async with get_db() as db:
        task_rows = await db.execute_fetchall(
            "SELECT name FROM qa_gen_task WHERE id=?", (task_id,)
        )
        if not task_rows:
            raise HTTPException(status_code=404, detail="Task not found")
        task_name = dict(task_rows[0]).get("name", task_id)

        rows = await db.execute_fetchall(
            """SELECT section_path, qid, question, reference_answer, file_name
               FROM (
                 SELECT section_path, question, reference_answer, file_name,
                        ROW_NUMBER() OVER (PARTITION BY section_path ORDER BY created_at) as rn,
                        'Q' || ROW_NUMBER() OVER (PARTITION BY section_path ORDER BY created_at) as qid
                 FROM qa_gen_question
                 WHERE task_id=? AND status='approved'
               )
               ORDER BY section_path, rn""",
            (task_id,),
        )
        # Convert rows to dicts while connection is still open
        row_dicts = [dict(r) for r in rows]

    if not row_dicts:
        raise HTTPException(status_code=404, detail="没有已通过的问题")

    from collections import defaultdict
    sections: dict[str, list] = defaultdict(list)
    section_file_names: dict[str, str] = {}
    for d in row_dicts:
        sections[d["section_path"]].append(d)
        if d.get("file_name") and d["section_path"] not in section_file_names:
            section_file_names[d["section_path"]] = d["file_name"]

    lines = []
    import re

    def clean_for_parser(text: str) -> str:
        """清理文本以匹配解析器正则表达式，保留中文字符"""
        if not text:
            return "default"
        # 保留中文字符、数字、字母、下划线、斜杠、空格、点、连字符
        cleaned = re.sub(r'[^一-龥a-zA-Z0-9_/ .\-]', '_', text)
        cleaned = cleaned.strip()
        if cleaned.startswith('.'):
            cleaned = '_' + cleaned[1:]
        return cleaned if cleaned else "default_section"

    section_index = 0
    for section_path, items in sections.items():
        section_index += 1
        file_name = section_file_names.get(section_path)

        if file_name:
            # 使用 Dagent 的 file_name 作为 section 标识
            doc_name = file_name.rsplit(".", 1)[0] if "." in file_name else file_name
            chapter_title = f"第{section_index}章 {doc_name.split('/')[-1]}"
            lines.append(f"# {chapter_title}")
            lines.append(f"## {file_name} / {doc_name}")
            lines.append(f"# {section_index}. {doc_name.split('/')[-1]}_Document")
        else:
            # 回退：没有 file_name 时用清理后的 section_path
            clean_section_path = clean_for_parser(section_path)
            raw_doc_name = section_path.split("/")[-1] if "/" in section_path else section_path
            clean_doc_name = clean_for_parser(raw_doc_name)
            chapter_title = f"第{section_index}章 {clean_doc_name}"
            lines.append(f"# {chapter_title}")
            lines.append(f"## {clean_section_path} / {clean_doc_name}")
            lines.append(f"# {section_index}. {clean_doc_name}_Document")

        lines.append("> Generated from QA generation task")
        lines.append("---")
        lines.append("")
        for item in items:
            qid = item["qid"]
            aid = qid.replace("Q", "A")
            lines.append(f"## {qid}: {item['question']}")
            lines.append(f"**{aid}:** {item['reference_answer']}")
            lines.append("")
        lines.append("---")
        lines.append("")

    md_content = "\n".join(lines)
    filename_encoded = quote(f"qa_{task_name}.md".replace(" ", "_"))
    return StreamingResponse(
        iter([md_content.encode("utf-8")]),
        media_type="text/markdown",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{filename_encoded}"},
    )


# ── 内部：运行生成任务 ─────────────────────────────────────────────────────────

async def _run_task(task_id: str, md_text: str):
    try:
        from rag_eval.single_jump.parser import parse_qa_file_text as _parse

        # 复用 single_jump parser 解析章节结构，但这里 md_text 是知识库原文
        # 需要用自定义解析器按 ## 切分章节
        sections = _parse_knowledge_md(md_text)
        total = len(sections)

        async with get_db() as db:
            await db.execute(
                "UPDATE qa_gen_task SET status='running', total=? WHERE id=?",
                (total, task_id),
            )
            await db.commit()

        # 获取 judge_config
        async with get_db() as db:
            cfg_rows = await db.execute_fetchall(
                "SELECT * FROM qa_gen_task t JOIN judge_config j ON t.judge_config_id=j.id WHERE t.id=?",
                (task_id,),
            )
        if not cfg_rows:
            raise ValueError("judge_config not found")
        cfg = dict(cfg_rows[0])
        questions_per_section = cfg["questions_per_section"]
        quality_threshold = cfg["quality_threshold"]

        # 逐章节生成
        sem = asyncio.Semaphore(3)
        done = 0

        async def gen_section(section_path: str, content: str):
            nonlocal done
            async with sem:
                questions = await _generate_questions(
                    cfg=cfg,
                    section_path=section_path,
                    content=content,
                    n=questions_per_section,
                )
                async with get_db() as db2:
                    for q in questions:
                        qid = _id()
                        # 简单质量评分：暂时用 LLM 返回的置信度，后续可扩展
                        quality_score = q.get("quality_score", 0.8)
                        status = "approved" if quality_score >= quality_threshold else "pending"
                        await db2.execute(
                            """INSERT INTO qa_gen_question
                               (id,task_id,section_path,question,reference_answer,source_chunk,
                                quality_score,status,created_at)
                               VALUES (?,?,?,?,?,?,?,?,?)""",
                            (qid, task_id, section_path,
                             q["question"], q["answer"], q.get("source_chunk", ""),
                             quality_score, status, _now()),
                        )
                    done += 1
                    await db2.execute(
                        "UPDATE qa_gen_task SET progress=? WHERE id=?", (done, task_id)
                    )
                    await _sync_approved_count(db2, task_id)
                    await db2.commit()

        await asyncio.gather(*[gen_section(sp, ct) for sp, ct in sections])

        async with get_db() as db:
            await db.execute(
                "UPDATE qa_gen_task SET status='done', finished_at=? WHERE id=?",
                (_now(), task_id),
            )
            await db.commit()

    except Exception as exc:
        async with get_db() as db:
            await db.execute(
                "UPDATE qa_gen_task SET status='failed', error_message=? WHERE id=?",
                (str(exc), task_id),
            )
            await db.commit()


def _parse_knowledge_md(md_text: str) -> list[tuple[str, str]]:
    """
    将知识库 MD 文件按 ## 标题切分为 (section_path, content) 列表。
    支持多级标题，用 / 拼接路径。
    """
    lines = md_text.splitlines()
    sections: list[tuple[str, str]] = []
    current_path: list[str] = []
    current_lines: list[str] = []
    current_level = 0

    for line in lines:
        m = re.match(r'^(#{1,4})\s+(.+)', line)
        if m:
            # 保存上一个 section
            if current_path and current_lines:
                content = "\n".join(current_lines).strip()
                if content:
                    sections.append(("/".join(current_path), content))
            level = len(m.group(1))
            title = m.group(2).strip()
            # 调整路径深度
            if level > current_level:
                current_path.append(title)
            elif level == current_level:
                if current_path:
                    current_path[-1] = title
                else:
                    current_path = [title]
            else:
                # 回退到对应层级
                current_path = current_path[:level - 1] + [title]
            current_level = level
            current_lines = []
        else:
            current_lines.append(line)

    # 最后一个 section
    if current_path and current_lines:
        content = "\n".join(current_lines).strip()
        if content:
            sections.append(("/".join(current_path), content))

    return sections


async def _generate_questions(
    cfg: dict,
    section_path: str,
    content: str,
    n: int,
) -> list[dict]:
    """调用 LLM 生成问题，返回 [{question, answer, source_chunk, quality_score}]"""
    import aiohttp

    base_url = cfg.get("base_url", "").rstrip("/")
    api_key = cfg.get("api_key", "")
    model = cfg.get("model", "gpt-4o-mini")

    # 截断过长内容
    content_truncated = content[:3000] if len(content) > 3000 else content

    prompt = f"""你是一个专业的技术文档测试问题生成专家。

根据以下技术文档章节内容，生成 {n} 个测试问题。

章节路径：{section_path}
章节内容：
{content_truncated}

要求：
1. 问题必须能从该章节内容直接回答，不要生成需要跨文档才能回答的问题
2. 问题应覆盖章节的关键知识点，避免过于简单的是非题
3. 问题表述清晰，无歧义
4. 答案准确，与原文一致，长度适中（1-3句话）
5. source_chunk 为答案来源的原文片段（50-150字）
6. quality_score 为你对该问题质量的评估（0-1，1为最高质量）

只输出 JSON 数组，不要有其他内容：
[
  {{
    "question": "问题文本",
    "answer": "参考答案",
    "source_chunk": "答案来源原文片段",
    "quality_score": 0.9
  }}
]"""

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.3,
    }

    try:
        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.post(
                f"{base_url}/chat/completions",
                json=payload,
                timeout=aiohttp.ClientTimeout(total=60),
            ) as resp:
                resp.raise_for_status()
                data = await resp.json()

        text = data["choices"][0]["message"]["content"].strip()
        # 提取 JSON 数组
        m = re.search(r'\[.*\]', text, re.DOTALL)
        if not m:
            return []
        questions = json.loads(m.group())
        # 校验字段
        result = []
        for q in questions:
            if isinstance(q, dict) and q.get("question") and q.get("answer"):
                result.append({
                    "question": str(q["question"]).strip(),
                    "answer": str(q["answer"]).strip(),
                    "source_chunk": str(q.get("source_chunk", "")).strip(),
                    "quality_score": float(q.get("quality_score", 0.8)),
                })
        return result
    except Exception as e:
        # 生成失败不中断整个任务，返回空列表
        return []


async def _sync_approved_count(db, task_id: str):
    """同步更新 qa_gen_task.approved 计数"""
    rows = await db.execute_fetchall(
        "SELECT COUNT(*) as cnt FROM qa_gen_question WHERE task_id=? AND status='approved'",
        (task_id,),
    )
    approved = dict(rows[0])["cnt"] if rows else 0
    await db.execute(
        "UPDATE qa_gen_task SET approved=? WHERE id=?", (approved, task_id)
    )


