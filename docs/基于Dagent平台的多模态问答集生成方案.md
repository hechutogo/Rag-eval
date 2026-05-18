# 基于 Dagent 平台的多模态问答集生成方案

**目标：** 利用 dagent 后端已有的知识库处理能力，生成包含图像信息的高质量问答集

---

## 一、Dagent 平台现有能力分析

### 1.1 核心能力

| 能力 | 实现位置 | 说明 |
|------|---------|------|
| **HTML → Markdown 转换** | `pdf_service.py` 调用 marker 服务 | 支持 PDF/DOCX/RST → MD |
| **图片 OCR + 语义描述** | `pic_to_text.py` | 使用 GPT-4V 将图片转文本，存入数据库 |
| **Markdown 段落分割** | `split_markdown_filter.py` | 按标题层级分割段落 |
| **图片路径处理** | `md_service.py` | 相对路径 → BOS 绝对路径 |
| **向量索引存储** | `store_*_semantic_index.py` | 段落/问题/表格向量化 |
| **知识库检索** | `knowledge_md_retrieve_service.py` | 语义搜索 |

### 1.2 数据库结构（OceanBase，兼容 MySQL）

**连接信息：**
```
Host:     120.48.66.228
Port:     23306
User:     dagent
Password: Fd1.Ej3.fdIie48
Database: dagent_platform
```

**核心表：**

**knowledge_file** — 原始文件元数据
```
id, org_id, file_md5, file_name, file_type, file_bytes, file_url, file_clean_status
```

**knowledge_md_header_split** — 段落分割结果（最重要）
```
id, org_id, file_id, file_name, headers
paragraph_context              -- 段落文本内容
paragraph_img_num              -- 段落内图片数量
paragraph_pic_semantics_context -- 图片 OCR + 语义描述（GPT-4V 已处理）
paragraph_question             -- Dagent 已生成的段落问题
paragraph_summary              -- 段落摘要
paragraph_keywords             -- 关键词
```

**knowledge_md_paragraph_active_context** — 段落活跃上下文（含向量）
```
id, file_id, headers, active_context, active_context_vector
```

### 1.3 关键发现

**Dagent 已经做了：**
- 209 个 HTML 文件 → 已转换为 Markdown
- 1142 张图片 → 已上传 BOS，已用 GPT-4V 生成语义描述
- 段落按标题层级分割完毕
- 每个段落已有 `paragraph_question`、`paragraph_summary`、`paragraph_keywords`

**结论：不需要重新处理 HTML，直接读数据库即可。**

---

## 二、方案设计

### 2.1 整体流程

```
Dagent 数据库 (knowledge_md_header_split)
    ↓
提取段落数据
  - paragraph_context（文本）
  - paragraph_pic_semantics_context（图片语义，已有）
  - paragraph_question（种子问题，已有）
    ↓
┌─────────────────────────────────────┐
│  问答生成（三类）                    │
│  1. 纯文本问题（基于 paragraph_context）│
│  2. 图文结合问题（文本 + 图片语义）   │
│  3. 扩展种子问题（基于已有问题扩展）  │
└─────────────────────────────────────┘
    ↓
存入 RAG Eval 数据库 (qa_gen_question)
    ↓
审核 → 导出 MD → 单跳召回测试
```

### 2.2 对比：从零处理 vs 利用 Dagent

| 维度 | 从零处理 HTML | 利用 Dagent 数据库 |
|------|--------------|-------------------|
| 开发工作量 | 2-3 周 | 3-5 天 |
| 图片 OCR 成本 | 1142 张 × $0.008 = $9 | $0（已完成） |
| 问答生成成本 | $4 | $4 |
| 数据可靠性 | 需验证 | 生产环境已验证 |
| **总成本** | **$13 + 2-3 周** | **$4 + 3-5 天** |

---

## 三、实现方案

### 3.1 后端：新增 Dagent 数据源支持

**新增文件：** `server/api/qa_gen_dagent.py`

```python
"""
从 Dagent 数据库导入知识库数据，生成多模态问答集
"""
import asyncio
import json
import aiomysql
from fastapi import APIRouter, Form
from typing import Optional

from ..models.db import get_db, _now, _id

router = APIRouter(prefix="/api/qa-gen", tags=["问题生成-Dagent"])

DAGENT_DB = {
    "host": "120.48.66.228",
    "port": 23306,
    "user": "dagent",
    "password": "Fd1.Ej3.fdIie48",
    "db": "dagent_platform",
    "charset": "utf8mb4",
}


async def get_dagent_conn():
    return await aiomysql.connect(**DAGENT_DB)


@router.post("/task/from-dagent")
async def create_task_from_dagent(
    org_id: str = Form(...),
    name: str = Form(""),
    judge_config_id: str = Form(...),
    file_ids: str = Form(""),           # 逗号分隔的 file_id，为空则全量
    questions_per_section: int = Form(5),
    quality_threshold: float = Form(0.6),
    include_multimodal: bool = Form(True),
):
    """从 Dagent 数据库创建问答生成任务"""
    task_id = _id()
    file_id_list = [f.strip() for f in file_ids.split(",") if f.strip()]

    async with get_db() as db:
        await db.execute(
            """INSERT INTO qa_gen_task
               (id,name,judge_config_id,questions_per_section,quality_threshold,status,created_at)
               VALUES (?,?,?,?,?,?,?)""",
            (task_id, name or f"Dagent导入({org_id[:8]}...)",
             judge_config_id, questions_per_section, quality_threshold, "pending", _now()),
        )
        await db.commit()

    asyncio.create_task(_run_dagent_task(
        task_id, org_id, file_id_list, judge_config_id,
        questions_per_section, quality_threshold, include_multimodal,
    ))
    return {"status": 0, "data": {"id": task_id}}


@router.get("/dagent/files")
async def list_dagent_files(org_id: str):
    """列出 Dagent 中某组织下已处理完成的文件"""
    conn = await get_dagent_conn()
    cursor = await conn.cursor(aiomysql.DictCursor)
    await cursor.execute(
        """SELECT id, file_name, file_type, file_clean_status,
                  file_bytes, create_time
           FROM knowledge_file
           WHERE org_id = %s AND delete_time IS NULL
           ORDER BY create_time DESC""",
        (org_id,),
    )
    rows = await cursor.fetchall()
    await cursor.close()
    conn.close()
    return {"status": 0, "data": [dict(r) for r in rows]}


@router.get("/dagent/stats")
async def get_dagent_stats(org_id: str):
    """获取 Dagent 知识库统计信息"""
    conn = await get_dagent_conn()
    cursor = await conn.cursor(aiomysql.DictCursor)
    await cursor.execute(
        """SELECT
               COUNT(DISTINCT f.id) as file_count,
               COUNT(h.id) as paragraph_count,
               SUM(h.paragraph_img_num) as total_images,
               SUM(CASE WHEN h.paragraph_pic_semantics_context IS NOT NULL
                        AND h.paragraph_img_num > 0 THEN 1 ELSE 0 END) as paragraphs_with_pic_text,
               SUM(CASE WHEN h.paragraph_question IS NOT NULL THEN 1 ELSE 0 END) as paragraphs_with_question
           FROM knowledge_file f
           LEFT JOIN knowledge_md_header_split h
               ON f.id = h.file_id AND h.delete_time IS NULL
           WHERE f.org_id = %s AND f.delete_time IS NULL
             AND f.file_clean_status = 'CLEAN_FINISH'""",
        (org_id,),
    )
    row = await cursor.fetchone()
    await cursor.close()
    conn.close()
    return {"status": 0, "data": dict(row) if row else {}}


# ── 内部：后台任务 ─────────────────────────────────────────────────────────────

async def _fetch_paragraphs(org_id: str, file_id_list: list[str]) -> list[dict]:
    """从 Dagent 数据库提取段落数据"""
    conn = await get_dagent_conn()
    cursor = await conn.cursor(aiomysql.DictCursor)

    sql = """
        SELECT h.id, h.file_id, h.file_name, h.headers,
               h.paragraph_context, h.paragraph_img_num,
               h.paragraph_pic_semantics_context,
               h.paragraph_question, h.paragraph_summary, h.paragraph_keywords
        FROM knowledge_md_header_split h
        JOIN knowledge_file f ON f.id = h.file_id
        WHERE h.org_id = %s
          AND h.delete_time IS NULL
          AND f.delete_time IS NULL
          AND f.file_clean_status = 'CLEAN_FINISH'
    """
    params = [org_id]

    if file_id_list:
        placeholders = ",".join(["%s"] * len(file_id_list))
        sql += f" AND h.file_id IN ({placeholders})"
        params.extend(file_id_list)

    sql += " ORDER BY h.file_name, h.headers"

    await cursor.execute(sql, params)
    rows = await cursor.fetchall()
    await cursor.close()
    conn.close()
    return [dict(r) for r in rows]


async def _generate_questions_for_paragraph(
    para: dict, cfg: dict, n: int, include_multimodal: bool
) -> list[dict]:
    """为单个段落生成问答"""
    import aiohttp, re

    base_url = cfg.get("base_url", "").rstrip("/")
    api_key = cfg.get("api_key", "")
    model = cfg.get("model", "gpt-4o-mini")

    text = (para.get("paragraph_context") or "").strip()
    pic_semantics = (para.get("paragraph_pic_semantics_context") or "").strip()
    seed_question = (para.get("paragraph_question") or "").strip()
    headers = (para.get("headers") or "").strip()
    has_image = bool(pic_semantics and para.get("paragraph_img_num", 0) > 0)

    if not text:
        return []

    # 构建 prompt
    pic_section = ""
    if has_image and include_multimodal:
        pic_section = f"""
**图片语义描述（图片已由 AI 识别）：**
{pic_semantics[:800]}
"""

    seed_section = ""
    if seed_question:
        seed_section = f"\n**已有种子问题（请避免重复，可从不同角度扩展）：** {seed_question}"

    prompt = f"""你是一个技术文档问答生成专家。基于以下内容生成 {n} 个测试问题。

**章节路径：** {headers}

**文本内容：**
{text[:2500]}
{pic_section}{seed_section}

**要求：**
1. 问题必须能从该章节内容直接回答
2. 覆盖关键知识点，避免过于简单的是非题
3. 如果有图片语义描述，至少生成 1 个图文结合的问题（问题中提及"如图所示"、"图中"等）
4. 答案准确，长度适中（1-3 句话）
5. source_chunk 为答案来源的原文片段（50-150 字）
6. has_image 标记该问题是否依赖图像信息
7. quality_score 为质量评估（0-1）

只输出 JSON 数组：
[
  {{
    "question": "问题文本",
    "answer": "参考答案",
    "source_chunk": "答案来源原文片段",
    "has_image": false,
    "quality_score": 0.9
  }}
]"""

    headers_http = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.3,
    }

    try:
        async with aiohttp.ClientSession(headers=headers_http) as session:
            async with session.post(
                f"{base_url}/chat/completions",
                json=payload,
                timeout=aiohttp.ClientTimeout(total=60),
            ) as resp:
                resp.raise_for_status()
                data = await resp.json()

        text_resp = data["choices"][0]["message"]["content"].strip()
        m = re.search(r"\[.*\]", text_resp, re.DOTALL)
        if not m:
            return []
        questions = json.loads(m.group())
        result = []
        for q in questions:
            if isinstance(q, dict) and q.get("question") and q.get("answer"):
                result.append({
                    "question": str(q["question"]).strip(),
                    "answer": str(q["answer"]).strip(),
                    "source_chunk": str(q.get("source_chunk", "")).strip(),
                    "has_image": bool(q.get("has_image", False)),
                    "quality_score": float(q.get("quality_score", 0.8)),
                    "source_image_desc": pic_semantics[:300] if q.get("has_image") else "",
                })
        return result
    except Exception as e:
        return []


async def _run_dagent_task(
    task_id: str,
    org_id: str,
    file_id_list: list[str],
    judge_config_id: str,
    questions_per_section: int,
    quality_threshold: float,
    include_multimodal: bool,
):
    try:
        # 1. 提取段落
        paragraphs = await _fetch_paragraphs(org_id, file_id_list)
        total = len(paragraphs)

        async with get_db() as db:
            await db.execute(
                "UPDATE qa_gen_task SET status='running', total=? WHERE id=?",
                (total, task_id),
            )
            await db.commit()

        # 2. 获取 LLM 配置
        async with get_db() as db:
            cfg_rows = await db.execute_fetchall(
                "SELECT * FROM judge_config WHERE id=?", (judge_config_id,)
            )
        if not cfg_rows:
            raise ValueError("judge_config not found")
        cfg = dict(cfg_rows[0])

        # 3. 并发生成（每次最多 5 个段落并发）
        sem = asyncio.Semaphore(5)
        done = 0
        FLUSH_SIZE = 10
        write_buf = []

        async def process_one(para: dict):
            nonlocal done
            async with sem:
                questions = await _generate_questions_for_paragraph(
                    para, cfg, questions_per_section, include_multimodal
                )
            done += 1
            write_buf.extend([(para, q) for q in questions])

            if len(write_buf) >= FLUSH_SIZE or done == total:
                batch = write_buf.copy()
                write_buf.clear()
                async with get_db() as db2:
                    for p, q in batch:
                        qid = _id()
                        status = "approved" if q["quality_score"] >= quality_threshold else "pending"
                        await db2.execute(
                            """INSERT INTO qa_gen_question
                               (id,task_id,section_path,question,reference_answer,source_chunk,
                                quality_score,status,created_at)
                               VALUES (?,?,?,?,?,?,?,?,?)""",
                            (qid, task_id, p["headers"],
                             q["question"], q["answer"], q["source_chunk"],
                             q["quality_score"], status, _now()),
                        )
                    # 同步 approved 计数
                    count_rows = await db2.execute_fetchall(
                        "SELECT COUNT(*) as cnt FROM qa_gen_question WHERE task_id=? AND status='approved'",
                        (task_id,),
                    )
                    approved = dict(count_rows[0])["cnt"] if count_rows else 0
                    await db2.execute(
                        "UPDATE qa_gen_task SET progress=?, approved=? WHERE id=?",
                        (done, approved, task_id),
                    )
                    await db2.commit()

        await asyncio.gather(*[process_one(p) for p in paragraphs])

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
```

### 3.2 注册路由

在 `server/main.py` 中添加：

```python
from .api import config, dataset, task, report, single_jump, qa_gen, qa_gen_dagent

app.include_router(qa_gen_dagent.router)
```

### 3.3 前端：新增"从 Dagent 导入"入口

在 `QaGen/index.tsx` 的新建任务弹窗中增加数据源切换：

```tsx
// 数据源选择
<Form.Item label="数据来源">
  <Radio.Group value={dataSource} onChange={e => setDataSource(e.target.value)}>
    <Radio value="file">上传 MD 文件</Radio>
    <Radio value="dagent">从 Dagent 知识库导入</Radio>
  </Radio.Group>
</Form.Item>

{dataSource === 'dagent' ? (
  <>
    <Form.Item name="org_id" label="Dagent 组织 ID" rules={[{ required: true }]}>
      <Input placeholder="cd6e121594984516..." />
    </Form.Item>
    <Form.Item name="file_ids" label="指定文件 ID（可选）"
      tooltip="留空则导入该组织下所有已处理完成的文件">
      <Input.TextArea rows={2} placeholder="多个 ID 用逗号分隔，留空则全量导入" />
    </Form.Item>
    <Form.Item name="include_multimodal" label="生成图文结合问题" valuePropName="checked"
      tooltip="利用 Dagent 已生成的图片语义描述，生成图文结合的问题">
      <Switch defaultChecked />
    </Form.Item>
    {/* 统计信息展示 */}
    {dagentStats && (
      <div style={{ background: '#f6ffed', border: '1px solid #b7eb8f', borderRadius: 6, padding: '8px 12px', marginBottom: 16 }}>
        <Space split={<Divider type="vertical" />}>
          <span>文件数: <b>{dagentStats.file_count}</b></span>
          <span>段落数: <b>{dagentStats.paragraph_count}</b></span>
          <span>含图段落: <b>{dagentStats.paragraphs_with_pic_text}</b></span>
          <span>总图片: <b>{dagentStats.total_images}</b></span>
        </Space>
      </div>
    )}
  </>
) : (
  // 原有的文件上传 UI
  <Form.Item label="知识库 MD 文件" required>
    <Upload ... />
  </Form.Item>
)}
```

---

## 四、验证步骤

### Step 1：先查询数据库确认数据完整性

```sql
-- 查看 EVB 知识库的文件列表
SELECT id, file_name, file_type, file_clean_status
FROM knowledge_file
WHERE org_id = 'cd6e121594984516bde17ae9aeb0eb45a01e6d28143034608c4985aea369deec'
  AND delete_time IS NULL
ORDER BY file_name;

-- 查看段落统计（含图片处理情况）
SELECT
    f.file_name,
    COUNT(h.id) as paragraphs,
    SUM(h.paragraph_img_num) as images,
    SUM(CASE WHEN h.paragraph_pic_semantics_context IS NOT NULL THEN 1 ELSE 0 END) as pic_text_done,
    SUM(CASE WHEN h.paragraph_question IS NOT NULL THEN 1 ELSE 0 END) as has_question
FROM knowledge_file f
JOIN knowledge_md_header_split h ON f.id = h.file_id AND h.delete_time IS NULL
WHERE f.org_id = 'cd6e121594984516bde17ae9aeb0eb45a01e6d28143034608c4985aea369deec'
  AND f.delete_time IS NULL
GROUP BY f.file_name
ORDER BY f.file_name;
```

### Step 2：抽样检查图片语义质量

```sql
-- 随机抽取 10 个有图片的段落，检查图片语义描述质量
SELECT headers, LEFT(paragraph_context, 200) as text_preview,
       LEFT(paragraph_pic_semantics_context, 300) as pic_text_preview
FROM knowledge_md_header_split
WHERE org_id = 'cd6e121594984516bde17ae9aeb0eb45a01e6d28143034608c4985aea369deec'
  AND paragraph_img_num > 0
  AND paragraph_pic_semantics_context IS NOT NULL
  AND delete_time IS NULL
ORDER BY RAND()
LIMIT 10;
```

### Step 3：小批量 Pilot 测试

先选 1 个文件（如 `common_questions`）做 Pilot，生成 ~50 条问答，人工审核质量后再全量。

---

## 五、预期产出

| 模块 | 段落数 | 含图段落 | 预期问答数 |
|------|--------|---------|-----------|
| linux_development | ~500 | ~200 | ~2500 条 |
| multimedia_development | ~150 | ~80 | ~750 条 |
| samples | ~100 | ~50 | ~500 条 |
| toolchain_development | ~80 | ~30 | ~400 条 |
| quick_start | ~30 | ~15 | ~150 条 |
| preface + common_questions | ~20 | ~5 | ~100 条 |
| **合计** | **~880** | **~380** | **~4400 条** |

其中多模态问题（图文结合）预计占 **20-30%**（约 880-1320 条）。

---

## 六、依赖安装

```bash
pip install aiomysql
```

（其他依赖 aiohttp、fastapi 等已有）
