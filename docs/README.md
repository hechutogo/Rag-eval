# RAG Eval 文档目录

本目录集中存放**技术性说明**与**数据型资产**（方案、规则、配置、导出结果）。项目入口说明仍见仓库根目录 [`README.md`](../README.md)。

---

## 分批与数据

| 文档 | 说明 |
|------|------|
| [循环测试_14组分批规则.md](./循环测试_14组分批规则.md) | 14 组 × 42 批次规则说明（人类可读） |
| task_groups_plan.json / exports/ | 本地数据资产（**不入 Git**，见 `.gitignore`） |
| [循环测试_14组分批规则.md](./循环测试_14组分批规则.md) | 分批说明（本地保留，含环境信息时不提交仓库） |

---

## 架构与设计

| 文档 | 说明 |
|------|------|
| [**RAG-Eval平台技术规格说明书.md**](./RAG-Eval平台技术规格说明书.md) | **万字级技术文档**（架构图、时序图、数据模型、API、指标） |
| [rag-eval-framework-design.md](./rag-eval-framework-design.md) | 评测框架总体设计（早期稿） |
| [TUTORIAL.md](./TUTORIAL.md) | 使用教程 |
| [config.example.yaml](./config.example.yaml) | SDK 配置示例（副本，运行仍以 `sdk/config.example.yaml` 为准） |

---

## 方案与报告

| 文档 | 说明 |
|------|------|
| [LLM自动生成问题方案.md](./LLM自动生成问题方案.md) | LLM 自动出题流程 |
| [多模态问答集生成方案.md](./多模态问答集生成方案.md) | 多模态问答集生成 |
| [基于Dagent平台的多模态问答集生成方案.md](./基于Dagent平台的多模态问答集生成方案.md) | Dagent 平台多模态方案 |
| [Dagent文件选择器方案.md](./Dagent文件选择器方案.md) | 文件选择器 |
| [EVB知识库单跳召回测试报告.md](./EVB知识库单跳召回测试报告.md) | EVB 单跳召回测试 |
| [验证报告.md](./验证报告.md) | 验证报告 |
| [multi-hop-example.md](./multi-hop-example.md) | 多跳测试 MD 样例格式 |
