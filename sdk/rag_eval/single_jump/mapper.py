"""
将 MD 文件中的 doc_name 映射到 dagent 知识库的 file_id。

映射规则（优先级从高到低）：
1. 精确匹配：file_name == doc_name
2. 包含匹配：file_name 包含 doc_name
3. 模糊匹配：doc_name 的关键词在 file_name 中
"""
import aiohttp
from difflib import SequenceMatcher


class FileMapper:
    def __init__(self, env_url: str, org_id: str, d_user_id: str = "test"):
        self.env_url = env_url.rstrip("/")
        self.org_id = org_id
        self.headers = {
            "Content-Type": "application/json",
            "d-user-id": d_user_id,
            "org-id": org_id,
        }
        self.files: list[dict] = []

    async def load_files(self):
        """拉取知识库所有文件列表"""
        url = f"{self.env_url}/dagent/knowledge/file/page"
        all_files = []
        page = 1
        page_size = 100

        async with aiohttp.ClientSession(headers=self.headers) as session:
            while True:
                payload = {
                    "current": page,
                    "page_size": page_size,
                    "org_id": self.org_id,
                }
                async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                    resp.raise_for_status()
                    data = await resp.json()
                    file_list = data.get("data", {}).get("list", [])
                    if not file_list:
                        break
                    all_files.extend(file_list)
                    if len(file_list) < page_size:
                        break
                    page += 1

        self.files = all_files
        return len(all_files)

    def map_section_to_file(self, section_path: str) -> dict | None:
        """
        将 section_path（如 "linux_development / bsp_develop"）映射到 file_id。

        文件名格式：linux_development/bsp_develop.md
        section_path 格式：linux_development / bsp_develop

        匹配规则（优先级从高到低）：
        1. 路径精确匹配：把 section_path 的空格去掉后与文件名（去扩展名）完全一致
        2. 路径包含匹配：文件名（去扩展名）包含 section_path 的规范化形式
        3. 末段精确匹配：文件名末段（去扩展名）== section_path 最后一段
        4. 模糊匹配
        """
        if not self.files:
            return None

        # 规范化 section_path：去空格，转小写，斜杠统一
        # "linux_development / bsp_develop" -> "linux_development/bsp_develop"
        normalized = "/".join(p.strip() for p in section_path.split("/")).lower()
        doc_name = section_path.split("/")[-1].strip().lower()

        # 1. 路径精确匹配（去扩展名）
        for f in self.files:
            fname_base = f["file_name"].rsplit(".", 1)[0].lower()
            if fname_base == normalized:
                return {"file_id": f["id"], "file_name": f["file_name"], "match_type": "exact"}

        # 2. 路径包含匹配
        for f in self.files:
            fname_base = f["file_name"].rsplit(".", 1)[0].lower()
            if normalized in fname_base or fname_base in normalized:
                return {"file_id": f["id"], "file_name": f["file_name"], "match_type": "path_contains"}

        # 3. 末段精确匹配
        for f in self.files:
            fname_base = f["file_name"].rsplit(".", 1)[0].lower()
            fname_last = fname_base.split("/")[-1]
            if fname_last == doc_name:
                return {"file_id": f["id"], "file_name": f["file_name"], "match_type": "basename"}

        # 4. 模糊匹配（相似度 > 0.6）
        best_match = None
        best_score = 0.6
        for f in self.files:
            fname_base = f["file_name"].rsplit(".", 1)[0].lower()
            score = SequenceMatcher(None, normalized, fname_base).ratio()
            if score > best_score:
                best_score = score
                best_match = {
                    "file_id": f["id"],
                    "file_name": f["file_name"],
                    "match_type": "fuzzy",
                    "score": round(score, 3),
                }

        return best_match

    def map_doc_to_file(self, doc_name: str) -> dict | None:
        """向后兼容，内部调用 map_section_to_file"""
        return self.map_section_to_file(doc_name)
