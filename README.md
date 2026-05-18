# RAG Eval Framework

平台无关的 **RAG 评测平台**，面向 远程agent 及任意兼容 HTTP 接口的 RAG 系统，提供检索层 + 生成层全指标评测、LLM 自动出题、单跳/多跳召回测试与循环压测能力。

| 使用方式 | 说明 |
|----------|------|
| **Web UI** | React + Ant Design，配置 / 测试集 / 任务 / 报告一站式操作 |
| **REST API** | FastAPI，11 组路由，OpenAPI 文档 `/docs` |
| **Python SDK** | `EvalRunner` + CLI，可嵌入 CI/CD |

📖 **详细技术文档（万字级，含架构图与时序图）**：[docs/RAG-Eval平台技术规格说明书.md](./docs/RAG-Eval平台技术规格说明书.md)  

---

## 功能一览

| 模块 | 能力 |
|------|------|
| **综合评测** | Hit@K、MRR、NDCG、Context Precision/Recall、Faithfulness、Answer Relevance/Correctness、Groundedness、RAG Score |
| **测试集** | 手动录入、JSON 导入、LLM 按知识库文件自动生成 |
| **单跳召回** | 上传 MD 问答集，映射 file_id，批量语义召回与命中率统计 |
| **多跳召回** | 多跳问题解析、分跳召回与全链路命中判定 |
| **问题生成** | 按切片 LLM 出题、质量打分、向量去重、人工审核 |
| **循环测试** | 多轮「出题 → 去重 → 单跳验证」闭环，支持暂停/恢复/导出 |
| **提示词模板** | 可配置出题 / 评判 Prompt |

---

## 架构概览

```
┌─────────────┐     ┌──────────────────┐     ┌─────────────┐
│  React UI   │────▶│  FastAPI :8021   │────▶│  SQLite DB  │
│  (Vite)     │     │  + 11 API 路由    │     │  (WAL)      │
└─────────────┘     └────────┬─────────┘     └─────────────┘
                             │ sys.path → sdk/
                             ▼
                    ┌──────────────────┐
                    │  rag_eval SDK    │
                    │  Adapter/Judge/  │
                    │  Runner/Parser   │
                    └────────┬─────────┘
                             │ HTTP
                             ▼
                    ┌──────────────────┐
                    │  远程agent / 其他   │
                    │  RAG 平台        │
                    └──────────────────┘
```

---

## 项目结构

```
rag-eval/
├── docs/                    # 技术文档、分批规则、数据导出
├── sdk/rag_eval/            # 核心评测逻辑（Adapter、Judge、Runner…）
├── server/                  # FastAPI 后端
│   ├── api/                 # REST 路由（config/dataset/task/report/…）
│   ├── service/             # 任务编排（task_service、loop_engine）
│   └── models/              # SQLite schema + 迁移
├── frontend/                # React Web UI
├── docker-compose.yml
└── README.md
```

---

## 快速开始

### Docker Compose

```bash
cd rag-eval
docker-compose up -d
# Web UI: http://localhost:3000  |  API: http://localhost:8003/docs
```

### 本地开发

```bash
# 后端（默认 8021，可改端口）
cd server && pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8021 --reload

# 前端（开发代理到 8021）
cd frontend && npm install && npm run dev

# SDK
cd sdk && pip install -e .
rag-eval run --config config.yaml --dataset dataset.json --output report.json
```

生产环境可将 `frontend/dist` 构建产物由 FastAPI `StaticFiles` 挂载，单端口对外。

---

## 典型工作流

1. **配置管理** — 添加 dagent `base_url` / `org_id` 与 Judge（OpenAI 兼容）模型  
2. **测试集** — 导入 JSON、手动添加或 LLM 自动生成  
3. **评测任务** — 选择指标子集，后台异步跑批，查看雷达图与 AI 解读  
4. **单跳/多跳/循环** — 见 [技术规格说明书 · 业务流程](./docs/RAG-Eval平台技术规格说明书.md#6-业务流程与时序图)

---

## 评测指标速查

| 层级 | 指标 | 类型 |
|------|------|------|
| 检索 | Hit Rate@K、MRR@K、NDCG@K | 规则（需 `relevant_chunk_ids`） |
| 检索 | Context Precision / Recall | LLM-as-Judge |
| 生成 | Faithfulness、Groundedness | LLM-as-Judge |
| 生成 | Answer Relevance | LLM + Embedding |
| 生成 | Answer Correctness | LLM-as-Judge（需参考答案） |
| 综合 | RAG Score、Hallucination Rate | 派生 |

阈值与解读见技术文档 [第 7 章](./docs/RAG-Eval平台技术规格说明书.md#7-评测指标体系)。

---

## 扩展其他 RAG 平台

实现 `RAGAdapter` 的 `retrieve` 与 `chat` 即可接入：

```python
from rag_eval.adapters.base import RAGAdapter, RetrievedChunk, AgentResponse

class MyAdapter(RAGAdapter):
    async def retrieve(self, query, knowledge_hub_id, top_k=10, **kwargs) -> list[RetrievedChunk]: ...
    async def chat(self, query, agent_id, **kwargs) -> AgentResponse: ...
```

---

## 相关文档

| 文档 | 说明 |
|------|------|
| [RAG-Eval平台技术规格说明书.md](./docs/RAG-Eval平台技术规格说明书.md) | 架构、时序图、数据模型、API |

---

## License

内部项目，使用前请遵循组织代码与数据安全规范。
