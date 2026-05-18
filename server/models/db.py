import aiosqlite
import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Iterable

DB_PATH = Path(__file__).parent.parent / "data" / "rag_eval.db"
SCHEMA_PATH = Path(__file__).parent / "schema.sql"


from contextlib import asynccontextmanager


@asynccontextmanager
async def get_db():
    """Async context manager that yields a configured aiosqlite connection."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(DB_PATH, timeout=30.0) as db:
        db.row_factory = aiosqlite.Row
        await db.execute("PRAGMA journal_mode=WAL")
        await db.execute("PRAGMA busy_timeout=30000")
        await db.execute("PRAGMA synchronous=NORMAL")
        yield db


async def init_db():
    async with get_db() as db:
        sql = SCHEMA_PATH.read_text(encoding="utf-8")
        await db.executescript(sql)
        await _run_migrations(db)
        await db.commit()


async def _run_migrations(db: aiosqlite.Connection):
    """Apply forward-only lightweight migrations for existing local DBs."""
    await _ensure_columns(
        db,
        "single_jump_result",
        (
            ("file_name", "TEXT"),
            ("match_type", "TEXT"),
            ("is_file_hit", "INTEGER DEFAULT 0"),
            ("expected_chunk_id", "TEXT"),
            ("is_chunk_hit", "INTEGER DEFAULT 0"),
            ("chunk_hit_rank", "INTEGER"),
            ("retrieved_chunk_ids", "TEXT"),
        ),
    )
    await _ensure_columns(
        db,
        "single_jump_task",
        (
            ("progress", "INTEGER DEFAULT 0"),
            ("total", "INTEGER DEFAULT 0"),
            ("error_message", "TEXT"),
            ("finished_at", "TEXT"),
            ("md_content", "TEXT"),
        ),
    )
    # qa_gen tables migration
    await _ensure_columns(
        db,
        "qa_gen_question",
        (
            ("source_chunk", "TEXT"),
            ("quality_score", "REAL"),
            ("quality_detail", "TEXT"),
            ("dup_of", "TEXT"),
            ("dup_similarity", "REAL"),
            ("embedding", "TEXT"),
            ("updated_at", "TEXT"),
            ("file_id", "TEXT"),
            ("file_name", "TEXT"),
            ("chunk_id", "TEXT"),
            ("chunk_headers", "TEXT"),
            ("chunk_content_preview", "TEXT"),
        ),
    )
    await _ensure_columns(
        db,
        "qa_gen_task",
        (
            ("approved", "INTEGER DEFAULT 0"),
        ),
    )
    await _ensure_columns(
        db,
        "loop_round",
        (
            ("dedup_progress", "TEXT"),
        ),
    )
    # multi_hop_gen_task: add new columns for dagent source
    await _ensure_columns(
        db,
        "multi_hop_gen_task",
        (
            ("source", "TEXT NOT NULL DEFAULT 'file'"),
            ("org_id", "TEXT"),
            ("file_ids", "TEXT DEFAULT ''"),
        ),
    )
    # multi_hop_task: add llm_type column
    await _ensure_columns(
        db,
        "multi_hop_task",
        (
            ("judge_config_id", "TEXT DEFAULT ''"),
            ("llm_type", "TEXT DEFAULT 'deepseek_v3'"),
        ),
    )
    # multi_hop_task: add agent_id
    await _ensure_columns(
        db,
        "multi_hop_task",
        (
            ("agent_id", "TEXT DEFAULT ''"),
        ),
    )
    # multi_hop_result: add actual_hops and agent_answer
    await _ensure_columns(
        db,
        "multi_hop_result",
        (
            ("actual_hops", "TEXT DEFAULT '[]'"),
            ("agent_answer", "TEXT DEFAULT ''"),
            ("chunk_hit_count", "INTEGER DEFAULT 0"),
            ("full_chunk_hit", "INTEGER DEFAULT 0"),
            ("partial_chunk_hit", "INTEGER DEFAULT 0"),
        ),
    )
    # multi_hop_gen_task: add prompt_template_id
    await _ensure_columns(
        db,
        "multi_hop_gen_task",
        (
            ("prompt_template_id", "TEXT"),
        ),
    )
    # loop_task: add global_dedup flag
    await _ensure_columns(
        db,
        "loop_task",
        (
            ("global_dedup", "INTEGER DEFAULT 0"),
        ),
    )
    # loop_round: add chunk_hit for chunk-level hit tracking
    await _ensure_columns(
        db,
        "loop_round",
        (
            ("chunk_hit", "INTEGER DEFAULT 0"),
        ),
    )
    # loop_task: add total_chunk_hit for chunk-level aggregation
    await _ensure_columns(
        db,
        "loop_task",
        (
            ("total_chunk_hit", "INTEGER DEFAULT 0"),
        ),
    )
    # single_jump_task: add recall_top_k for unlimited recall results
    await _ensure_columns(
        db,
        "single_jump_task",
        (
            ("recall_top_k", "INTEGER DEFAULT 64"),
            ("hit_top_k", "INTEGER DEFAULT 64"),
        ),
    )
    # single_jump_result: add hit_top_k for chunk hit calculation
    await _ensure_columns(
        db,
        "single_jump_result",
        (
            ("hit_top_k", "INTEGER DEFAULT 64"),
        ),
    )
    # single_jump_result: add raw_chunk_headers for original section title
    await _ensure_columns(
        db,
        "single_jump_result",
        (
            ("raw_chunk_headers", "TEXT"),
        ),
    )
    # loop_task: add recall_top_k for unlimited recall results
    await _ensure_columns(
        db,
        "loop_task",
        (
            ("recall_top_k", "INTEGER DEFAULT 64"),
        ),
    )
    # loop_task: 批次规划中的切片总数，用于校验拉取是否完整（与 chunk_batches_plan.chunk_count 一致）
    await _ensure_columns(
        db,
        "loop_task",
        (
            ("expected_chunk_count", "INTEGER"),
        ),
    )


async def _ensure_columns(
    db: aiosqlite.Connection,
    table_name: str,
    columns: Iterable[tuple[str, str]],
):
    """Ensure table has required columns; add missing ones via ALTER TABLE."""
    rows = await db.execute_fetchall(f"PRAGMA table_info({table_name})")
    existing = {row["name"] for row in rows}
    for column_name, column_def in columns:
        if column_name in existing:
            continue
        await db.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_def}")


def _now() -> str:
    return datetime.utcnow().isoformat()


def _id() -> str:
    return uuid.uuid4().hex
