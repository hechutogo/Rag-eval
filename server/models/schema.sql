-- RAG Eval Framework — SQLite schema
-- server/models/schema.sql

CREATE TABLE IF NOT EXISTS platform_config (
    id         TEXT PRIMARY KEY,
    name       TEXT NOT NULL,
    type       TEXT NOT NULL DEFAULT 'dagent',
    base_url   TEXT NOT NULL,
    org_id     TEXT,
    token      TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS judge_config (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    base_url        TEXT NOT NULL,
    api_key         TEXT NOT NULL,
    model           TEXT NOT NULL,
    embed_base_url  TEXT DEFAULT '',
    embed_api_key   TEXT DEFAULT '',
    embed_model     TEXT DEFAULT 'text-embedding-3-small',
    created_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS eval_dataset (
    id           TEXT PRIMARY KEY,
    name         TEXT NOT NULL,
    description  TEXT,
    sample_count INTEGER DEFAULT 0,
    created_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS eval_sample (
    id                  TEXT PRIMARY KEY,
    dataset_id          TEXT NOT NULL,
    question            TEXT NOT NULL,
    reference_answer    TEXT NOT NULL,
    relevant_chunk_ids  TEXT NOT NULL DEFAULT '[]',
    knowledge_hub_id    TEXT NOT NULL,
    source_file_id      TEXT,
    metadata            TEXT DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS eval_task (
    id                  TEXT PRIMARY KEY,
    name                TEXT,
    dataset_id          TEXT NOT NULL,
    platform_config_id  TEXT NOT NULL,
    judge_config_id     TEXT NOT NULL,
    agent_id            TEXT NOT NULL,
    knowledge_hub_id    TEXT NOT NULL,
    file_id_list        TEXT DEFAULT '[]',
    top_k               INTEGER DEFAULT 10,
    eval_retrieval      INTEGER DEFAULT 1,
    eval_generation     INTEGER DEFAULT 1,
    concurrency         INTEGER DEFAULT 3,
    selected_metrics    TEXT DEFAULT '[]',
    status              TEXT NOT NULL DEFAULT 'pending',
    progress            INTEGER DEFAULT 0,
    total               INTEGER DEFAULT 0,
    error_message       TEXT,
    created_at          TEXT NOT NULL,
    finished_at         TEXT
);

CREATE TABLE IF NOT EXISTS eval_result (
    id                  TEXT PRIMARY KEY,
    task_id             TEXT NOT NULL,
    sample_id           TEXT NOT NULL,
    question            TEXT,
    reference_answer    TEXT,
    retrieved_chunks    TEXT,
    agent_answer        TEXT,
    hit_rate            REAL,
    mrr                 REAL,
    ndcg                REAL,
    context_precision   REAL,
    context_recall      REAL,
    faithfulness        REAL,
    answer_relevance    REAL,
    answer_correctness  REAL,
    groundedness        REAL,
    latency_ms          INTEGER,
    judge_detail        TEXT,
    error               TEXT
);

CREATE TABLE IF NOT EXISTS generate_task (
    id              TEXT PRIMARY KEY,
    dataset_id      TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'pending',
    progress        INTEGER DEFAULT 0,
    total           INTEGER DEFAULT 0,
    error_message   TEXT,
    created_at      TEXT NOT NULL,
    finished_at     TEXT
);

CREATE TABLE IF NOT EXISTS single_jump_task (
    id              TEXT PRIMARY KEY,
    name            TEXT,
    env_url         TEXT NOT NULL,
    org_id          TEXT NOT NULL,
    d_user_id       TEXT DEFAULT 'test',
    agent_id        TEXT DEFAULT '',  -- 用于召回测试的 agent ID
    top_k           INTEGER DEFAULT 64,
    concurrency     INTEGER DEFAULT 5,
    cross_chunk     INTEGER DEFAULT 1,
    status          TEXT NOT NULL DEFAULT 'pending',
    progress        INTEGER DEFAULT 0,
    total           INTEGER DEFAULT 0,
    error_message   TEXT,
    created_at      TEXT NOT NULL,
    finished_at     TEXT
);

CREATE TABLE IF NOT EXISTS single_jump_result (
    id              TEXT PRIMARY KEY,
    task_id         TEXT NOT NULL,
    section_path    TEXT,
    doc_name        TEXT,
    file_id         TEXT,
    file_name       TEXT,
    match_type      TEXT,
    qid             TEXT,
    question        TEXT,
    reference_answer TEXT,
    top_k           INTEGER,
    retrieved       TEXT DEFAULT '[]',
    latency_ms      INTEGER DEFAULT 0,
    error           TEXT,
    best_cosine_sim REAL,
    avg_cosine_sim  REAL,
    is_file_hit     INTEGER DEFAULT 0,
    expected_chunk_id TEXT,          -- 期望命中的切片ID
    is_chunk_hit    INTEGER DEFAULT 0, -- 是否命中切片
    chunk_hit_rank  INTEGER,          -- 切片命中排名
    retrieved_chunk_ids TEXT,         -- JSON数组：召回的所有切片ID
    raw_chunk_headers TEXT            -- 原始切片标题（从元数据解析）
);

-- Indexes for single_jump_result
CREATE INDEX IF NOT EXISTS idx_single_jump_result_task_id ON single_jump_result(task_id);
CREATE INDEX IF NOT EXISTS idx_single_jump_result_section_path ON single_jump_result(section_path);
CREATE INDEX IF NOT EXISTS idx_single_jump_result_is_file_hit ON single_jump_result(is_file_hit);
CREATE INDEX IF NOT EXISTS idx_single_jump_result_error ON single_jump_result(error);
CREATE INDEX IF NOT EXISTS idx_single_jump_result_task_section ON single_jump_result(task_id, section_path);

CREATE TABLE IF NOT EXISTS multi_hop_task (
    id              TEXT PRIMARY KEY,
    name            TEXT,
    env_url         TEXT NOT NULL,
    org_id          TEXT NOT NULL,
    d_user_id       TEXT DEFAULT 'test',
    agent_id        TEXT DEFAULT '',
    judge_config_id TEXT DEFAULT '',
    top_k           INTEGER DEFAULT 10,
    concurrency     INTEGER DEFAULT 5,
    status          TEXT NOT NULL DEFAULT 'pending',
    progress        INTEGER DEFAULT 0,
    total           INTEGER DEFAULT 0,
    error_message   TEXT,
    created_at      TEXT NOT NULL,
    finished_at     TEXT
);

CREATE TABLE IF NOT EXISTS multi_hop_result (
    id              TEXT PRIMARY KEY,
    task_id         TEXT NOT NULL,
    qid             TEXT,
    question        TEXT,
    answer          TEXT,
    type            TEXT,
    top_k           INTEGER,
    hops            TEXT DEFAULT '[]',        -- JSON: [{section_path, file_id, file_name, hit, contribution}]
    actual_hops     TEXT DEFAULT '[]',        -- JSON: [{hop_index, query, retrieved:[{file_id,headers,file_name}]}]
    retrieved       TEXT DEFAULT '[]',        -- JSON: 所有跳合并去重的召回结果（兼容旧逻辑）
    agent_answer    TEXT DEFAULT '',          -- Agent 最终回答
    latency_ms      INTEGER DEFAULT 0,
    error           TEXT,
    best_cosine_sim REAL,
    full_hit        INTEGER DEFAULT 0,
    partial_hit     INTEGER DEFAULT 0,
    hop_count       INTEGER DEFAULT 0,
    hop_hit_count   INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS qa_gen_task (
    id                    TEXT PRIMARY KEY,
    name                  TEXT,
    status                TEXT NOT NULL DEFAULT 'pending',
    judge_config_id       TEXT NOT NULL,
    questions_per_section INTEGER DEFAULT 5,
    quality_threshold     REAL DEFAULT 0.6,
    progress              INTEGER DEFAULT 0,
    total                 INTEGER DEFAULT 0,
    approved              INTEGER DEFAULT 0,
    error_message         TEXT,
    created_at            TEXT NOT NULL,
    finished_at           TEXT
);

CREATE TABLE IF NOT EXISTS qa_gen_question (
    id               TEXT PRIMARY KEY,
    task_id          TEXT NOT NULL,
    section_path     TEXT NOT NULL,
    question         TEXT NOT NULL,
    reference_answer TEXT NOT NULL,
    source_chunk     TEXT,
    quality_score    REAL,
    quality_detail   TEXT,
    dup_of           TEXT,
    dup_similarity   REAL,
    status           TEXT NOT NULL DEFAULT 'pending',
    embedding        TEXT,
    created_at       TEXT NOT NULL,
    updated_at       TEXT,
    file_id          TEXT,
    file_name        TEXT,
    chunk_id         TEXT,           -- 切片ID，用于追踪问题来源的切片
    chunk_headers    TEXT,           -- 切片标题路径
    chunk_content_preview TEXT      -- 切片内容预览（前500字）
);

CREATE TABLE IF NOT EXISTS eval_report (
    id                      TEXT PRIMARY KEY,
    task_id                 TEXT NOT NULL UNIQUE,
    sample_count            INTEGER,
    avg_hit_rate            REAL,
    avg_mrr                 REAL,
    avg_ndcg                REAL,
    avg_context_precision   REAL,
    avg_context_recall      REAL,
    avg_faithfulness        REAL,
    avg_answer_relevance    REAL,
    avg_answer_correctness  REAL,
    avg_groundedness        REAL,
    rag_score               REAL,
    hallucination_rate      REAL,
    interpretation          TEXT,
    created_at              TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS loop_task (
    id                    TEXT PRIMARY KEY,
    name                  TEXT,
    org_id                TEXT NOT NULL,
    judge_config_id       TEXT NOT NULL,
    file_ids              TEXT DEFAULT '',
    questions_per_section INTEGER DEFAULT 5,
    quality_threshold     REAL DEFAULT 0.6,
    include_multimodal    INTEGER DEFAULT 1,
    env_url               TEXT NOT NULL,
    d_user_id             TEXT DEFAULT 'test',
    agent_id              TEXT DEFAULT '',  -- 用于召回测试的 agent ID
    top_k                 INTEGER DEFAULT 64,
    concurrency           INTEGER DEFAULT 20,
    cross_chunk           INTEGER DEFAULT 1,
    status                TEXT NOT NULL DEFAULT 'pending',
    current_round         INTEGER DEFAULT 0,
    max_rounds            INTEGER DEFAULT 0,
    max_questions         INTEGER DEFAULT 0,
    total_generated       INTEGER DEFAULT 0,
    total_approved        INTEGER DEFAULT 0,
    total_duplicates      INTEGER DEFAULT 0,
    total_tested          INTEGER DEFAULT 0,
    total_recalled        INTEGER DEFAULT 0,
    total_file_hit        INTEGER DEFAULT 0,
    total_file_miss       INTEGER DEFAULT 0,
    total_recall_failed   INTEGER DEFAULT 0,
    error_message         TEXT,
    global_dedup          INTEGER DEFAULT 0,  -- 是否全局去重（跨任务）
    expected_chunk_count  INTEGER,            -- 批次规划切片总数，与 chunk_batches_plan.chunk_count 对齐
    created_at            TEXT NOT NULL,
    paused_at             TEXT,
    finished_at           TEXT
);

CREATE TABLE IF NOT EXISTS loop_round (
    id                    TEXT PRIMARY KEY,
    loop_task_id          TEXT NOT NULL,
    round_number          INTEGER NOT NULL,
    qa_gen_task_id        TEXT,
    single_jump_task_id   TEXT,
    status                TEXT NOT NULL DEFAULT 'pending',
    generated             INTEGER DEFAULT 0,
    approved              INTEGER DEFAULT 0,
    duplicates            INTEGER DEFAULT 0,
    tested                INTEGER DEFAULT 0,
    recalled              INTEGER DEFAULT 0,
    file_hit              INTEGER DEFAULT 0,
    dedup_progress        TEXT,
    started_at            TEXT,
    finished_at           TEXT
);

CREATE TABLE IF NOT EXISTS multi_hop_gen_task (
    id                    TEXT PRIMARY KEY,
    name                  TEXT,
    status                TEXT NOT NULL DEFAULT 'pending',
    source                TEXT NOT NULL DEFAULT 'file',   -- 'file' | 'dagent'
    judge_config_id       TEXT NOT NULL,
    org_id                TEXT,
    file_ids              TEXT DEFAULT '',
    hops_per_question     INTEGER DEFAULT 2,
    questions_per_group   INTEGER DEFAULT 3,
    quality_threshold     REAL DEFAULT 0.6,
    progress              INTEGER DEFAULT 0,
    total                 INTEGER DEFAULT 0,
    approved              INTEGER DEFAULT 0,
    error_message         TEXT,
    created_at            TEXT NOT NULL,
    finished_at           TEXT
);

CREATE TABLE IF NOT EXISTS prompt_template (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    description TEXT,
    content     TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    updated_at  TEXT
);

CREATE TABLE IF NOT EXISTS multi_hop_gen_question (
    id               TEXT PRIMARY KEY,
    task_id          TEXT NOT NULL,
    qid              TEXT,
    question         TEXT NOT NULL,
    answer           TEXT NOT NULL,
    type             TEXT DEFAULT 'reasoning',
    hops             TEXT DEFAULT '[]',
    source_sections  TEXT DEFAULT '[]',
    quality_score    REAL,
    quality_detail   TEXT,
    status           TEXT NOT NULL DEFAULT 'pending',
    created_at       TEXT NOT NULL,
    updated_at       TEXT
);
