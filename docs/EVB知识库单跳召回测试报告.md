# EVB 知识库单跳召回测试报告

**测试时间：** 2026-04-21  
**测试范围：** EVB 知识库全量 7 个模块  
**测试方法：** 单跳语义召回（cross_chunk 模式，top_k=3）

---

## 一、总体概览

| 指标 | 数值 |
|------|------|
| 总问题数 | **12,591** |
| 召回成功率 | **100%**（12,591 / 12,591） |
| 文件命中率 | **63.1%**（7,849 / 12,591） |
| 文件命中失败 | **4,742 条** |
| 平均最佳余弦相似度 | **0.868** |
| 平均召回延迟 | **432 ms** |
| 覆盖章节数 | **171 个** |

> **召回成功率 100%** 说明知识库语义索引完整，所有问题均能检索到相关内容。  
> **文件命中率 63.1%** 是核心问题：召回的 top-k 结果中，有 36.9% 的问题未能命中预期文件，说明跨文件语义干扰较严重。

---

## 二、分模块统计

| 模块 | 问题数 | 召回率 | 文件命中率 | 命中失败 | 平均相似度 | 平均延迟 | 章节数 |
|------|--------|--------|-----------|---------|-----------|---------|--------|
| linux_development | 7,455 | 100% | **63.7%** | 2,703 | 0.864 | 433ms | 107 |
| multimedia_development | 2,307 | 100% | **68.8%** | 720 | 0.880 | 425ms | 25 |
| samples | 1,374 | 100% | **53.6%** | 637 | 0.872 | 434ms | 19 |
| toolchain_development | 832 | 100% | **57.3%** | 355 | 0.859 | 423ms | 13 |
| quick_start | 483 | 100% | **47.6%** | 253 | 0.869 | 441ms | 5 |
| preface | 86 | 100% | **30.2%** | 60 | 0.867 | 469ms | 1 |
| common_questions | 54 | 100% | **74.1%** | 14 | 0.887 | 476ms | 1 |

**最佳模块：** common_questions（74.1%）、multimedia_development（68.8%）  
**最差模块：** preface（30.2%）、quick_start（47.6%）

---

## 三、文件命中率最差章节 TOP 20

| 模块 | 章节路径（截断） | 命中率 | 问题数 | 平均相似度 |
|------|----------------|--------|--------|-----------|
| multimedia_development | multimedia_development / 8-GDC_index_zh_ | **0%** | 68 | 0.868 |
| toolchain_development | toolchain_development / expert / environ | **2%** | 35 | 0.836 |
| samples | samples / sunrise_camera_develop_guide | **12%** | 141 | 0.838 |
| linux_development | linux_development / system_debug / ddr (1) | **13%** | 30 | 0.853 |
| samples | samples / overview | **13%** | 65 | 0.874 |
| linux_development | linux_command_manual (1) | **15%** | 71 | 0.860 |
| linux_development | linux_development / system_debug / ddr (2) | **18%** | 75 | 0.865 |
| quick_start | quick_start / x5_evb_1_b_user_guide | **21%** | 131 | 0.863 |
| toolchain_development | toolchain_development / expert / quick_s | **22%** | 40 | 0.840 |
| linux_development | linux_development / system_debug / ddr (3) | **23%** | 51 | 0.837 |
| samples | samples / sample_osd | **26%** | 50 | 0.867 |
| samples | samples / sample_hbmem | **26%** | 68 | 0.857 |
| linux_development | linux_development / driver_develop_guide (1) | **28%** | 50 | 0.851 |
| preface | preface / overview | **30%** | 86 | 0.867 |
| linux_development | system_component_dev | **31%** | 51 | 0.849 |
| samples | samples / sample_imu | **31%** | 72 | 0.868 |
| linux_development | linux_command_manual (2) | **32%** | 134 | 0.849 |
| quick_start | quick_start / x5_evb_v2p0_user_guide | **33%** | 107 | 0.878 |
| linux_development | linux_development / driver_develop_guide (2) | **33%** | 59 | 0.857 |
| samples | samples / sample_trustzone | **34%** | 50 | 0.881 |

---

## 四、问题诊断

### 4.1 文件命中率低的根本原因

**相似度高但命中率低**（如 multimedia_development/GDC 章节：sim=0.868 但命中率 0%）说明问题不是语义索引质量差，而是：

1. **知识库文件粒度过粗**：多个文档内容高度相似（如不同版本的 EVB 用户手册、多个 DDR 调试文档），导致召回时命中了语义相近但文件不同的内容
2. **章节路径与文件名映射偏差**：部分章节（如 GDC、preface/overview）在知识库中对应的文件名与 MD 路径差异较大，文件映射失败
3. **跨文件语义干扰**：samples 模块各 sample 文档结构相似（都有 overview、API 说明），问题语义相近导致召回串文件

### 4.2 各模块特征分析

- **linux_development**（最大模块，107 章节）：整体命中率 63.7%，DDR 调试相关章节命中率极低（13-23%），推测是多个 DDR 相关文档内容重叠
- **multimedia_development**：GDC 章节 0% 命中，需检查该章节的文件映射是否正确
- **samples**：命中率最低（53.6%），各 sample 文档结构高度相似是主因
- **preface**：仅 30.2%，overview 章节内容通用性强，容易被其他文档的 overview 内容干扰
- **common_questions**：命中率最高（74.1%），FAQ 类问题语义独特性强

---

## 五、优化建议

### 短期（知识库配置层面）

| 优先级 | 建议 | 预期收益 |
|--------|------|---------|
| 🔴 高 | 检查并修复 multimedia_development/GDC 章节的文件映射 | 68 条 0% 命中问题 |
| 🔴 高 | 对 DDR 调试相关文档（3 个重叠章节）合并或增加文件标识元数据 | ~156 条低命中问题 |
| 🟡 中 | samples 模块各文档增加文件级别的唯一标识前缀（如文件名注入到 chunk） | 637 条命中失败 |
| 🟡 中 | quick_start 两个版本手册（1_b 和 v2p0）内容重叠，考虑合并或版本标注 | 384 条命中失败 |
| 🟢 低 | preface/overview 内容过于通用，考虑增加文档标题作为 chunk 前缀 | 60 条命中失败 |

### 中期（召回策略层面）

1. **降低 top_k**：当前 top_k=3，对于高相似度干扰场景可尝试 top_k=1 测试精确命中率
2. **文件级过滤**：对已知文件映射的章节，在召回时传入 `file_id_list` 限定范围（关闭 cross_chunk）
3. **Rerank 优化**：在 rerank 阶段引入文件来源权重，同文件内的 chunk 给予加分

---

## 六、测试执行情况

| 模块 | 开始时间 | 结束时间 | 耗时 |
|------|---------|---------|------|
| linux_development | 03:01:38 | 03:12:27 | **10m 49s** |
| multimedia_development | 03:12:08 | 03:15:26 | **3m 18s** |
| quick_start | 03:21:33 | 03:21:46 | **13s** |
| samples | 03:22:56 | 03:23:26 | **30s** |
| toolchain_development | 03:23:52 | 03:24:12 | **20s** |
| preface | 03:24:25 | 03:24:28 | **3s** |
| common_questions | 03:24:59 | 03:25:01 | **2s** |

总测试耗时约 **24 分钟**，12,591 条问题全部完成，无错误。
