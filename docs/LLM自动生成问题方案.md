# LLM 自动生成问题 + 测试 + 审核方案

**版本：** v1.0  
**日期：** 2026-04-21  
**目标：** 基于知识库 MD 文件，自动生成测试问题，经过查重和质量审核后，直接送入单跳召回测试

---

## 一、整体流程

```
┌──────────────┐
│ 上传 MD 文件  │
└──────┬───────┘
       ↓
┌──────────────────────────┐
│ LLM 按章节生成 Q&A        │
│ - 每个 section 生成 N 个   │
│ - 同时生成参考答案         │
│ - 记录答案来源原文片段     │
└──────┬───────────────────┘
       ↓
┌─────────────────────────────────┐
│         审核流程                 │
│  ┌─────────────────────────┐   │
│  │ 1. 批次内查重            │   │
│  │    - 精确查重（hash）     │   │
│  │    - 语义查重（embedding）│   │
│  └─────────────────────────┘   │
│  ┌─────────────────────────┐   │
│  │ 2. 跨历史问题库查重       │   │
│  │    - 与已审核问题对比     │   │
│  └─────────────────────────┘   │
│  ┌─────────────────────────┐   │
│  │ 3. 问题质量自动评分       │   │
│  │    - 可回答性            │   │
│  │    - 问题清晰度          │   │
│  │    - 答案准确性          │   │
│  │    - 独特性              │   │
│  └─────────────────────────┘   │
│  ┌─────────────────────────┐   │
│  │ 4. 人工确认/编辑/删除     │   │
│  │    - 自动通过高质量问题   │   │
│  │    - 标记低质量/重复问题  │   │
│  └─────────────────────────┘   │
└─────────┬───────────────────────┘
          ↓
┌──────────────────────────┐
│ 导出为标准 MD 格式        │
│ (与现有单跳测试格式一致)  │
└──────┬───────────────────┘
       ↓
┌──────────────────────────┐
│ 直接送入单跳召回测试      │
└──────────────────────────┘
```

---

## 二、模块设计

### 2.1 生成模块（`/api/qa-gen`）

#### API 设计

```
POST   /api/qa-gen/task                    # 创建生成任务
GET    /api/qa-gen/task/list               # 任务列表
GET    /api/qa-gen/task/{id}               # 任务详情（含进度）
DELETE /api/qa-gen/task/{id}               # 删除任务
GET    /api/qa-gen/task/{id}/questions     # 获取生成的问题列表
POST   /api/qa-gen/question/{id}/approve   # 通过问题
POST   /api/qa-gen/question/{id}/reject    # 拒绝问题
PUT    /api/qa-gen/question/{id}           # 编辑问题
POST   /api/qa-gen/task/{id}/export-md     # 导出已通过问题为 MD
```

#### 生成策略

**输入：**
- MD 文件（与单跳测试相同格式）
- 配置参数：
  - `model`: LLM 模型（默认 gpt-4o-mini）
  - `questions_per_section`: 每章节生成问题数（默认 5）
  - `quality_threshold`: 质量阈值（默认 0.6）
  - `judge_config_id`: 评分模型配置

**处理流程：**
1. 按 `## section` 切分文档
2. 对每个 section：
   - 提取章节标题和内容
   - 调用 LLM 生成 N 个问题
   - 每个问题包含：
     - 问题文本
     - 参考答案
     - 答案来源原文片段（用于质量审核）
3. 后台异步执行，支持进度回调

**Prompt 模板：**

```
你是一个专业的技术文档测试问题生成专家。

任务：根据以下技术文档章节内容，生成 {N} 个测试问题。

章节标题：{section_path}
章节内容：
{content}

要求：
1. 问题必须能从该章节内容直接回答（不要生成需要跨文档才能回答的问题）
2. 问题应覆盖章节的关键知识点
3. 问题表述清晰，无歧义
4. 答案准确，与原文一致
5. 标注答案来源的原文片段（用于后续审核）

输出格式（JSON）：
[
  {
    "question": "问题文本",
    "answer": "参考答案",
    "source_chunk": "答案来源的原文片段（50-200字）"
  },
  ...
]
```

---

### 2.2 查重模块

#### 两层查重机制

| 层级 | 方法 | 阈值 | 说明 |
|------|------|------|------|
| **精确查重** | 问题文本 hash | 完全相同 | 快速过滤完全重复 |
| **语义查重** | embedding 余弦相似度 | > 0.92 | 识别语义相似问题 |

#### 查重范围

1. **批次内查重**：当前生成任务内的问题互相查重
2. **跨历史查重**：与 `qa_approved_question` 表中已审核通过的问题查重

#### 实现细节

**Embedding 计算：**
- 使用 `text-embedding-3-small` 或配置的 embedding 模型
- 问题生成后立即计算 embedding 并存储
- embedding 存储为 JSON 字符串（1536 维向量）

**查重流程：**
```python
# 1. 精确查重
question_hash = hashlib.md5(question.strip().lower().encode()).hexdigest()
if question_hash in existing_hashes:
    mark_as_duplicate()

# 2. 语义查重
question_embedding = get_embedding(question)
similarities = cosine_similarity(question_embedding, all_embeddings)
if max(similarities) > 0.92:
    mark_as_similar(most_similar_question_id)
```

---

### 2.3 质量审核模块

#### 自动质量评分

每条生成的问题自动打分（0-1），综合以下维度：

| 维度 | 权重 | 评分方法 |
|------|------|---------|
| **可回答性** | 30% | LLM 判断：答案是否能从 source_chunk 推导出 |
| **问题清晰度** | 25% | LLM 判断：问题是否有歧义、表述是否清晰 |
| **答案准确性** | 30% | LLM 判断：参考答案是否与 source_chunk 一致 |
| **独特性** | 15% | 计算：与最相似问题的语义距离（1 - max_similarity） |

**质量评分 Prompt：**

```
评估以下测试问题的质量，从 0-1 打分。

问题：{question}
参考答案：{answer}
答案来源原文：{source_chunk}

评估维度：
1. 可回答性（0-1）：答案是否能从原文推导出？
2. 问题清晰度（0-1）：问题是否清晰无歧义？
3. 答案准确性（0-1）：参考答案是否与原文一致？

输出格式（JSON）：
{
  "answerable": 0.9,
  "clarity": 0.85,
  "accuracy": 0.95,
  "reasoning": "简短说明"
}
```

#### 审核状态流转

```
pending（待审核）
    ↓
    ├─→ approved（通过）→ 进入 qa_approved_question 表
    ├─→ rejected（拒绝）→ 不进入测试
    └─→ edited（编辑后）→ 重新计算 embedding 和质量分
```

**自动通过规则：**
- `quality_score >= threshold`（默认 0.6）
- 且 `dup_of IS NULL`（非重复）
- 自动标记为 `approved`

**需人工审核：**
- `quality_score < threshold`
- 或 `dup_of IS NOT NULL`（疑似重复）

---

### 2.4 数据库设计

#### 新增表

```sql
-- 生成任务表
CREATE TABLE qa_gen_task (
    id              TEXT PRIMARY KEY,
    name            TEXT,
    status          TEXT NOT NULL DEFAULT 'pending',  -- pending/running/done/failed
    model           TEXT NOT NULL,                    -- 使用的 LLM 模型
    judge_config_id TEXT,                             -- 评分模型配置
    questions_per_section INTEGER DEFAULT 5,
    quality_threshold     REAL DEFAULT 0.6,
    progress        INTEGER DEFAULT 0,
    total           INTEGER DEFAULT 0,
    error_message   TEXT,
    created_at      TEXT NOT NULL,
    finished_at     TEXT
);

-- 生成的问题表（待审核池）
CREATE TABLE qa_gen_question (
    id                TEXT PRIMARY KEY,
    task_id           TEXT NOT NULL,
    section_path      TEXT NOT NULL,
    question          TEXT NOT NULL,
    reference_answer  TEXT NOT NULL,
    source_chunk      TEXT,                -- 答案来源原文片段
    quality_score     REAL,                -- 自动质量评分（0-1）
    quality_detail    TEXT,                -- JSON: {answerable, clarity, accuracy, reasoning}
    dup_of            TEXT,                -- 重复问题的 id（如果是重复的）
    dup_similarity    REAL,                -- 与重复问题的相似度
    status            TEXT NOT NULL DEFAULT 'pending',  -- pending/approved/rejected/edited
    embedding         TEXT,                -- JSON 向量，用于查重
    created_at        TEXT NOT NULL,
    updated_at        TEXT
);

-- 已审核通过的问题库（用于查重基准 + 导出测试）
CREATE TABLE qa_approved_question (
    id                TEXT PRIMARY KEY,
    gen_question_id   TEXT NOT NULL,      -- 关联 qa_gen_question.id
    section_path      TEXT NOT NULL,
    question          TEXT NOT NULL,
    reference_answer  TEXT NOT NULL,
    embedding         TEXT NOT NULL,       -- 用于后续查重
    source_task_id    TEXT NOT NULL,
    quality_score     REAL,
    approved_at       TEXT NOT NULL,
    approved_by       TEXT DEFAULT 'auto' -- auto/manual
);

-- 索引
CREATE INDEX idx_qa_gen_question_task_id ON qa_gen_question(task_id);
CREATE INDEX idx_qa_gen_question_status ON qa_gen_question(status);
CREATE INDEX idx_qa_approved_question_section ON qa_approved_question(section_path);
```

---

## 三、前端设计

### 3.1 页面结构

新增"问题生成"一级菜单，包含两个子页面：

```
问题生成
  ├─ 生成任务
  └─ 问题审核
```

---

### 3.2 生成任务页

**布局：** 类似单跳测试的任务列表页

**功能：**
- 上传 MD 文件
- 配置生成参数：
  - 模型选择（下拉）
  - 每章节问题数（数字输入，默认 5）
  - 质量阈值（滑块，0-1，默认 0.6）
  - 评分模型配置（下拉，复用 judge_config）
- 任务列表：
  - 任务名称、状态、进度、创建时间
  - 操作：查看问题、删除任务

**任务状态展示：**
```
┌────────────────────────────────────────────────────┐
│ 任务名称：evb_linux_development                     │
│ 状态：运行中  进度：45/107 章节                      │
│ 已生成：225 个问题  自动通过：180  待审核：45        │
│ [查看问题] [停止任务]                               │
└────────────────────────────────────────────────────┘
```

---

### 3.3 问题审核页（核心交互）

**布局：** 左右分栏

```
┌─────────────────────────────────────────────────────────────┐
│  筛选：[全部] [待审核] [重复] [低质量] [已通过] [已拒绝]      │
│  任务：[下拉选择任务]                                         │
├──────────┬──────────────────────────────────────────────────┤
│          │  批量操作：[全部通过] [通过高质量(>0.6)] [导出MD]  │
│          ├──────────────────────────────────────────────────┤
│  章节列表 │  问题列表                                         │
│          │  ┌────────────────────────────────────────────┐  │
│  □ 全选   │  │ ✅ Q1: 如何配置 DDR 参数？  质量分: 0.85   │  │
│  □ ch1   │  │    A: 通过修改 xxx 配置文件...              │  │
│  (12/15) │  │    来源: linux_development/ddr/config       │  │
│          │  │    [通过] [拒绝] [编辑]                     │  │
│  □ ch2   │  └────────────────────────────────────────────┘  │
│  (8/10)  │  ┌────────────────────────────────────────────┐  │
│          │  │ ⚠️ Q2: DDR 配置文件在哪？  质量分: 0.45     │  │
│  □ ch3   │  │    A: 在 /etc/ddr.conf                     │  │
│  (5/8)   │  │    ⚠️ 与"Q1"相似度 0.94（疑似重复）         │  │
│          │  │    [通过] [拒绝] [编辑] [查看原问题]        │  │
│          │  └────────────────────────────────────────────┘  │
│          │  ┌────────────────────────────────────────────┐  │
│          │  │ ❌ Q3: xxx？  质量分: 0.32                  │  │
│          │  │    A: xxx                                  │  │
│          │  │    ⚠️ 低质量：问题不清晰                    │  │
│          │  │    [通过] [拒绝] [编辑]                     │  │
│          │  └────────────────────────────────────────────┘  │
└──────────┴──────────────────────────────────────────────────┘
```

**交互细节：**

1. **问题卡片状态标识：**
   - ✅ 绿色：已通过（quality_score >= threshold 且非重复）
   - ⚠️ 黄色：待审核（低质量或疑似重复）
   - ❌ 红色：已拒绝

2. **批量操作：**
   - "全部通过"：将当前筛选结果中所有 pending 问题标记为 approved
   - "通过高质量"：仅通过 quality_score >= threshold 且非重复的问题
   - "导出 MD"：导出已通过问题为标准 MD 格式

3. **编辑问题：**
   - 弹出对话框，可修改问题、答案
   - 保存后重新计算 embedding 和质量分
   - 状态变为 `edited`

4. **查看原问题：**
   - 点击"查看原问题"跳转到重复问题的卡片
   - 高亮显示相似部分

---

### 3.4 导出 MD 格式

导出的 MD 文件格式与单跳测试输入格式完全一致：

```markdown
## section_path / doc_name

## Q1: 问题文本
**A1:** 参考答案

## Q2: 问题文本
**A2:** 参考答案

---

## section_path2 / doc_name2

## Q1: 问题文本
**A1:** 参考答案
```

导出后可直接上传到"单跳召回测试"模块进行测试。

---

## 四、实现优先级

### P0（核心功能，1-2 周）

| 模块 | 功能 | 工作量 |
|------|------|--------|
| 后端 | 生成任务 API（上传 MD → LLM 生成 Q&A → 存库） | 1-2 天 |
| 后端 | 问题列表 API + 通过/拒绝/编辑 API | 0.5 天 |
| 后端 | 导出 MD API | 0.5 天 |
| 前端 | 生成任务页（上传 + 配置 + 任务列表） | 1 天 |
| 前端 | 问题审核页（列表 + 基础交互） | 1-2 天 |
| 数据库 | 新增 3 张表 + schema 迁移 | 0.5 天 |

### P1（查重 + 质量评分，1 周）

| 模块 | 功能 | 工作量 |
|------|------|--------|
| 后端 | 批次内查重（hash + embedding） | 1 天 |
| 后端 | 质量自动评分（LLM 评分） | 1 天 |
| 前端 | 问题卡片状态标识（质量分、重复标记） | 0.5 天 |
| 前端 | 批量操作（全部通过、通过高质量） | 0.5 天 |

### P2（跨历史查重 + 优化，3-5 天）

| 模块 | 功能 | 工作量 |
|------|------|--------|
| 后端 | 跨历史问题库查重 | 0.5 天 |
| 前端 | 查看原问题跳转 | 0.5 天 |
| 前端 | 编辑问题对话框 | 0.5 天 |
| 优化 | embedding 批量计算优化 | 0.5 天 |
| 优化 | 生成任务并发控制 | 0.5 天 |

---

## 五、技术选型

### LLM 模型

| 用途 | 推荐模型 | 备选 |
|------|---------|------|
| 问题生成 | gpt-4o-mini | gpt-4o, claude-3.5-sonnet |
| 质量评分 | gpt-4o-mini | gpt-4o |
| Embedding | text-embedding-3-small | text-embedding-3-large |

### 依赖库

- **后端：** 复用现有 `judge_config` 表的 OpenAI 配置
- **Embedding：** 使用 OpenAI SDK 或 `sentence-transformers`（如果需要本地部署）
- **相似度计算：** `numpy.dot` + `numpy.linalg.norm`（余弦相似度）

---

## 六、风险与注意事项

### 6.1 成本控制

- **问题生成：** 每个 section 约 500-2000 tokens 输入，生成 5 个问题约 500 tokens 输出
  - 估算：12,000 条问题（2,400 sections × 5）≈ 3M tokens input + 1M tokens output
  - 成本（gpt-4o-mini）：约 $0.6
- **质量评分：** 每个问题约 300 tokens 输入 + 100 tokens 输出
  - 估算：12,000 条问题 ≈ 3.6M tokens input + 1.2M tokens output
  - 成本（gpt-4o-mini）：约 $0.7
- **Embedding：** 每个问题约 20 tokens
  - 估算：12,000 条问题 ≈ 240K tokens
  - 成本（text-embedding-3-small）：约 $0.005

**总成本：** 约 $1.3 / 12,000 条问题

### 6.2 性能优化

- **并发控制：** 生成任务使用 `asyncio.Semaphore` 限制并发数（默认 5）
- **批量 embedding：** 每次最多 100 个问题批量计算 embedding
- **查重优化：** 使用 numpy 向量化计算，避免循环

### 6.3 数据一致性

- **事务保护：** 问题通过/拒绝操作使用数据库事务
- **幂等性：** 重复提交生成任务时检查是否已存在相同任务

---

## 七、后续扩展

### 7.1 高级功能

- **问题难度分级：** 自动标注问题难度（简单/中等/困难）
- **知识点标签：** 自动提取问题涉及的知识点标签
- **多轮对话问题：** 生成需要多轮交互的复杂问题
- **负样本生成：** 生成故意错误的答案，用于测试模型鲁棒性

### 7.2 集成优化

- **与单跳测试联动：** 审核通过后自动创建单跳测试任务
- **测试结果反馈：** 单跳测试失败的问题自动标记为"需优化"
- **持续迭代：** 根据测试结果自动调整生成策略

---

## 八、总结

本方案提供了一个完整的"生成 → 查重 → 审核 → 测试"闭环，核心优势：

1. **自动化程度高：** 90% 的高质量问题可自动通过，人工仅需审核 10%
2. **质量可控：** 多维度质量评分 + 查重机制保证问题质量
3. **无缝集成：** 导出格式与现有单跳测试完全兼容
4. **可扩展性强：** 模块化设计，易于后续扩展

**预期效果：** 将问题生成效率提升 10 倍，从人工编写 1 小时 10 条问题，提升到 LLM 生成 1 小时 1000+ 条问题（含审核）。
