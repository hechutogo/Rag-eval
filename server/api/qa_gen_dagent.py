"""
从 Dagent 数据库导入知识库数据，生成多模态问答集
"""
import asyncio
import json
import re
import sys
from pathlib import Path
from fastapi import APIRouter, Form, HTTPException
from typing import Optional
import aiohttp
import aiomysql

import logging
import os
from datetime import datetime

# 设置文件日志（必须在 Path 导入后）
LOG_PATH = Path(__file__).parent.parent / "logs"
LOG_PATH.mkdir(exist_ok=True)
_logger = logging.getLogger("qa_gen_dagent")
_logger.setLevel(logging.DEBUG)
if not _logger.handlers:
    _fh = logging.FileHandler(LOG_PATH / "qa_gen_debug.log", encoding="utf-8")
    _fh.setLevel(logging.DEBUG)
    _fh.setFormatter(logging.Formatter("%(asctime)s - %(message)s"))
    _logger.addHandler(_fh)

def _log(msg: str):
    """强制写入文件日志"""
    _logger.debug(msg)

# Add parent directory to sys.path for relative imports
sys.path.insert(0, str(Path(__file__).parent.parent))
from models.db import get_db, _now, _id

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
    """创建 Dagent 数据库连接"""
    return await aiomysql.connect(**DAGENT_DB)


@router.get("/dagent/stats")
async def get_dagent_stats(org_id: str, env_url: str = ""):
    """获取 Dagent 知识库统计信息（通过 HTTP API）"""
    import aiohttp

    # 使用默认生产环境 URL
    base_url = (env_url or "https://dagent.d-robotics.cc").rstrip("/")

    headers = {
        "Content-Type": "application/json",
        "org-id": org_id,
        "d-user-id": "test",
    }

    try:
        async with aiohttp.ClientSession(headers=headers) as session:
            # 获取文件列表
            page = 1
            page_size = 100
            total_files = 0
            total_paragraphs = 0

            while True:
                async with session.post(
                    f"{base_url}/dagent/knowledge/file/page",
                    json={"current": page, "page_size": page_size, "org_id": org_id},
                    timeout=aiohttp.ClientTimeout(total=15),
                ) as resp:
                    if resp.status != 200:
                        break
                    data = await resp.json()
                    files = data.get("data", {}).get("list", [])
                    if not files:
                        break

                    total_files += len(files)

                    # 获取每个文件的切片数
                    for f in files:
                        try:
                            async with session.post(
                                f"{base_url}/dagent/knowledge/chunk/page",
                                json={"file_id": f["id"], "org_id": org_id, "page": 1, "page_size": 1},
                                timeout=aiohttp.ClientTimeout(total=10),
                            ) as cr:
                                if cr.status == 200:
                                    cd = await cr.json()
                                    total_paragraphs += cd.get("data", {}).get("total", 0)
                        except Exception:
                            pass

                    if len(files) < page_size:
                        break
                    page += 1

            return {"status": 0, "data": {
                "file_count": total_files,
                "paragraph_count": total_paragraphs,
                "total_images": 0,
                "paragraphs_with_pic_text": 0,
                "paragraphs_with_question": 0,
            }}
    except Exception as e:
        print(f"[get_dagent_stats] Error: {e}")
        return {"status": 0, "data": {}}


@router.get("/dagent/files")
async def list_dagent_files(org_id: str, env_url: str = ""):
    """列出 Dagent 中某组织下已处理完成的文件（通过 HTTP API）"""
    import aiohttp

    base_url = (env_url or "https://dagent.d-robotics.cc").rstrip("/")

    headers = {
        "Content-Type": "application/json",
        "org-id": org_id,
        "d-user-id": "test",
    }

    all_files = []

    try:
        async with aiohttp.ClientSession(headers=headers) as session:
            page = 1
            page_size = 100

            while True:
                async with session.post(
                    f"{base_url}/dagent/knowledge/file/page",
                    json={"current": page, "page_size": page_size, "org_id": org_id},
                    timeout=aiohttp.ClientTimeout(total=15),
                ) as resp:
                    if resp.status != 200:
                        break
                    data = await resp.json()
                    files = data.get("data", {}).get("list", [])
                    if not files:
                        break

                    for f in files:
                        all_files.append({
                            "id": f.get("id"),
                            "file_name": f.get("file_name"),
                            "file_type": f.get("file_type"),
                            "file_clean_status": f.get("file_clean_status", "").lower(),
                            "file_bytes": f.get("file_bytes", 0),
                            "create_time": f.get("create_time"),
                        })

                    if len(files) < page_size:
                        break
                    page += 1

        return {"status": 0, "data": all_files}
    except Exception as e:
        print(f"[list_dagent_files] Error: {e}")
        return {"status": 0, "data": []}


@router.get("/dagent/tree")
async def get_dagent_tree(org_id: str, env_url: str = ""):
    """
    获取知识库的层级树形结构
    结构：大章节 -> 小章节 -> 文件
    """
    import aiohttp
    import asyncio

    base_url = (env_url or "https://dagent.d-robotics.cc").rstrip("/")

    headers = {
        "Content-Type": "application/json",
        "org-id": org_id,
        "d-user-id": "test",
    }

    try:
        async with aiohttp.ClientSession(headers=headers) as session:
            page = 1
            all_files = []

            while True:
                async with session.post(
                    f"{base_url}/dagent/knowledge/file/page",
                    json={"current": page, "page_size": 100, "org_id": org_id},
                    timeout=aiohttp.ClientTimeout(total=15),
                ) as resp:
                    if resp.status != 200:
                        break
                    data = await resp.json()
                    files = data.get("data", {}).get("list", [])
                    if not files:
                        break

                    for f in files:
                        all_files.append(f)

                    if len(files) < 100:
                        break
                    page += 1

            # 并发获取每个文件的 chunk 总数（page_size=1 只拿 total）
            sem = asyncio.Semaphore(20)

            async def fetch_chunk_count(file_id: str) -> int:
                async with sem:
                    try:
                        async with session.post(
                            f"{base_url}/dagent/knowledge/chunk/page",
                            json={"file_id": file_id, "org_id": org_id, "page": 1, "page_size": 1},
                            timeout=aiohttp.ClientTimeout(total=10),
                        ) as cr:
                            if cr.status == 200:
                                cdata = await cr.json()
                                return cdata.get("data", {}).get("total", 0)
                    except Exception:
                        pass
                    return 0

            chunk_counts = await asyncio.gather(
                *[fetch_chunk_count(f.get("id")) for f in all_files]
            )

            # 解析文件路径并构建列表
            parsed_files = []
            for i, f in enumerate(all_files):
                file_name = f.get("file_name", "")
                parts = file_name.split("/")
                if len(parts) >= 2:
                    major_chapter = parts[0]
                    minor_chapter = "/".join(parts[:-1]) if len(parts) > 2 else parts[0]
                    file_name_only = parts[-1]
                else:
                    major_chapter = "默认章节"
                    minor_chapter = "默认章节"
                    file_name_only = file_name

                parsed_files.append({
                    "id": f.get("id"),
                    "file_name": file_name_only,
                    "full_path": file_name,
                    "file_type": f.get("file_type", ""),
                    "file_clean_status": f.get("file_clean_status", "").lower(),
                    "major_chapter": major_chapter,
                    "minor_chapter": minor_chapter,
                    "chunk_count": chunk_counts[i],
                })

            # 构建树形结构
            tree = {}
            for f in parsed_files:
                major = f["major_chapter"]
                minor = f["minor_chapter"]

                if major not in tree:
                    tree[major] = {
                        "key": f"major:{major}",
                        "title": major,
                        "type": "major_chapter",
                        "children": {}
                    }

                if minor not in tree[major]["children"]:
                    tree[major]["children"][minor] = {
                        "key": f"minor:{minor}",
                        "title": minor.split("/")[-1] if "/" in minor else minor,
                        "full_path": minor,
                        "type": "minor_chapter",
                        "children": []
                    }

                tree[major]["children"][minor]["children"].append({
                    "key": f"file:{f['id']}",
                    "title": f["file_name"],
                    "type": "file",
                    "file_id": f["id"],
                    "file_type": f["file_type"],
                    "status": f["file_clean_status"],
                    "chunk_count": f["chunk_count"],
                })

            result = []
            for major_name, major_node in tree.items():
                major_children = []
                for minor_name, minor_node in major_node["children"].items():
                    minor_children = sorted(minor_node["children"], key=lambda x: x["title"])
                    major_children.append({
                        **{k: v for k, v in minor_node.items() if k != "children"},
                        "children": minor_children
                    })

                result.append({
                    "key": major_node["key"],
                    "title": major_node["title"],
                    "type": "major_chapter",
                    "children": sorted(major_children, key=lambda x: x["title"])
                })

            return {"status": 0, "data": sorted(result, key=lambda x: x["title"])}

    except Exception as e:
        import traceback
        print(f"[get_dagent_tree] Error: {e}")
        print(traceback.format_exc())
        return {"status": 1, "message": str(e), "data": []}


@router.post("/task/from-dagent")
async def create_task_from_dagent(
    org_id: str = Form(...),
    env_url: str = Form(""),
    name: str = Form(""),
    judge_config_id: str = Form(...),
    file_ids: str = Form(""),
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
        env_url=env_url,
    ))
    return {"status": 0, "data": {"id": task_id}}


# ── 内部：后台任务 ─────────────────────────────────────────────────────────────


def _dedupe_paragraphs_by_chunk_id(paragraphs: list[dict]) -> list[dict]:
    """按 chunk id 去重，保留首次出现顺序（避免 API 重复页导致重复生成）。"""
    seen: set[str] = set()
    out: list[dict] = []
    dup = 0
    for p in paragraphs:
        cid = (p.get("id") or "").strip()
        if cid:
            if cid in seen:
                dup += 1
                continue
            seen.add(cid)
        out.append(p)
    if dup:
        print(f"[_dedupe_paragraphs_by_chunk_id] removed {dup} duplicate chunk rows")
    return out


def _merge_paragraphs_by_chunk_id(primary: list[dict], extra: list[dict]) -> list[dict]:
    """把 extra 中尚未出现在 primary 的 chunk 并入（按 id）。"""
    seen = {(p.get("id") or "").strip() for p in primary if (p.get("id") or "").strip()}
    merged = list(primary)
    for p in extra:
        cid = (p.get("id") or "").strip()
        if cid and cid in seen:
            continue
        if cid:
            seen.add(cid)
        merged.append(p)
    return merged


async def _fetch_paragraphs(org_id: str, file_id_list: list[str], env_url: str = "") -> list[dict]:
    """从 Dagent HTTP API 提取段落数据

    Args:
        file_id_list: 指定要处理的文件ID列表，如果为空则处理所有文件
    """
    import aiohttp

    base_url = (env_url or "https://dagent.d-robotics.cc").rstrip("/")

    headers = {
        "Content-Type": "application/json",
        "org-id": org_id,
        "d-user-id": "test",
    }

    all_paragraphs = []

    # 单个文件的切片数上限（防止 API 忽略 file_id 返回全库切片）；过小会整文件跳过
    MAX_CHUNKS_PER_FILE = 50000
    MAX_RETRIES = 5  # 分页触顶 / 网络抖动时多试几次
    PAGE_SIZE = 100

    try:
        async with aiohttp.ClientSession(headers=headers) as session:
            # 确定要处理的文件列表
            files_to_process = []

            if file_id_list:
                print(f"[_fetch_paragraphs] Processing {len(file_id_list)} user-selected files")
                files_to_process = [{"id": fid, "file_name": ""} for fid in file_id_list]
            else:
                print(f"[_fetch_paragraphs] Fetching file list...")
                page = 1
                all_files = []

                while True:
                    async with session.post(
                        f"{base_url}/dagent/knowledge/file/page",
                        json={"current": page, "page_size": 100, "org_id": org_id},
                        timeout=aiohttp.ClientTimeout(total=15),
                    ) as resp:
                        if resp.status != 200:
                            break
                        data = await resp.json()
                        files = data.get("data", {}).get("list", [])
                        if not files:
                            break
                        all_files.extend(files)
                        if len(files) < 100:
                            break
                        page += 1

                print(f"[_fetch_paragraphs] Total files available: {len(all_files)}, will process all")
                files_to_process = all_files

            # 获取每个文件的切片
            total_files = len(files_to_process)
            for idx, f in enumerate(files_to_process):
                file_id = f.get("id") if isinstance(f, dict) else f
                file_name = f.get("file_name", "") if isinstance(f, dict) else ""

                if idx % 10 == 0:
                    print(f"[_fetch_paragraphs] Processing file {idx+1}/{total_files}: {file_id[:20]}...")

                # 先用 page_size=1 探测该文件的 total，验证 API 是否正确过滤
                expected_total = None
                for attempt in range(MAX_RETRIES):
                    try:
                        async with session.post(
                            f"{base_url}/dagent/knowledge/chunk/page",
                            json={"file_id": file_id, "org_id": org_id, "page": 1, "page_size": 1},
                            timeout=aiohttp.ClientTimeout(total=15),
                        ) as resp:
                            if resp.status != 200:
                                print(f"[_fetch_paragraphs] Probe failed for {file_id[:20]}: HTTP {resp.status}")
                                await asyncio.sleep(2 ** attempt)
                                continue
                            probe_data = await resp.json()
                            expected_total = probe_data.get("data", {}).get("total", 0)
                    except Exception as e:
                        print(f"[_fetch_paragraphs] Probe error for {file_id[:20]}: {e}")
                        await asyncio.sleep(2 ** attempt)
                        continue

                    if expected_total is not None and expected_total <= MAX_CHUNKS_PER_FILE:
                        break
                    elif expected_total is not None and expected_total > MAX_CHUNKS_PER_FILE:
                        print(f"[_fetch_paragraphs] WARNING: file {file_id[:20]} returned total={expected_total}, "
                              f"likely API bug (file_id ignored). Retrying ({attempt+1}/{MAX_RETRIES})...")
                        expected_total = None
                        await asyncio.sleep(3 * (attempt + 1))

                if expected_total is None or expected_total > MAX_CHUNKS_PER_FILE:
                    print(f"[_fetch_paragraphs] SKIPPING file {file_id[:20]} ({file_name}): "
                          f"total={expected_total} exceeds limit after {MAX_RETRIES} retries")
                    continue

                if expected_total == 0:
                    continue

                # 正式分页拉取：不得以「已收集数 >= API total」提前停——total 常低于真实切片数，会少拉约一页～数页。
                # max_pages 给足余量；仅当末页 < PAGE_SIZE 或返回空 list 时视为自然结束。
                for fetch_attempt in range(MAX_RETRIES):
                    slack = 80 + fetch_attempt * 60
                    max_pages = min(
                        2000,
                        max(50, (expected_total + PAGE_SIZE - 1) // PAGE_SIZE + slack),
                    )
                    page = 1
                    file_chunks = []
                    fetch_ok = True
                    foreign_count = 0
                    ended_normally = False  # 空页或末页不满 PAGE_SIZE

                    while page <= max_pages:
                        try:
                            async with session.post(
                                f"{base_url}/dagent/knowledge/chunk/page",
                                json={
                                    "file_id": file_id,
                                    "org_id": org_id,
                                    "page": page,
                                    "page_size": PAGE_SIZE,
                                },
                                timeout=aiohttp.ClientTimeout(total=30),
                            ) as resp:
                                if resp.status != 200:
                                    fetch_ok = False
                                    break
                                data = await resp.json()

                                chunks = data.get("data", {}).get("list", [])
                                if not chunks:
                                    ended_normally = True
                                    break

                                page_foreign = 0
                                for c in chunks:
                                    chunk_fid = c.get("file_id", "")
                                    if chunk_fid and chunk_fid != file_id:
                                        foreign_count += 1
                                        page_foreign += 1
                                        continue
                                    # large_paragraph_llm_summary：后端大段压缩后的摘要，常与 paragraph_context 二选一存在；
                                    # 若不映射，大量切片会落入「无正文」→ 生成阶段恒返回 0 题。
                                    _ctx = (
                                        c.get("active_paragraph_context")
                                        or c.get("paragraph_context")
                                        or c.get("active_context")
                                        or ""
                                    )
                                    _llm_sum = (c.get("large_paragraph_llm_summary") or "").strip()
                                    _para_sum = (c.get("paragraph_summary") or "").strip()
                                    file_chunks.append({
                                        "id": c.get("id"),
                                        "file_id": file_id,
                                        "file_name": file_name or c.get("file_name", ""),
                                        "headers": c.get("headers", ""),
                                        "paragraph_context": _ctx or _llm_sum,
                                        "paragraph_img_num": c.get("paragraph_img_num", 0),
                                        "paragraph_pic_semantics_context": c.get("paragraph_pic_semantics_context", ""),
                                        "paragraph_question": c.get("paragraph_question", ""),
                                        "paragraph_summary": _para_sum or _llm_sum,
                                        "paragraph_keywords": c.get("paragraph_keywords", ""),
                                    })

                                if len(chunks) < PAGE_SIZE:
                                    ended_normally = True
                                    break
                                if page_foreign > len(chunks) * 0.5:
                                    print(
                                        f"[_fetch_paragraphs] Page {page}: high foreign ratio "
                                        f"{page_foreign}/{len(chunks)} for file {file_id[:20]}, continuing"
                                    )
                                page += 1
                        except Exception as e:
                            print(f"[_fetch_paragraphs] Error fetching chunks for file {file_id[:20]}: {e}")
                            fetch_ok = False
                            break

                    if foreign_count > 0:
                        print(
                            f"[_fetch_paragraphs] File {file_id[:20]}: filtered {foreign_count} foreign, "
                            f"kept {len(file_chunks)}"
                        )

                    if not fetch_ok:
                        if fetch_attempt < MAX_RETRIES - 1:
                            print(
                                f"[_fetch_paragraphs] File {file_id[:20]}: fetch error, "
                                f"retry ({fetch_attempt + 1}/{MAX_RETRIES})..."
                            )
                            file_chunks = []
                            await asyncio.sleep(3 * (fetch_attempt + 1))
                            continue
                        break

                    if ended_normally:
                        if expected_total and len(file_chunks) < expected_total:
                            print(
                                f"[_fetch_paragraphs] File {file_id[:20]}: EOF kept={len(file_chunks)} "
                                f"vs API total={expected_total} (often foreign rows in total)"
                            )
                        break

                    # 未自然结束：多半触达 max_pages 且最后一页仍为满页，继续扩页重试
                    if fetch_attempt < MAX_RETRIES - 1:
                        print(
                            f"[_fetch_paragraphs] File {file_id[:20]}: page cap hit "
                            f"(last_page={page - 1}, max_pages={max_pages}, kept={len(file_chunks)}), "
                            f"retry ({fetch_attempt + 1}/{MAX_RETRIES})..."
                        )
                        file_chunks = []
                        await asyncio.sleep(3 * (fetch_attempt + 1))
                        continue

                    print(
                        f"[_fetch_paragraphs] WARNING: file {file_id[:20]} still not EOF after "
                        f"{MAX_RETRIES} attempts; accepting {len(file_chunks)} chunks"
                    )
                    break

                if file_chunks:
                    all_paragraphs.extend(file_chunks)

            all_paragraphs = _dedupe_paragraphs_by_chunk_id(all_paragraphs)
            print(f"[_fetch_paragraphs] Total paragraphs fetched: {len(all_paragraphs)} from {total_files} files")
            return all_paragraphs
    except Exception as e:
        import traceback
        print(f"[_fetch_paragraphs] Error: {e}")
        print(f"[_fetch_paragraphs] Traceback: {traceback.format_exc()}")
        return []


def _extract_json_array(text: str) -> Optional[list]:
    """容错解析 LLM 返回的 JSON 数组。

    策略依次尝试：
    1) 直接 json.loads 整个响应
    2) 抠出 ```...``` 或 ```json ... ``` 代码块再 loads
    3) 以第一个 `[` 为起点，按括号配平找到对应 `]`（跳过字符串内的括号）
    4) 若因截断未闭合，尝试在最后一个完整对象 `}` 处强制补 `]` 再 loads

    任一成功即返回 list；全部失败返回 None。
    """
    if not text:
        return None
    stripped = text.strip()

    # 1) 整体 loads
    try:
        data = json.loads(stripped)
        if isinstance(data, list):
            return data
    except Exception:
        pass

    # 2) 代码块
    block = re.search(r"```(?:json)?\s*(.*?)```", stripped, re.DOTALL | re.IGNORECASE)
    if block:
        try:
            data = json.loads(block.group(1).strip())
            if isinstance(data, list):
                return data
        except Exception:
            pass

    # 3) 括号配平（跳过字符串内的括号）
    start = stripped.find("[")
    if start == -1:
        return None

    depth = 0
    in_str = False
    escape = False
    end = -1
    for i in range(start, len(stripped)):
        ch = stripped[i]
        if escape:
            escape = False
            continue
        if ch == "\\":
            escape = True
            continue
        if ch == '"':
            in_str = not in_str
            continue
        if in_str:
            continue
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                end = i
                break

    if end != -1:
        candidate = stripped[start:end + 1]
        try:
            data = json.loads(candidate)
            if isinstance(data, list):
                return data
        except Exception:
            pass

    # 4) 截断恢复：找最后一个完整对象的 `}`，强制补 `]`
    tail_brace = stripped.rfind("}")
    if tail_brace > start:
        candidate = stripped[start:tail_brace + 1] + "]"
        try:
            data = json.loads(candidate)
            if isinstance(data, list):
                return data
        except Exception:
            pass

    return None


def _parse_quality_score(raw) -> float:
    """模型自评分数：缺省/非法时用 0.8，避免 float(None) 整段失败；限制在 [0,1]。"""
    if raw is None:
        return 0.8
    try:
        v = float(raw)
    except (TypeError, ValueError):
        return 0.8
    return max(0.0, min(1.0, v))


async def _call_llm_once(
    session, base_url: str, payload: dict, timeout_s: int
) -> tuple[Optional[str], Optional[str]]:
    """单次调用 LLM，返回 (content, error_str)。"""
    try:
        async with session.post(
            f"{base_url}/chat/completions",
            json=payload,
            timeout=aiohttp.ClientTimeout(total=timeout_s),
        ) as resp:
            if resp.status != 200:
                body = (await resp.text())[:500]
                return None, f"HTTP {resp.status}: {body}"
            data = await resp.json()
        content = data["choices"][0]["message"]["content"].strip()
        return content, None
    except Exception as e:
        return None, str(e)


async def _generate_questions_for_paragraph(
    para: dict, cfg: dict, n: int, include_multimodal: bool,
    existing_questions: list[str] = None,  # 已有的问题列表，用于避免重复
) -> list[dict]:
    """为单个段落生成问答，支持传入已有问题避免重复。

    改进：
    - 引入容错 JSON 抽取（_extract_json_array），避免贪婪正则漏解析/截断直接丢题。
    - 增加重试与自适应降 n：单次失败后指数退避重试；若怀疑是 max_tokens 截断，下一次把 n 折半。
    - 复用 ClientSession（在此函数内同次生成共享；跨调用暂未共享以保持接口稳定）。
    - 放宽「已有历史问题」的硬约束，改为软参考，避免第 3/4 轮模型大量拒答。
    """
    base_url = cfg.get("base_url", "").rstrip("/")
    api_key = cfg.get("api_key", "")
    model = cfg.get("model", "gpt-4o-mini")

    context_plain = (para.get("paragraph_context") or "").strip()
    pic_semantics = (para.get("paragraph_pic_semantics_context") or "").strip()
    seed_question = (para.get("paragraph_question") or "").strip()
    headers = (para.get("headers") or "").strip()
    summary = (para.get("paragraph_summary") or "").strip()
    keywords = (para.get("paragraph_keywords") or "").strip()
    has_image = bool(pic_semantics and para.get("paragraph_img_num", 0) > 0)

    text = context_plain
    if not text:
        text = summary
    if not text and seed_question:
        text = seed_question
    if not text and has_image and include_multimodal and pic_semantics:
        text = pic_semantics[:2500]
    if not text and keywords:
        text = f"关键词：\n{keywords[:1500]}"
    if not text and headers:
        text = (
            f"（该切片缺少正文/摘要，仅章节路径如下；请基于路径生成 {n} 个简短、可检索的技术问题，"
            f"答案可写「需结合全文」类占位但问题须具体）\n{headers}"
        )

    if not text:
        return []

    # 构建 prompt（正文为空但用图片语义作主内容时不再重复插入图片块）
    pic_section = ""
    if has_image and include_multimodal and pic_semantics and context_plain:
        pic_section = f"""
**图片语义描述（图片已由 AI 识别）：**
{pic_semantics[:800]}
"""

    seed_section = ""
    if seed_question:
        seed_section = f"\n**已有种子问题（请避免重复，可从不同角度扩展）：** {seed_question}"

    # 已有问题列表（来自循环任务的历史问题）
    # 放宽为「风格参考」——模型在历史 10+ 条强约束下常直接返回空数组，导致循环第 3/4 轮整轮 0 题。
    existing_section = ""
    if existing_questions:
        sample_existing = existing_questions[:5]
        existing_section = (
            "\n**该段落的历史问题（供参考，尽量换角度/换措辞，但不必完全不同）：**\n"
        )
        for i, eq in enumerate(sample_existing, 1):
            existing_section += f"{i}. {eq}\n"

    def _build_prompt(ask_n: int) -> str:
        return f"""你是一个技术文档问答生成专家。基于以下内容生成 {ask_n} 个测试问题。

**章节路径：** {headers}

**文本内容：**
{text[:2500]}
{pic_section}{seed_section}{existing_section}

**要求：**
1. 问题必须能从该章节内容直接回答
2. 覆盖关键知识点，避免过于简单的是非题
3. 如果有图片语义描述，至少生成 1 个图文结合的问题（问题中提及"如图所示"、"图中"等）
4. 答案准确，长度适中（1-3 句话）
5. source_chunk 为答案来源的原文片段（50-150 字）
6. has_image 标记该问题是否依赖图像信息
7. quality_score 为质量评估（0-1）

**输出格式：严格只输出一个合法 JSON 数组，不要额外解释、不要代码块标记。**
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

    MAX_ATTEMPTS = 3
    TIMEOUT_S = 120
    cur_n = n

    async with aiohttp.ClientSession(headers=headers_http) as session:
        for attempt in range(MAX_ATTEMPTS):
            prompt = _build_prompt(cur_n)
            payload = {
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.3,
            }

            content, err = await _call_llm_once(session, base_url, payload, TIMEOUT_S)
            if err:
                is_rate_limit = "429" in err or "Rate limit" in err or "rate limit" in err
                is_budget = "400" in err and ("Budget" in err or "budget" in err or "budget_exceeded" in err)
                _log(
                    f"[_generate_questions] Attempt {attempt + 1}/{MAX_ATTEMPTS} failed "
                    f"for headers={headers[:50]}: {err[:200]}"
                )
                # 限流或预算超限：长退避；其他错误：短退避
                if attempt < MAX_ATTEMPTS - 1:
                    if is_budget:
                        wait_s = 300 + 300 * attempt  # 预算超限：5min, 10min, 15min
                        _log(f"[_generate_questions] Budget exceeded, backing off {wait_s}s (wait for reset)")
                    elif is_rate_limit:
                        wait_s = 30 + 15 * attempt  # 429: 30s, 45s, 60s
                        _log(f"[_generate_questions] Rate limit detected, backing off {wait_s}s")
                    else:
                        wait_s = 2 + 2 * attempt  # 其他: 2s, 4s, 6s
                    await asyncio.sleep(wait_s)
                continue

            questions = _extract_json_array(content)
            if not questions:
                # 看起来像被截断：响应末尾既无 `]` 又无 `}`，下一轮降 n
                looks_truncated = not content.rstrip().endswith(("]", "}"))
                _log(
                    f"[_generate_questions] Attempt {attempt + 1}/{MAX_ATTEMPTS}: "
                    f"JSON parse failed for headers={headers[:50]} "
                    f"(len={len(content)}, truncated={looks_truncated})"
                )
                _log(f"[_generate_questions] Raw response preview: {content[:300]}...{content[-300:]}")
                if looks_truncated and cur_n > 1:
                    cur_n = max(1, cur_n // 2)
                if attempt < MAX_ATTEMPTS - 1:
                    await asyncio.sleep(1.0 * (attempt + 1))
                continue

            result = []
            for q in questions:
                if isinstance(q, dict) and q.get("question") and q.get("answer"):
                    result.append({
                        "question": str(q["question"]).strip(),
                        "answer": str(q["answer"]).strip(),
                        "source_chunk": str(q.get("source_chunk", "")).strip(),
                        "has_image": bool(q.get("has_image", False)),
                        "quality_score": _parse_quality_score(q.get("quality_score")),
                        "source_image_desc": pic_semantics[:300] if q.get("has_image") else "",
                    })

            if result:
                _log(
                    f"[_generate_questions] Generated {len(result)} questions for "
                    f"headers={headers[:50]} (attempt {attempt + 1}, asked={cur_n})"
                )
                return result

            _log(
                f"[_generate_questions] Attempt {attempt + 1}/{MAX_ATTEMPTS}: "
                f"JSON parsed but 0 valid items for headers={headers[:50]} "
                f"(raw count={len(questions)})"
            )
            if attempt < MAX_ATTEMPTS - 1:
                await asyncio.sleep(1.0 * (attempt + 1))

    _log(f"[_generate_questions] All {MAX_ATTEMPTS} attempts exhausted for headers={headers[:50]}")
    return []


async def _run_dagent_task(
    task_id: str,
    org_id: str,
    file_id_list: list[str],
    judge_config_id: str,
    questions_per_section: int,
    quality_threshold: float,
    include_multimodal: bool,
    section_existing_questions: dict[str, list[str]] = None,  # {section_path: [question1, question2, ...]}
    stop_check: callable = None,  # Optional stop check function
    pause_check: callable = None,  # Optional async pause check function
    env_url: str = "",  # Dagent environment URL
    expected_chunk_count: Optional[int] = None,  # 批次规划切片总数；与拉取结果对齐校验
):
    """
    运行 Dagent QA 生成任务

    Args:
        section_existing_questions: 各 section 下已有的问题列表，用于避免重复生成
        stop_check: 可选的停止检查函数，返回True时应停止任务
        env_url: Dagent 环境 URL
        expected_chunk_count: 与 chunk_batches_plan 中本批 chunk_count 一致时，强制校验去重后的拉取条数
    """
    import traceback
    section_existing_questions = section_existing_questions or {}

    print(f"[_run_dagent_task] Starting task {task_id}, org_id={org_id}, file_id_list={len(file_id_list)} files, env_url={env_url}")

    try:
        # 1. 先更新状态为 running，让用户知道任务已开始
        async with get_db() as db:
            await db.execute(
                "UPDATE qa_gen_task SET status='running', total=0, progress=0 WHERE id=?",
                (task_id,),
            )
            await db.commit()

        # 2. 提取段落（可多次拉取合并，直至满足 expected_chunk_count）
        print(f"[_run_dagent_task] Fetching paragraphs...")
        paragraphs = await _fetch_paragraphs(org_id, file_id_list, env_url)
        paragraphs = _dedupe_paragraphs_by_chunk_id(paragraphs)
        if expected_chunk_count and len(paragraphs) < expected_chunk_count:
            for refetch_i in range(3):
                short_by = expected_chunk_count - len(paragraphs)
                print(
                    f"[_run_dagent_task] Chunk count {len(paragraphs)} < expected {expected_chunk_count} "
                    f"(short {short_by}), refetch merge attempt {refetch_i + 1}/3"
                )
                more = await _fetch_paragraphs(org_id, file_id_list, env_url)
                paragraphs = _merge_paragraphs_by_chunk_id(paragraphs, more)
                if len(paragraphs) >= expected_chunk_count:
                    break
                await asyncio.sleep(5 * (refetch_i + 1))
        if expected_chunk_count and len(paragraphs) < expected_chunk_count:
            raise RuntimeError(
                f"拉取切片 {len(paragraphs)} 条，少于批次期望 {expected_chunk_count} 条；"
                f"请检查 Dagent chunk/page API、file_ids 是否与 chunk_batches_plan 一致。"
            )
        total = len(paragraphs)
        print(
            f"[_run_dagent_task] Fetched {total} paragraphs"
            + (f" (expected_chunk_count={expected_chunk_count})" if expected_chunk_count else "")
        )
        if expected_chunk_count and total > expected_chunk_count + 5:
            print(
                f"[_run_dagent_task] WARN: fetched {total} > expected {expected_chunk_count} "
                "(plan/API 漂移，仍按已拉取切片全部生成)"
            )

        if total == 0:
            print(f"[_run_dagent_task] No paragraphs found, marking as done")
            async with get_db() as db:
                await db.execute(
                    "UPDATE qa_gen_task SET status='done', finished_at=?, total=0 WHERE id=?",
                    (_now(), task_id),
                )
                await db.commit()
            return

        # 更新总数
        async with get_db() as db:
            await db.execute(
                "UPDATE qa_gen_task SET total=? WHERE id=?",
                (total, task_id),
            )
            await db.commit()

        # 3. 获取 LLM 配置
        _log(f"[_run_dagent_task] Getting LLM config for judge_config_id={judge_config_id}")
        async with get_db() as db:
            cfg_rows = await db.execute_fetchall(
                "SELECT * FROM judge_config WHERE id=?", (judge_config_id,)
            )
        if not cfg_rows:
            raise ValueError("judge_config not found")
        cfg = dict(cfg_rows[0])
        _log(f"[_run_dagent_task] LLM config: {cfg.get('model')}")

        # 3. 并发生成（降低并发到 3，避免触发限流；原 10 在 global_dedup 下压力过大）
        sem = asyncio.Semaphore(3)
        buf_lock = asyncio.Lock()  # 保护 write_buf 的锁
        done = 0
        FLUSH_SIZE = 50
        write_buf = []
        stopped = False

        _log(f"[_run_dagent_task] Starting generation: {total} paragraphs, concurrency=3, flush_size=50")

        total_questions_written = 0
        paragraphs_with_zero_questions = 0

        async def flush_question_buf(buf: list):
            """将缓冲区问题写入 DB，并同步 progress（即使 buf 为空，也需要回写进度，
            否则整轮 0 题的任务 progress 永远停在 0，前端误以为卡死）。"""
            async with get_db() as db2:
                for p, q in buf:
                    qid = _id()
                    status = "approved" if q["quality_score"] >= quality_threshold else "pending"
                    await db2.execute(
                        """INSERT INTO qa_gen_question
                           (id,task_id,section_path,question,reference_answer,source_chunk,
                            quality_score,status,created_at,file_id,file_name,chunk_id,chunk_headers,chunk_content_preview)
                           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (qid, task_id, p["headers"],
                         q["question"], q["answer"], q["source_chunk"],
                         q["quality_score"], status, _now(),
                         p.get("file_id", ""), p.get("file_name", ""),
                         p.get("id", ""), p.get("headers", ""), p.get("paragraph_context", "")[:500]),
                    )
                if buf:
                    from .qa_gen import _sync_approved_count
                    await _sync_approved_count(db2, task_id)
                await db2.execute(
                    "UPDATE qa_gen_task SET progress=? WHERE id=?",
                    (done, task_id),
                )
                await db2.commit()

        async def process_one(para: dict):
            nonlocal done, stopped, total_questions_written, paragraphs_with_zero_questions
            # Check stop condition before processing
            if stop_check and stop_check():
                stopped = True
                return

            # Check pause condition before processing
            if pause_check and await pause_check():
                stopped = True
                return

            async with sem:
                # Check stop condition again before LLM call
                if stop_check and stop_check():
                    stopped = True
                    return

                # Check pause condition again before LLM call
                if pause_check and await pause_check():
                    stopped = True
                    return

                # 获取该 section 下已有的问题列表
                headers = para.get("headers", "")
                existing = section_existing_questions.get(headers, [])

                questions: list = []
                merged_existing = list(existing)
                max_fill_rounds = 4
                consecutive_empty_rounds = 0  # 连续空轮次计数
                max_consecutive_empty = 2     # 最多允许连续2轮为空才终止
                for fill_round in range(max_fill_rounds):
                    need = questions_per_section - len(questions)
                    if need <= 0:
                        break
                    batch = await _generate_questions_for_paragraph(
                        para, cfg, need, include_multimodal,
                        existing_questions=merged_existing,
                    )
                    if not batch:
                        consecutive_empty_rounds += 1
                        if consecutive_empty_rounds >= max_consecutive_empty:
                            # 连续多轮为空才真正终止
                            break
                        # 单轮为空继续尝试下一轮
                        continue
                    # 重置连续空轮次计数
                    consecutive_empty_rounds = 0
                    questions.extend(batch)
                    merged_existing.extend(q["question"] for q in batch)
            async with buf_lock:
                done += 1
                total_questions_written += len(questions)
                if not questions:
                    paragraphs_with_zero_questions += 1
                write_buf.extend([(para, q) for q in questions])

                # 每100个段落打印一次进度
                if done % 100 == 0 or done == total:
                    print(
                        f"[_run_dagent_task] Progress: {done}/{total} ({done*100//total}%) "
                        f"questions={total_questions_written} zero_chunks={paragraphs_with_zero_questions}"
                    )

                # 有足够题目时按 FLUSH_SIZE 落盘；整轮 0 题时也要周期性回写进度（每 100 段一次）
                need_flush = (
                    len(write_buf) >= FLUSH_SIZE
                    or done == total
                    or (done % 100 == 0)
                )
                if need_flush:
                    batch = write_buf.copy()
                    write_buf.clear()
                    await flush_question_buf(batch)

        await asyncio.gather(*[process_one(p) for p in paragraphs])

        # 停止/正常结束前务必刷盘，否则缓冲区里已生成的问题会整批丢失（表现为部分切片无题）
        async with buf_lock:
            if write_buf:
                await flush_question_buf(write_buf)
                write_buf.clear()

        print(
            f"[_run_dagent_task] First pass only (no second pass): paragraphs={total}, "
            f"questions_inserted={total_questions_written}, "
            f"paragraphs_with_zero_questions={paragraphs_with_zero_questions}"
        )

        # Check if stopped early
        if stopped:
            async with get_db() as db:
                await db.execute(
                    "UPDATE qa_gen_task SET status='stopped', finished_at=? WHERE id=?",
                    (_now(), task_id),
                )
                await db.commit()
            return

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
