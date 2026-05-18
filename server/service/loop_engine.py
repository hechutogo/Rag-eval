# -*- coding: utf-8 -*-
"""
Loop task execution engine with pause/resume support.
"""
import asyncio
import sys
from datetime import datetime
from typing import Optional

# Fix Windows GBK encoding issue
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.stderr.reconfigure(encoding='utf-8', errors='replace')

from models.db import get_db, _id, _now
from service.loop_recall_md import DEFAULT_LLM_NOTE, append_recall_md_section


# Module-level control dictionary for pause/resume/stop
# key=loop_task_id, value={"pause_event": asyncio.Event, "stop": bool}
_loop_controls: dict[str, dict] = {}


async def _check_pause(loop_task_id: str) -> bool:
    """Check if task should pause. Returns True if stopped."""
    ctrl = _loop_controls.get(loop_task_id)
    if not ctrl:
        return False

    if ctrl["stop"]:
        return True

    # Wait for pause_event (will block if event is cleared)
    await ctrl["pause_event"].wait()
    return ctrl["stop"]


def _init_control(loop_task_id: str) -> None:
    """Initialize control structure for a loop task."""
    event = asyncio.Event()
    event.set()  # Initially not paused
    _loop_controls[loop_task_id] = {
        "pause_event": event,
        "stop": False,
    }


def _clear_control(loop_task_id: str) -> None:
    """Clean up control structure."""
    _loop_controls.pop(loop_task_id, None)


async def pause_loop(loop_task_id: str) -> bool:
    """Pause a running loop task."""
    ctrl = _loop_controls.get(loop_task_id)
    if not ctrl:
        return False

    # 立即写数据库，让前端看到"已暂停"状态
    async with get_db() as db:
        await db.execute(
            "UPDATE loop_task SET status='paused', paused_at=? WHERE id=?",
            (_now(), loop_task_id),
        )
        await db.commit()

    # Clear event，后台会在阶段边界停下来
    ctrl["pause_event"].clear()
    return True


async def resume_loop(loop_task_id: str) -> bool:
    """Resume a paused loop task."""
    ctrl = _loop_controls.get(loop_task_id)
    if not ctrl:
        return False

    ctrl["pause_event"].set()
    return True


async def stop_loop(loop_task_id: str) -> bool:
    """Stop a loop task permanently."""
    ctrl = _loop_controls.get(loop_task_id)
    if not ctrl:
        return False

    ctrl["stop"] = True
    ctrl["pause_event"].set()  # Unblock if paused

    async with get_db() as db:
        await db.execute(
            "UPDATE loop_task SET status='stopped', finished_at=? WHERE id=?",
            (_now(), loop_task_id),
        )
        await db.commit()

    return True


async def run_loop_task(
    loop_task_id: str,
    org_id: str,
    file_ids: list[str],
    judge_config_id: str,
    questions_per_section: int,
    quality_threshold: float,
    include_multimodal: bool,
    env_url: str,
    d_user_id: str,
    agent_id: str,
    top_k: int,
    recall_top_k: int,
    concurrency: int,
    cross_chunk: bool,
    max_rounds: int,
    max_questions: int,
    global_dedup: bool = False,  # 是否使用全局去重（跨任务）
):
    """
    Main loop execution engine.

    Each round:
    1. Fetch existing questions from all previous rounds
    2. Generate new questions (avoiding existing angles)
    3. Deduplicate with LLM
    4. Create single-jump test
    5. Wait for test completion
    6. Update stats and check termination conditions
    """
    _init_control(loop_task_id)

    try:
        await _do_run_loop(
            loop_task_id, org_id, file_ids, judge_config_id,
            questions_per_section, quality_threshold, include_multimodal,
            env_url, d_user_id, agent_id, top_k, recall_top_k, concurrency, cross_chunk,
            max_rounds, max_questions, global_dedup
        )
    except Exception as e:
        # Mark as failed
        async with get_db() as db:
            await db.execute(
                "UPDATE loop_task SET status='failed', error_message=? WHERE id=?",
                (str(e), loop_task_id),
            )
            await db.commit()
    finally:
        _clear_control(loop_task_id)


async def _do_run_loop(
    loop_task_id: str,
    org_id: str,
    file_ids: list[str],
    judge_config_id: str,
    questions_per_section: int,
    quality_threshold: float,
    include_multimodal: bool,
    env_url: str,
    d_user_id: str,
    agent_id: str,
    top_k: int,
    recall_top_k: int,
    concurrency: int,
    cross_chunk: bool,
    max_rounds: int,
    max_questions: int,
    global_dedup: bool = False,
):
    """Internal loop implementation."""

    # Get loop task name与批次期望切片数（与 chunk_batches_plan.chunk_count 对齐，用于拉取完整性校验）
    async with get_db() as db:
        task_rows = await db.execute_fetchall(
            "SELECT name, expected_chunk_count FROM loop_task WHERE id=?", (loop_task_id,)
        )
    _tr = dict(task_rows[0]) if task_rows else {}
    loop_task_name = _tr.get("name") or loop_task_id[:8]
    _ecc = _tr.get("expected_chunk_count")
    try:
        expected_chunk_count = int(_ecc) if _ecc is not None and int(_ecc) > 0 else None
    except (TypeError, ValueError):
        expected_chunk_count = None

    # Get judge config for LLM client
    async with get_db() as db:
        cfg_rows = await db.execute_fetchall(
            "SELECT * FROM judge_config WHERE id=?", (judge_config_id,)
        )
    if not cfg_rows:
        raise ValueError("judge_config not found")
    judge_cfg = dict(cfg_rows[0])

    # Initialize Embedding client for dedup (向量相似度查重，不再使用 LLM)
    from openai import AsyncOpenAI
    embed_base = (judge_cfg.get("embed_base_url") or judge_cfg["base_url"]).rstrip("/")
    embed_key = judge_cfg.get("embed_api_key") or judge_cfg["api_key"]
    embed_client = AsyncOpenAI(
        base_url=embed_base,
        api_key=embed_key,
    )
    embed_model = judge_cfg.get("embed_model") or "text-embedding-3-small"

    # Update status to running
    async with get_db() as db:
        await db.execute(
            "UPDATE loop_task SET status='running' WHERE id=?",
            (loop_task_id,),
        )
        await db.commit()

    consecutive_empty_rounds = 0

    def stop_check():
        ctrl = _loop_controls.get(loop_task_id)
        if ctrl is None or ctrl.get("stop", False):
            return True
        return False

    async def async_pause_check():
        """Check if paused and wait for resume. Returns True if should stop."""
        ctrl = _loop_controls.get(loop_task_id)
        if not ctrl:
            return False
        if ctrl.get("stop", False):
            return True
        # Check pause and wait if needed
        if not ctrl["pause_event"].is_set():
            await ctrl["pause_event"].wait()
            if ctrl.get("stop", False):
                return True
        return False

    async def check_pause_between_stages() -> bool:
        """在阶段边界等待暂停信号，返回 True 表示应该停止。"""
        ctrl = _loop_controls.get(loop_task_id)
        if not ctrl:
            return False
        if ctrl["stop"]:
            return True
        # 如果 pause_event 已被 clear，说明用户点了暂停
        # pause_loop 已经写了数据库，这里只需要等待 resume
        if not ctrl["pause_event"].is_set():
            await ctrl["pause_event"].wait()  # 阻塞直到 resume
            if ctrl["stop"]:
                return True
            # resume 后把状态改回 running
            async with get_db() as db:
                await db.execute(
                    "UPDATE loop_task SET status='running', paused_at=NULL WHERE id=?",
                    (loop_task_id,),
                )
                await db.commit()
        return False

    # 确定从哪一轮、哪个阶段开始
    # 查最后一轮的状态，决定是继续该轮还是开新轮
    async with get_db() as db:
        rows = await db.execute_fetchall(
            """SELECT id, round_number, status, qa_gen_task_id, single_jump_task_id
               FROM loop_round
               WHERE loop_task_id=?
               ORDER BY round_number DESC LIMIT 1""",
            (loop_task_id,),
        )

    # resume_round: 需要继续执行的轮次信息，None 表示从新轮开始
    resume_round = None
    if rows:
        last = dict(rows[0])
        if last["status"] != "done":
            resume_round = last  # 需要从这一轮的某个阶段继续
            round_number = last["round_number"] - 1  # 循环会 +1 回到这一轮
        else:
            round_number = last["round_number"]  # 从下一轮开始
    else:
        round_number = 0

    while True:
        # 阶段边界：检查暂停/停止
        if await check_pause_between_stages():
            return

        round_number += 1

        # Check max_rounds
        if max_rounds > 0 and round_number > max_rounds:
            break

        # Check max_questions
        if max_questions > 0:
            async with get_db() as db:
                row = await db.execute_fetchall(
                    "SELECT total_approved FROM loop_task WHERE id=?", (loop_task_id,)
                )
                current_total = row[0]["total_approved"] if row else 0
            if current_total >= max_questions:
                break

        # 判断是继续上次中断的轮次，还是创建新轮次
        if resume_round and resume_round["round_number"] == round_number:
            # 继续上次中断的轮次，复用已有的 round_id 和 qa_gen_task_id
            round_id = resume_round["id"]
            resume_stage = resume_round["status"]  # qa_generating / deduplicating / testing
            qa_task_id = resume_round["qa_gen_task_id"]
            resume_round = None  # 只用一次
        else:
            # 创建新轮次
            resume_stage = None
            round_id = _id()
            qa_task_id = None
            async with get_db() as db:
                await db.execute(
                    """INSERT INTO loop_round
                       (id, loop_task_id, round_number, status, started_at)
                       VALUES (?,?,?,?,?)""",
                    (round_id, loop_task_id, round_number, "qa_generating", _now()),
                )
                await db.execute(
                    "UPDATE loop_task SET current_round=? WHERE id=?",
                    (round_number, loop_task_id),
                )
                await db.commit()

        # 1. Get existing questions from all previous rounds
        section_existing_questions = await _get_existing_questions(loop_task_id, global_dedup=global_dedup)
        all_existing_questions = []
        for questions in section_existing_questions.values():
            all_existing_questions.extend(questions)

        # For QA generation, only pass question text (not ids)
        section_existing_text = {
            sp: [q["question"] for q in qs]
            for sp, qs in section_existing_questions.items()
        }

        # 2. QA 生成阶段
        # 如果是从 deduplicating 或 testing 阶段 resume，跳过 QA 生成
        if resume_stage in ("deduplicating", "testing"):
            # qa_task_id 已经有了，直接跳过生成
            pass
        else:
            # 需要运行 QA 生成（新轮次，或从 qa_generating 阶段 resume）
            if qa_task_id is None:
                qa_task_id = _id()
                async with get_db() as db:
                    await db.execute(
                        """INSERT INTO qa_gen_task
                           (id,name,status,judge_config_id,questions_per_section,quality_threshold,
                            progress,total,created_at)
                           VALUES (?,?,?,?,?,?,?,?,?)""",
                        (qa_task_id, f"{loop_task_name}-问题生成-第{round_number}轮", "pending",
                         judge_config_id, questions_per_section, quality_threshold,
                         0, 0, _now()),
                    )
                    await db.execute(
                        "UPDATE loop_round SET qa_gen_task_id=?, status='qa_generating' WHERE id=?",
                        (qa_task_id, round_id),
                    )
                    await db.commit()
            else:
                # resume_stage == 'qa_generating'：qa_task 已存在但未完成，重新跑
                async with get_db() as db:
                    await db.execute(
                        "UPDATE loop_round SET status='qa_generating' WHERE id=?",
                        (round_id,),
                    )
                    await db.commit()

            from api.qa_gen_dagent import _run_dagent_task
            try:
                await _run_dagent_task(
                    task_id=qa_task_id,
                    org_id=org_id,
                    file_id_list=file_ids,
                    judge_config_id=judge_config_id,
                    questions_per_section=questions_per_section,
                    quality_threshold=quality_threshold,
                    include_multimodal=include_multimodal,
                    section_existing_questions=section_existing_text,
                    stop_check=stop_check,
                    pause_check=async_pause_check,
                    env_url=env_url,
                    expected_chunk_count=expected_chunk_count,
                )
            except Exception as e:
                async with get_db() as db:
                    await db.execute(
                        "UPDATE loop_round SET status='failed', finished_at=? WHERE id=?",
                        (_now(), round_id),
                    )
                    await db.commit()
                raise

        # 阶段边界：QA 生成完成后检查暂停
        if await check_pause_between_stages():
            return

        # 3. 去重阶段
        if resume_stage != "testing":
            async with get_db() as db:
                await db.execute(
                    "UPDATE loop_round SET status='deduplicating' WHERE id=?",
                    (round_id,),
                )
                await db.commit()

            # 按切片分组获取新问题
            new_questions_by_chunk = await _get_new_questions_by_chunk(qa_task_id)

            # 按切片分组获取已有问题（用于查重），排除本轮 qa_task_id 避免自查自
            existing_by_chunk = await _get_existing_questions_by_chunk(
                loop_task_id,
                exclude_qa_task_id=qa_task_id,
                global_dedup=global_dedup,
            )

            if new_questions_by_chunk:
                from service.dedup import deduplicate_questions_by_chunk

                async def on_dedup_progress(done: int, total: int):
                    async with get_db() as db:
                        await db.execute(
                            "UPDATE loop_round SET dedup_progress=? WHERE id=?",
                            (f"{done}/{total}", round_id),
                        )
                        await db.commit()

                # 按切片并行查重（正则归一化 + 向量余弦相似度）
                dup_results = await deduplicate_questions_by_chunk(
                    new_questions_by_chunk,
                    existing_by_chunk,
                    embed_client,
                    embed_model,
                    similarity_threshold=0.85,
                    max_parallel_chunks=5,
                    stop_check=stop_check,
                    pause_check=async_pause_check,
                    on_progress=on_dedup_progress,
                )

                if stop_check():
                    return

                async with get_db() as db:
                    for qid, (dup_of, sim) in dup_results.items():
                        if dup_of:
                            await db.execute(
                                """UPDATE qa_gen_question
                                   SET dup_of=?, dup_similarity=?, status='rejected'
                                   WHERE id=?""",
                                (dup_of, sim, qid),
                            )
                    await db.commit()

        # 阶段边界：去重完成后检查暂停
        if await check_pause_between_stages():
            return

        # 统计本轮数据
        async with get_db() as db:
            counts = await db.execute_fetchall(
                """SELECT
                    COUNT(*) as generated,
                    SUM(CASE WHEN status='approved' THEN 1 ELSE 0 END) as approved,
                    SUM(CASE WHEN dup_of IS NOT NULL THEN 1 ELSE 0 END) as duplicates
                FROM qa_gen_question WHERE task_id=?""",
                (qa_task_id,),
            )
            gen_count = counts[0]["generated"] if counts else 0
            app_count = counts[0]["approved"] if counts else 0
            dup_count = counts[0]["duplicates"] if counts else 0
            # SUM 在没有匹配行时返回 NULL，统一成 0 避免后续 None 比较
            gen_count = gen_count or 0
            app_count = app_count or 0
            dup_count = dup_count or 0

        async with get_db() as db:
            await db.execute(
                """UPDATE loop_round
                   SET generated=?, approved=?, duplicates=?, status='testing'
                   WHERE id=?""",
                (gen_count, app_count, dup_count, round_id),
            )
            await db.commit()

        # 收敛检测
        if app_count == 0:
            consecutive_empty_rounds += 1
            if consecutive_empty_rounds >= 2:
                break
        else:
            consecutive_empty_rounds = 0

        # 4. 召回测试阶段
        if app_count > 0:
            await _run_single_jump_for_round(
                loop_task_id, loop_task_name, round_number, round_id, qa_task_id,
                env_url, org_id, d_user_id, agent_id, top_k, recall_top_k, concurrency, cross_chunk
            )

        # 阶段边界：召回测试完成后检查暂停
        if await check_pause_between_stages():
            return

        # 5. 更新累计统计
        await _update_loop_stats(loop_task_id)

        async with get_db() as db:
            await db.execute(
                "UPDATE loop_round SET status='done', finished_at=? WHERE id=?",
                (_now(), round_id),
            )
            await db.commit()

    # Loop finished normally
    async with get_db() as db:
        await db.execute(
            "UPDATE loop_task SET status='done', finished_at=? WHERE id=?",
            (_now(), loop_task_id),
        )
        await db.commit()


async def _get_existing_questions(loop_task_id: str, global_dedup: bool = False) -> dict[str, list[str]]:
    """Get all approved questions, grouped by section_path.

    Args:
        loop_task_id: Current loop task ID
        global_dedup: If True, get all approved questions from database (cross-task dedup)
                     If False, only get questions from this loop task (default)
    """
    async with get_db() as db:
        if global_dedup:
            # 全局去重：获取所有已批准的问题（跨任务）
            rows = await db.execute_fetchall(
                """SELECT q.id, q.section_path, q.question
                   FROM qa_gen_question q
                   WHERE q.status = 'approved'
                   ORDER BY q.created_at""",
            )
        else:
            # 任务内去重：只获取当前循环任务的问题
            rows = await db.execute_fetchall(
                """SELECT q.id, q.section_path, q.question
                   FROM qa_gen_question q
                   JOIN loop_round lr ON q.task_id = lr.qa_gen_task_id
                   WHERE lr.loop_task_id = ? AND q.status = 'approved'
                   ORDER BY q.created_at""",
                (loop_task_id,),
            )

    result: dict[str, list] = {}
    for row in rows:
        sp = row["section_path"]
        if sp not in result:
            result[sp] = []
        result[sp].append({"id": row["id"], "question": row["question"]})

    return result


async def _get_new_questions(qa_task_id: str) -> list[dict]:
    """Get all questions from a QA task."""
    async with get_db() as db:
        rows = await db.execute_fetchall(
            "SELECT id, question FROM qa_gen_question WHERE task_id=?",
            (qa_task_id,),
        )
    return [{"id": r["id"], "question": r["question"]} for r in rows]


async def _get_new_questions_by_chunk(qa_task_id: str) -> dict[str, list[dict]]:
    """按切片分组获取新问题。

    Returns:
        {chunk_id: [{id, question, ...}]}
    """
    async with get_db() as db:
        rows = await db.execute_fetchall(
            """SELECT id, question, chunk_id, section_path
               FROM qa_gen_question
               WHERE task_id=?""",
            (qa_task_id,),
        )

    result: dict[str, list] = {}
    for row in rows:
        chunk_id = row["chunk_id"] or row["section_path"] or "default"
        if chunk_id not in result:
            result[chunk_id] = []
        result[chunk_id].append({
            "id": row["id"],
            "question": row["question"],
            "chunk_id": row["chunk_id"],
            "section_path": row["section_path"],
        })

    return result


async def _get_existing_questions_by_chunk(
    loop_task_id: str,
    exclude_qa_task_id: str | None = None,
    global_dedup: bool = False,
) -> dict[str, list[tuple[str, str]]]:
    """按切片分组获取已有问题（用于查重）。

    Args:
        loop_task_id: 当前循环任务ID
        exclude_qa_task_id: 排除的 qa_gen_task_id（即本轮刚生成的一批，避免自己查自己）
        global_dedup: 是否全局去重（跨任务）

    Returns:
        {chunk_id: [(id, question)]}
    """
    async with get_db() as db:
        if global_dedup:
            # 全局去重：获取所有已批准的问题，但排除本轮 qa_task
            if exclude_qa_task_id:
                rows = await db.execute_fetchall(
                    """SELECT id, chunk_id, section_path, question
                       FROM qa_gen_question
                       WHERE status = 'approved' AND task_id != ?
                       ORDER BY created_at""",
                    (exclude_qa_task_id,),
                )
            else:
                rows = await db.execute_fetchall(
                    """SELECT id, chunk_id, section_path, question
                       FROM qa_gen_question
                       WHERE status = 'approved'
                       ORDER BY created_at""",
                )
        else:
            # 任务内去重：只获取当前循环任务的问题，但排除本轮 qa_task
            if exclude_qa_task_id:
                rows = await db.execute_fetchall(
                    """SELECT q.id, q.chunk_id, q.section_path, q.question
                       FROM qa_gen_question q
                       JOIN loop_round lr ON q.task_id = lr.qa_gen_task_id
                       WHERE lr.loop_task_id = ?
                         AND q.status = 'approved'
                         AND q.task_id != ?
                       ORDER BY q.created_at""",
                    (loop_task_id, exclude_qa_task_id),
                )
            else:
                rows = await db.execute_fetchall(
                    """SELECT q.id, q.chunk_id, q.section_path, q.question
                       FROM qa_gen_question q
                       JOIN loop_round lr ON q.task_id = lr.qa_gen_task_id
                       WHERE lr.loop_task_id = ? AND q.status = 'approved'
                       ORDER BY q.created_at""",
                    (loop_task_id,),
                )

    result: dict[str, list] = {}
    for row in rows:
        chunk_id = row["chunk_id"] or row["section_path"] or "default"
        if chunk_id not in result:
            result[chunk_id] = []
        result[chunk_id].append((row["id"], row["question"]))

    return result


async def _run_single_jump_for_round(
    loop_task_id: str,
    loop_task_name: str,
    round_number: int,
    round_id: str,
    qa_task_id: str,
    env_url: str,
    org_id: str,
    d_user_id: str,
    agent_id: str,
    top_k: int,
    recall_top_k: int,
    concurrency: int,
    cross_chunk: bool,
):
    """Run single-jump test for a round's approved questions."""

    def stop_check():
        ctrl = _loop_controls.get(loop_task_id)
        return ctrl is None or ctrl.get("stop", False)

    # Check stop before starting
    if stop_check():
        return

    # Create single-jump task
    sj_task_id = _id()
    async with get_db() as db:
        await db.execute(
            """INSERT INTO single_jump_task
               (id,name,env_url,org_id,d_user_id,agent_id,top_k,recall_top_k,concurrency,cross_chunk,
                status,progress,total,created_at,hit_top_k)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (sj_task_id, f"{loop_task_name}-单跳测试-第{round_number}轮", env_url, org_id, d_user_id,
             agent_id, top_k, recall_top_k, concurrency, int(cross_chunk), "pending", 0, 0, _now(), top_k),
        )
        await db.execute(
            "UPDATE loop_round SET single_jump_task_id=? WHERE id=?",
            (sj_task_id, round_id),
        )
        await db.commit()

    # Build MD content from approved questions
    # Query approved questions from this QA task
    async with get_db() as db:
        rows = await db.execute_fetchall(
            """SELECT section_path, file_name, file_id, question, reference_answer, chunk_id, chunk_headers
               FROM qa_gen_question
               WHERE task_id=? AND status='approved'
               ORDER BY chunk_headers, created_at""",
            (qa_task_id,),
        )

    if not rows:
        # No approved questions, skip test
        return

    # Check stop before running test
    if stop_check():
        return

    # Group by chunk_headers (use section_path as fallback)
    from collections import defaultdict
    sections_dict: dict[str, list] = defaultdict(list)
    question_chunk_map: dict[str, str] = {}  # question -> chunk_id
    # section_key -> {file_id, file_name} from qa_gen_question
    section_file_info: dict[str, dict] = {}

    for row in rows:
        # Use chunk_headers as the grouping key if available, otherwise use section_path
        section_key = row["chunk_headers"] if row["chunk_headers"] else row["section_path"]
        if not section_key:
            section_key = row["file_name"] or "default"
        sections_dict[section_key].append({
            "question": row["question"],
            "reference_answer": row["reference_answer"],
            "file_name": row["file_name"],
            "chunk_headers": row["chunk_headers"],
            "chunk_id": row["chunk_id"],
        })
        # Build question to chunk_id mapping
        if row["chunk_id"] and row["question"]:
            question_chunk_map[row["question"]] = row["chunk_id"]
        # Remember file info for this section_key (first non-empty file_id wins)
        if row["file_id"] and section_key not in section_file_info:
            section_file_info[section_key] = {
                "file_id": row["file_id"],
                "file_name": row["file_name"] or "",
            }

    # Generate MD（与 HTTP 导出、离线脚本共用 loop_recall_md）
    prebuilt_file_map: dict[str, dict] = {}
    md_lines: list[str] = []

    section_index = 0
    for section_key, items in sections_dict.items():
        section_index += 1
        file_name = (items[0].get("file_name") or "").strip()
        slice_title = (items[0].get("chunk_headers") or "").strip() or section_key

        parsed_section_path = append_recall_md_section(
            md_lines,
            section_index,
            file_name=file_name,
            slice_title=slice_title,
            qa_items=items,
            meta_lines=[DEFAULT_LLM_NOTE],
        )
        finfo = section_file_info.get(section_key)
        if finfo:
            prebuilt_file_map[parsed_section_path] = {
                "file_id": finfo["file_id"],
                "file_name": finfo["file_name"],
                "match_type": "exact",
            }

    md_content = "\n".join(md_lines)

    # Check stop before running test
    if stop_check():
        return

    # Run single-jump test
    from api.single_jump import _run_task

    # Import necessary modules
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent / "sdk"))

    await _run_task(
        task_id=sj_task_id,
        qa_text=md_content,
        env_url=env_url,
        org_id=org_id,
        d_user_id=d_user_id,
        agent_id=agent_id,
        hit_top_k=top_k,
        recall_top_k=recall_top_k,
        concurrency=concurrency,
        cross_chunk=cross_chunk,
        prebuilt_file_map=prebuilt_file_map if prebuilt_file_map else None,
        prebuilt_chunk_map=question_chunk_map if question_chunk_map else None,
    )

    # After test completes, aggregate stats from single_jump_result
    async with get_db() as db:
        # Wait a bit for the test to complete (polling)
        max_wait = 1800  # Max 30 minutes wait for large tasks
        waited = 0
        while waited < max_wait:
            # Check stop during polling
            if stop_check():
                return

            row = await db.execute_fetchall(
                "SELECT status FROM single_jump_task WHERE id=?",
                (sj_task_id,)
            )
            if row and row[0]["status"] in ("done", "failed"):
                break
            await asyncio.sleep(2)
            waited += 2

        # Aggregate stats
        stats_rows = await db.execute_fetchall(
            """SELECT
                COUNT(*) as tested,
                SUM(CASE WHEN error IS NULL AND COALESCE(json_array_length(retrieved), 0) > 0 THEN 1 ELSE 0 END) as recalled,
                SUM(CASE WHEN is_file_hit = 1 THEN 1 ELSE 0 END) as file_hit,
                SUM(CASE WHEN is_chunk_hit = 1 THEN 1 ELSE 0 END) as chunk_hit
            FROM single_jump_result
            WHERE task_id=?""",
            (sj_task_id,)
        )

        if stats_rows:
            stats = dict(stats_rows[0])
            await db.execute(
                """UPDATE loop_round
                   SET tested=?, recalled=?, file_hit=?, chunk_hit=?
                   WHERE id=?""",
                (stats.get("tested") or 0, stats.get("recalled") or 0,
                 stats.get("file_hit") or 0, stats.get("chunk_hit") or 0,
                 round_id),
            )
            await db.commit()


async def _update_loop_stats(loop_task_id: str):
    """Update cumulative stats from all rounds."""
    async with get_db() as db:
        # Aggregate from loop_round
        rows = await db.execute_fetchall(
            """SELECT
                SUM(generated) as total_generated,
                SUM(approved) as total_approved,
                SUM(duplicates) as total_duplicates,
                SUM(tested) as total_tested,
                SUM(recalled) as total_recalled,
                SUM(file_hit) as total_file_hit,
                SUM(chunk_hit) as total_chunk_hit
            FROM loop_round WHERE loop_task_id=?""",
            (loop_task_id,),
        )

        stats = dict(rows[0]) if rows else {}

        # Count file_miss and recall_failed from single_jump_result
        miss_rows = await db.execute_fetchall(
            """SELECT
                SUM(CASE WHEN r.is_file_hit=0 AND COALESCE(json_array_length(r.retrieved), 0)>0 THEN 1 ELSE 0 END) as file_miss,
                SUM(CASE WHEN COALESCE(json_array_length(r.retrieved), 0)=0 AND r.error IS NULL THEN 1 ELSE 0 END) as recall_failed
            FROM single_jump_result r
            JOIN loop_round lr ON r.task_id = lr.single_jump_task_id
            WHERE lr.loop_task_id=?""",
            (loop_task_id,),
        )

        miss_stats = dict(miss_rows[0]) if miss_rows else {}

        await db.execute(
            """UPDATE loop_task SET
                total_generated=?,
                total_approved=?,
                total_duplicates=?,
                total_tested=?,
                total_recalled=?,
                total_file_hit=?,
                total_file_miss=?,
                total_recall_failed=?,
                total_chunk_hit=?
            WHERE id=?""",
            (
                stats.get("total_generated") or 0,
                stats.get("total_approved") or 0,
                stats.get("total_duplicates") or 0,
                stats.get("total_tested") or 0,
                stats.get("total_recalled") or 0,
                stats.get("total_file_hit") or 0,
                miss_stats.get("file_miss") or 0,
                miss_stats.get("recall_failed") or 0,
                stats.get("total_chunk_hit") or 0,
                loop_task_id,
            ),
        )
        await db.commit()


async def recover_orphaned_loops():
    """On startup, set any 'running' loop tasks to 'paused'."""
    async with get_db() as db:
        rows = await db.execute_fetchall(
            "SELECT id FROM loop_task WHERE status='running'"
        )
        for row in rows:
            await db.execute(
                "UPDATE loop_task SET status='paused', paused_at=? WHERE id=?",
                (_now(), row["id"]),
            )
        await db.commit()
