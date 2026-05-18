# RAG 评测框架设计文档

> 版本：v1.0  
> 日期：2026-04-13  
> 背景：为 dagent agent 平台设计的独立 RAG 评测框架

---

## 一、背景与目标

### 为什么做成独立框架

dagent 平台已具备完整的 RAG 能力（知识库切片、向量检索、ReAct Agent），但缺乏系统性的评测手段。将评测能力做成**独立框架**而非嵌入现有 backend，原因如下：

- **平台无关**：通过标准化 Adapter 接口，可评测任何 RAG 系统，不只是 dagent
- **独立部署**：不影响生产服务，可单独扩缩容，评测任务不占用业务资源
- **技术栈自由**：可选最适合评测场景的工具和模型
- **可复用**：其他项目也能接入使用

### 目标

1. 提供**检索层**和**生成层**的完整评测指标体系
2. 支持通过 **Python SDK** 集成到 CI/CD 流程
3. 提供 **Web UI** 供非技术人员操作和查看报告
4. 对接 dagent 平台，同时保持对其他平台的扩展能力

---

## 二、评测指标体系

### 2.1 检索层评测（Retrieval Evaluation）

评测知识库切片的召回质量，**不依赖 LLM**，纯计算指标。

| 指标 | 全称 | 说明 | 计算方式 |
|------|------|------|----------|
| **Hit Rate@K** | 命中率 | Top-K 结果中是否包含至少一个相关切片 | 二值判断，对所有样本取均值 |
| **MRR@K** | Mean Reciprocal Rank | 第一个相关切片排名的倒数均值 | `MRR = mean(1 / rank_i)`，rank_i 为第一个相关切片的位置 |
| **NDCG@K** | Normalized Discounted Cumulative Gain | 考虑排名权重的相关性得分，最全面的检索指标 | `NDCG = DCG / IDCG`，DCG 对高排名相关结果给予更高权重 |
| **Context Precision** | 上下文精确率 | 召回的切片中有多少是真正相关的（信噪比） | LLM-as-judge 判断每个召回切片是否相关 |
| **Context Recall** | 上下文召回率 | 回答所需信息有多少被召回覆盖 | LLM 将参考答案分解为原子声明，检查每条声明是否被召回内容覆盖 |

**指标公式**

```
Hit Rate@K = (1/|Q|) * Σ 1[∃ relevant chunk in top-K results]

MRR@K = (1/|Q|) * Σ (1 / rank_i)
  rank_i = position of first relevant chunk for query i

DCG@K = Σ_{i=1}^{K} rel_i / log2(i+1)
NDCG@K = DCG@K / IDCG@K
  IDCG = DCG of ideal (perfect) ranking

Context Precision = |relevant ∩ retrieved| / |retrieved|
Context Recall = |ground truth claims covered by context| / |total ground truth claims|
```

### 2.2 生成层评测（Generation Evaluation）

评测 Agent 基于召回内容的回复质量，**依赖 LLM Judge**。

| 指标 | 说明 | 计算方式 | 是否需要参考答案 |
|------|------|----------|-----------------|
| **Faithfulness（忠实度）** | 回答中每个声明是否都有召回内容支撑，无幻觉 | LLM 分解答案为原子声明 → 逐条判断是否可从 context 推导 → 支持数/总数 | 否 |
| **Answer Relevance（答案相关性）** | 回答是否切题，有没有答非所问 | LLM 从答案反向生成问题 → 与原问题做 Embedding 相似度 | 否 |
| **Answer Correctness（答案正确性）** | 回答与标准答案的事实一致程度 | LLM judge 评分 + Embedding 相似度加权 | 是 |
| **Groundedness（可溯源性）** | 回答中每个声明是否可追溯到具体切片 | LLM-as-judge，带 chain-of-thought | 否 |

**Faithfulness 计算原理（最重要的指标）**

```
1. LLM 将 answer 分解为原子声明列表
   例："答案：北京是中国首都，人口约2200万"
   → ["北京是中国首都", "北京人口约2200万"]

2. 对每条声明，LLM 判断：能否从 retrieved context 中推导出来？
   → [True, False]  （第二条无法从 context 推导 = 幻觉）

3. Faithfulness = 支持的声明数 / 总声明数 = 1/2 = 0.5
```

### 2.3 端到端综合指标

| 指标 | 计算方式 | 说明 |
|------|----------|------|
| **RAG Score** | 调和均值(Faithfulness, Answer Relevance, Context Precision, Context Recall) | 综合评分，任一短板都会拉低总分 |
| **Hallucination Rate** | 含幻觉样本数 / 总样本数（Faithfulness < 阈值） | 幻觉发生率 |

---

## 三、系统架构

### 3.1 整体架构

```
┌─────────────────────────────────────────────────────────────────┐
│                      RAG Eval Framework                          │
│                                                                 │
│  ┌──────────────┐    ┌──────────────────┐    ┌───────────────┐  │
│  │  Python SDK  │    │  FastAPI Server  │    │  React Web UI │  │
│  │  (核心逻辑)   │ ←→ │  (REST API)      │ ←→ │  (可视化报告)  │  │
│  │  CLI 支持    │    │  任务队列         │    │  测试集管理    │  │
│  └──────────────┘    └──────────────────┘    └───────────────┘  │
│          ↓                    ↓                                  │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │                    核心模块                               │   │
│  │  Adapters  │  Evaluators  │  LLM Judge  │  Dataset Gen   │   │
│  └──────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
                    ↕ HTTP API（标准化 Adapter 接口）
┌─────────────────────────────────────────────────────────────────┐
│         dagent platform  /  任何其他 RAG 系统                     │
└─────────────────────────────────────────────────────────────────┘
```

### 3.2 数据流

```
测试集 (question + relevant_chunk_ids + reference_answer)
         ↓
    EvalRunner.run(dataset, agent_id, knowledge_hub_id)
         ↓
    ┌────────────────────────────────────────────────────┐
    │  for each sample:                                  │
    │                                                    │
    │  Step 1: adapter.retrieve(question)                │
    │    → 获取 Top-K 召回切片                            │
    │    → 计算 Hit Rate / MRR / NDCG（与标注对比）       │
    │                                                    │
    │  Step 2: adapter.chat(question)                    │
    │    → 获取 Agent 回复 + 引用切片                     │
    │    → judge.score_faithfulness(answer, context)     │
    │    → judge.score_relevance(question, answer)       │
    │    → judge.score_correctness(answer, reference)    │
    └────────────────────────────────────────────────────┘
         ↓
    EvalReport（每条样本详情 + 汇总统计 + 趋势对比）
```

---

## 四、项目结构

```
rag-eval/
├── sdk/                                # Python SDK（核心）
│   ├── rag_eval/
│   │   ├── __init__.py
│   │   ├── runner.py                   # 评测任务执行器（入口）
│   │   ├── adapters/                   # 平台适配器
│   │   │   ├── base.py                 # 抽象接口定义
│   │   │   └── dagent.py               # dagent 适配器实现
│   │   ├── evaluators/                 # 评测器
│   │   │   ├── retrieval.py            # 检索层：Hit Rate / MRR / NDCG
│   │   │   └── generation.py           # 生成层：Faithfulness / Relevance / Correctness
│   │   ├── judge/                      # LLM Judge
│   │   │   ├── base.py                 # 抽象接口
│   │   │   └── openai_compatible.py    # 兼容 DeepSeek / Qwen / OpenAI
│   │   ├── dataset/                    # 测试集管理
│   │   │   ├── schema.py               # 数据结构定义（Pydantic）
│   │   │   └── generator.py            # LLM 自动生成测试集
│   │   └── report.py                   # 报告生成与格式化
│   ├── pyproject.toml
│   └── README.md
│
├── server/                             # FastAPI 后端
│   ├── main.py
│   ├── api/
│   │   ├── dataset.py                  # 测试集 CRUD
│   │   ├── task.py                     # 评测任务管理
│   │   ├── report.py                   # 报告查询
│   │   └── config.py                   # 平台连接 & Judge 配置
│   ├── service/
│   │   ├── task_service.py
│   │   └── report_service.py
│   ├── models/                         # 数据库模型（SQLite / PostgreSQL）
│   │   └── schema.sql
│   └── requirements.txt
│
├── frontend/                           # React 前端
│   ├── src/
│   │   ├── pages/
│   │   │   ├── Dataset/                # 测试集管理（上传/生成/标注）
│   │   │   ├── Task/                   # 评测任务（配置/提交/进度）
│   │   │   └── Report/                 # 报告 & 可视化（雷达图/趋势图）
│   │   └── components/
│   └── package.json
│
└── docker-compose.yml                  # 一键部署
```

---

## 五、核心接口设计

### 5.1 Adapter 抽象接口

```python
# sdk/rag_eval/adapters/base.py

from abc import ABC, abstractmethod
from dataclasses import dataclass

@dataclass
class RetrievedChunk:
    chunk_id: str
    content: str
    score: float          # 相似度分数
    headers: str          # 所属章节标题
    file_id: str

@dataclass
class AgentResponse:
    answer: str
    retrieved_chunks: list[RetrievedChunk]   # Agent 实际使用的切片
    latency_ms: int

class RAGAdapter(ABC):
    """
    任何 RAG 平台都需要实现这两个方法。
    框架通过此接口与平台交互，不依赖平台内部实现。
    """

    @abstractmethod
    async def retrieve(
        self,
        query: str,
        knowledge_hub_id: str,
        top_k: int = 10,
        **kwargs
    ) -> list[RetrievedChunk]:
        """调用平台检索接口，返回召回的切片列表"""
        ...

    @abstractmethod
    async def chat(
        self,
        query: str,
        agent_id: str,
        **kwargs
    ) -> AgentResponse:
        """调用平台 Agent 对话接口，返回回复和引用的切片"""
        ...
```

### 5.2 dagent 适配器

```python
# sdk/rag_eval/adapters/dagent.py

class DagentAdapter(RAGAdapter):
    """
    对接 dagent 平台的适配器。
    通过 HTTP API 调用，不依赖 dagent 内部代码。
    """

    def __init__(self, base_url: str, org_id: str, token: str):
        self.base_url = base_url
        self.org_id = org_id
        self.headers = {"Authorization": f"Bearer {token}"}

    async def retrieve(self, query, knowledge_hub_id, top_k=10, **kwargs):
        # 调用 dagent 知识库检索接口
        # POST /dagent/knowledge/retrieve
        async with aiohttp.ClientSession() as session:
            resp = await session.post(
                f"{self.base_url}/dagent/knowledge/retrieve",
                json={"query": query, "knowledge_hub_id": knowledge_hub_id,
                      "top_k": top_k, "org_id": self.org_id},
                headers=self.headers
            )
            data = await resp.json()
        return [RetrievedChunk(**chunk) for chunk in data["chunks"]]

    async def chat(self, query, agent_id, **kwargs):
        # 调用 dagent Agent 对话接口（SSE 流式，解析完整回复）
        # POST /dagent/agent/chat
        ...
```

### 5.3 LLM Judge

```python
# sdk/rag_eval/judge/openai_compatible.py

class OpenAICompatibleJudge(LLMJudge):
    """
    兼容所有 OpenAI 协议的模型：DeepSeek / Qwen / OpenAI / Azure OpenAI
    评判逻辑使用中文 prompt，适合中文 RAG 场景
    """

    def __init__(self, base_url: str, api_key: str, model: str):
        self.client = AsyncOpenAI(base_url=base_url, api_key=api_key)
        self.model = model

    async def score_faithfulness(self, answer: str, context: list[str]) -> float:
        """
        原理：
        1. 让 LLM 把 answer 分解为原子声明列表
        2. 对每条声明，判断是否可从 context 推导
        3. 返回 支持声明数 / 总声明数
        """
        context_text = "\n\n".join(context)

        # Step 1: 分解为原子声明
        decompose_prompt = f"""
请将以下回答分解为独立的原子声明列表，每条声明是一个不可再分的事实陈述。
回答：{answer}
输出格式：JSON 数组，如 ["声明1", "声明2", ...]
"""
        claims = await self._call_json(decompose_prompt)

        # Step 2: 逐条判断是否有 context 支撑
        supported = 0
        for claim in claims:
            verify_prompt = f"""
参考资料：
{context_text}

声明：{claim}

问题：上述声明是否可以从参考资料中推导出来？
只回答 yes 或 no。
"""
            result = await self._call(verify_prompt)
            if "yes" in result.lower():
                supported += 1

        return supported / len(claims) if claims else 0.0

    async def score_relevance(self, question: str, answer: str) -> float:
        """
        原理：
        1. 让 LLM 从 answer 反向生成 N 个问题
        2. 计算这些问题与原 question 的 Embedding 相似度
        3. 返回均值
        """
        ...

    async def score_correctness(self, answer: str, reference: str) -> float:
        """
        原理：LLM 对比 answer 和 reference，给出 0-1 分数
        """
        prompt = f"""
请评估以下回答与参考答案的事实一致程度，给出 0 到 1 之间的分数。
1.0 = 完全一致，0.0 = 完全错误或无关。

参考答案：{reference}
待评估回答：{answer}

只输出一个 0 到 1 之间的小数。
"""
        result = await self._call(prompt)
        return float(result.strip())
```

### 5.4 测试集数据结构

```python
# sdk/rag_eval/dataset/schema.py

@dataclass
class EvalSample:
    id: str
    question: str                        # 测试问题
    reference_answer: str                # 标准参考答案
    relevant_chunk_ids: list[str]        # 标注的相关切片 ID（用于检索层评测）
    knowledge_hub_id: str                # 所属知识库
    source_file_id: str | None = None    # 来源文件（可选）
    metadata: dict = field(default_factory=dict)

@dataclass
class EvalDataset:
    id: str
    name: str
    description: str
    samples: list[EvalSample]
    created_at: datetime
```

### 5.5 SDK 使用示例

```python
from rag_eval import EvalRunner
from rag_eval.adapters import DagentAdapter
from rag_eval.judge import OpenAICompatibleJudge

# 配置适配器（对接 dagent）
adapter = DagentAdapter(
    base_url="http://dagent-backend:8000",
    org_id="org_xxx",
    token="your-token"
)

# 配置 LLM Judge（独立于 dagent，使用 DeepSeek）
judge = OpenAICompatibleJudge(
    base_url="https://api.deepseek.com/v1",
    api_key="sk-xxx",
    model="deepseek-chat"
)

# 运行评测
runner = EvalRunner(adapter=adapter, judge=judge)
report = await runner.run(
    dataset="./my_dataset.json",
    agent_id="agent_xxx",
    knowledge_hub_id="hub_xxx",
    top_k=10,
)

# 查看结果
print(report.summary())
# ┌─────────────────────────────────────────┐
# │           评测报告摘要                    │
# ├──────────────────────┬──────────────────┤
# │ 样本数               │ 200              │
# │ Hit Rate@10          │ 0.87             │
# │ MRR@10               │ 0.72             │
# │ NDCG@10              │ 0.81             │
# │ Context Precision    │ 0.76             │
# │ Context Recall       │ 0.83             │
# │ Faithfulness         │ 0.91             │
# │ Answer Relevance     │ 0.88             │
# │ Answer Correctness   │ 0.79             │
# │ RAG Score            │ 0.84             │
# │ Hallucination Rate   │ 4.5%             │
# └──────────────────────┴──────────────────┘

report.save("./eval_report_20260413.json")
```

---

## 六、测试集构建方案

### 6.1 数据结构

每条测试样本：
```json
{
  "id": "sample_001",
  "question": "什么是向量数据库？",
  "reference_answer": "向量数据库是专门存储和检索高维向量的数据库系统...",
  "relevant_chunk_ids": ["chunk_abc123", "chunk_def456"],
  "knowledge_hub_id": "hub_xxx",
  "source_file_id": "file_yyy"
}
```

### 6.2 构建方式

**方式 A：LLM 自动生成（推荐先用）**

```python
from rag_eval.dataset import DatasetGenerator

generator = DatasetGenerator(judge=judge, adapter=adapter)
dataset = await generator.generate(
    knowledge_hub_id="hub_xxx",
    questions_per_chunk=2,
    question_types=["factual", "reasoning", "comparison", "unanswerable"]
)
# 自动生成问题 + 参考答案 + 标注 relevant_chunk_ids
```

原理：
1. 遍历知识库中所有切片
2. 对每个切片，用 LLM 生成 2-3 个不同类型的问题
3. 用 LLM 基于切片内容生成参考答案
4. 自动标注 `relevant_chunk_ids`（生成来源切片）
5. 建议人工抽检 10-20% 过滤低质量样本

**方式 B：人工标注（质量最高）**

通过 Web UI 提供标注界面：
- 输入问题
- 搜索并标注相关切片
- 填写参考答案

**问题类型覆盖建议**

| 类型 | 示例 | 占比建议 |
|------|------|----------|
| 事实查询 | "X 是什么？" | 40% |
| 多跳推理 | "X 和 Y 的关系是？" | 20% |
| 比较 | "X 和 Y 有什么区别？" | 20% |
| 不可回答 | 文档中不存在的信息 | 10% |
| 摘要 | "总结 X 的主要内容" | 10% |

推荐测试集规模：**200-500 条**，低于 100 条统计意义不足。

---

## 七、Web 端功能规划

| 页面 | 核心功能 |
|------|----------|
| **测试集管理** | 上传 JSON 测试集、LLM 自动生成、人工标注界面、样本预览 |
| **评测任务** | 配置 Adapter（平台连接）、配置 Judge 模型、提交任务、实时进度 |
| **评测报告** | 各指标得分雷达图、样本级别明细表、多次评测趋势对比、问题样本下钻 |
| **配置管理** | 平台连接配置（URL/Token）、Judge 模型配置（API Key/Model）|

---

## 八、数据库设计（Server 端）

```sql
-- 平台连接配置
CREATE TABLE platform_config (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    type        TEXT NOT NULL,          -- 'dagent' | 'custom'
    base_url    TEXT NOT NULL,
    org_id      TEXT,
    token       TEXT,
    created_at  DATETIME
);

-- Judge 模型配置
CREATE TABLE judge_config (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    base_url    TEXT NOT NULL,
    api_key     TEXT NOT NULL,
    model       TEXT NOT NULL,
    created_at  DATETIME
);

-- 测试集
CREATE TABLE eval_dataset (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    description TEXT,
    sample_count INTEGER,
    created_at  DATETIME
);

-- 测试样本
CREATE TABLE eval_sample (
    id                  TEXT PRIMARY KEY,
    dataset_id          TEXT NOT NULL,
    question            TEXT NOT NULL,
    reference_answer    TEXT NOT NULL,
    relevant_chunk_ids  TEXT NOT NULL,   -- JSON array
    knowledge_hub_id    TEXT NOT NULL,
    source_file_id      TEXT,
    metadata            TEXT             -- JSON
);

-- 评测任务
CREATE TABLE eval_task (
    id                  TEXT PRIMARY KEY,
    name                TEXT,
    dataset_id          TEXT NOT NULL,
    platform_config_id  TEXT NOT NULL,
    judge_config_id     TEXT NOT NULL,
    agent_id            TEXT NOT NULL,
    knowledge_hub_id    TEXT NOT NULL,
    top_k               INTEGER DEFAULT 10,
    status              TEXT NOT NULL,   -- pending | running | done | failed
    progress            INTEGER DEFAULT 0,
    created_at          DATETIME,
    finished_at         DATETIME
);

-- 样本级评测结果
CREATE TABLE eval_result (
    id                  TEXT PRIMARY KEY,
    task_id             TEXT NOT NULL,
    sample_id           TEXT NOT NULL,
    retrieved_chunks    TEXT,            -- JSON
    agent_answer        TEXT,
    hit_rate            REAL,
    mrr                 REAL,
    ndcg                REAL,
    context_precision   REAL,
    context_recall      REAL,
    faithfulness        REAL,
    answer_relevance    REAL,
    answer_correctness  REAL,
    judge_detail        TEXT             -- JSON，LLM judge 的推理过程
);

-- 评测汇总报告
CREATE TABLE eval_report (
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
    rag_score               REAL,
    hallucination_rate      REAL,
    created_at              DATETIME
);
```

---

## 九、开发优先级

| 阶段 | 内容 | 说明 |
|------|------|------|
| **Phase 1** | SDK 核心：Adapter 接口 + 检索评测器 | 无 LLM 依赖，最快验证，Hit Rate/MRR/NDCG |
| **Phase 2** | dagent Adapter 实现 | 对接现有平台 HTTP API |
| **Phase 3** | LLM Judge 模块 | Faithfulness / Relevance / Correctness |
| **Phase 4** | 测试集自动生成器 | 降低标注成本 |
| **Phase 5** | FastAPI Server | 把 SDK 包成 Web 服务，支持异步任务 |
| **Phase 6** | React 前端 | 报告可视化、测试集管理 |

---

## 十、技术选型

| 模块 | 技术 | 理由 |
|------|------|------|
| SDK | Python 3.10+, asyncio, Pydantic | 与 dagent 保持一致，异步支持并发评测 |
| Server | FastAPI + SQLite（开发）/ PostgreSQL（生产） | 轻量，易部署 |
| 任务队列 | asyncio.Queue（轻量）/ Celery（生产） | 评测任务耗时长，需异步执行 |
| Frontend | React + TypeScript + Ant Design | 与 dagent 前端技术栈一致 |
| LLM Judge | OpenAI SDK（兼容 DeepSeek/Qwen） | 统一接口，灵活切换模型 |
| 部署 | Docker Compose | 一键启动 server + frontend |

---

## 十一、与 dagent 平台的集成方式

框架通过 **HTTP API** 调用 dagent，不依赖 dagent 内部代码。

dagent 需要提供（或框架调用现有接口）：

1. **检索接口**：`POST /dagent/knowledge/retrieve`
   - 输入：query, knowledge_hub_id, top_k, org_id
   - 输出：切片列表（chunk_id, content, score, headers, file_id）

2. **对话接口**：`POST /dagent/agent/chat`（现有 SSE 接口）
   - 输入：question, agent_id, org_id
   - 输出：回复文本 + 引用切片信息

如果 dagent 现有接口不完全满足，可在 dagent 侧新增一个**评测专用接口**，返回更详细的检索过程信息（如每个切片的 cosine distance、rerank score 等）。
