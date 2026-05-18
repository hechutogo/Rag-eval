"""
语义覆盖率监控模块

基于最近邻距离的语义覆盖率方案：
- 计算新问题与已有问题集的语义距离
- 当平均距离低于阈值时，认为该切片的问题空间已被充分探索
- 用于判断循环测试何时应该停止
"""
import asyncio
import json
import numpy as np
from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass
from datetime import datetime


@dataclass
class SemanticCoverageResult:
    """语义覆盖率结果"""
    chunk_id: str
    total_questions: int
    avg_neighbor_distance: float
    min_neighbor_distance: float
    coverage_score: float  # 0-1，越高表示覆盖越充分
    is_converged: bool
    recommended_action: str  # 'continue', 'stop', 'reduce'


class SemanticCoverageMonitor:
    """
    语义覆盖率监控器

    算法：
    1. 使用embedding表示每个问题的语义
    2. 对每个新问题，计算其与已有问题的最小距离
    3. 当平均最小距离 < threshold时，认为收敛
    """

    def __init__(
        self,
        threshold: float = 0.15,
        min_questions: int = 3,
        max_questions: int = 20,
        embedding_model: str = "text-embedding-3-small",
    ):
        self.threshold = threshold
        self.min_questions = min_questions
        self.max_questions = max_questions
        self.embedding_model = embedding_model
        self._embeddings_cache: Dict[str, List[float]] = {}

    async def _get_embedding(self, text: str, client) -> List[float]:
        """获取文本的embedding"""
        cache_key = hash(text)
        if cache_key in self._embeddings_cache:
            return self._embeddings_cache[cache_key]

        resp = await client.embeddings.create(
            model=self.embedding_model,
            input=text,
        )
        embedding = resp.data[0].embedding
        self._embeddings_cache[cache_key] = embedding
        return embedding

    def _cosine_distance(self, a: List[float], b: List[float]) -> float:
        """计算余弦距离"""
        a_np = np.array(a)
        b_np = np.array(b)
        cos_sim = np.dot(a_np, b_np) / (np.linalg.norm(a_np) * np.linalg.norm(b_np) + 1e-9)
        return 1.0 - cos_sim

    def _calculate_coverage_metrics(
        self,
        embeddings: List[List[float]]
    ) -> Tuple[float, float]:
        """
        计算覆盖率指标

        返回: (平均最近邻距离, 最小最近邻距离)
        """
        if len(embeddings) < 2:
            return 1.0, 1.0  # 问题太少，返回最大距离

        distances = []
        min_distances = []

        for i, emb_i in enumerate(embeddings):
            # 计算与其他所有问题的距离
            other_distances = []
            for j, emb_j in enumerate(embeddings):
                if i != j:
                    dist = self._cosine_distance(emb_i, emb_j)
                    other_distances.append(dist)

            if other_distances:
                min_dist = min(other_distances)
                min_distances.append(min_dist)
                distances.extend(other_distances)

        avg_min_distance = np.mean(min_distances) if min_distances else 1.0
        min_distance = min(min_distances) if min_distances else 1.0

        return avg_min_distance, min_distance

    async def evaluate_chunk_coverage(
        self,
        chunk_id: str,
        questions: List[str],
        client,
    ) -> SemanticCoverageResult:
        """
        评估单个切片的语义覆盖率

        Args:
            chunk_id: 切片ID
            questions: 该切片已有的问题列表
            client: OpenAI客户端用于获取embedding

        Returns:
            SemanticCoverageResult: 覆盖率评估结果
        """
        total = len(questions)

        # 问题数不足
        if total < self.min_questions:
            return SemanticCoverageResult(
                chunk_id=chunk_id,
                total_questions=total,
                avg_neighbor_distance=1.0,
                min_neighbor_distance=1.0,
                coverage_score=0.0,
                is_converged=False,
                recommended_action='continue',
            )

        # 问题数已达上限
        if total >= self.max_questions:
            return SemanticCoverageResult(
                chunk_id=chunk_id,
                total_questions=total,
                avg_neighbor_distance=0.0,
                min_neighbor_distance=0.0,
                coverage_score=1.0,
                is_converged=True,
                recommended_action='stop',
            )

        # 计算embedding
        embeddings = []
        for q in questions:
            emb = await self._get_embedding(q, client)
            embeddings.append(emb)

        # 计算覆盖率指标
        avg_dist, min_dist = self._calculate_coverage_metrics(embeddings)

        # 计算覆盖率分数 (0-1)
        # 距离越小，覆盖率越高
        coverage_score = max(0.0, 1.0 - (avg_dist / self.threshold))

        # 判断是否收敛
        is_converged = avg_dist < self.threshold

        # 推荐动作
        if is_converged:
            recommended_action = 'stop'
        elif total > self.max_questions * 0.8:
            recommended_action = 'reduce'  # 减少生成数量
        else:
            recommended_action = 'continue'

        return SemanticCoverageResult(
            chunk_id=chunk_id,
            total_questions=total,
            avg_neighbor_distance=avg_dist,
            min_neighbor_distance=min_dist,
            coverage_score=coverage_score,
            is_converged=is_converged,
            recommended_action=recommended_action,
        )

    async def evaluate_batch_coverage(
        self,
        chunk_questions: Dict[str, List[str]],
        client,
    ) -> Dict[str, SemanticCoverageResult]:
        """
        评估一批切片的覆盖率

        Args:
            chunk_questions: {chunk_id: [question1, question2, ...]}
            client: OpenAI客户端

        Returns:
            {chunk_id: SemanticCoverageResult}
        """
        results = {}
        for chunk_id, questions in chunk_questions.items():
            result = await self.evaluate_chunk_coverage(chunk_id, questions, client)
            results[chunk_id] = result
        return results

    def get_batch_summary(
        self,
        results: Dict[str, SemanticCoverageResult]
    ) -> Dict:
        """获取批次覆盖率汇总"""
        total_chunks = len(results)
        converged_chunks = sum(1 for r in results.values() if r.is_converged)
        total_questions = sum(r.total_questions for r in results.values())
        avg_coverage = np.mean([r.coverage_score for r in results.values()]) if results else 0.0

        return {
            "total_chunks": total_chunks,
            "converged_chunks": converged_chunks,
            "convergence_rate": converged_chunks / total_chunks if total_chunks > 0 else 0.0,
            "total_questions": total_questions,
            "avg_coverage_score": avg_coverage,
            "should_stop": converged_chunks / total_chunks > 0.9 if total_chunks > 0 else False,
        }


class LoopConvergenceChecker:
    """
    循环任务收敛检查器

    集成到loop_engine中，用于判断是否应该停止循环
    """

    def __init__(self, monitor: SemanticCoverageMonitor):
        self.monitor = monitor

    async def check_convergence(
        self,
        qa_task_id: str,
        client,
    ) -> Tuple[bool, Dict]:
        """
        检查loop任务是否收敛

        Returns:
            (是否收敛, 详细信息)
        """
        # 从数据库获取该任务的所有问题
        from server.models.db import get_db

        chunk_questions = {}
        async with get_db() as db:
            rows = await db.execute_fetchall(
                """SELECT chunk_id, question
                   FROM qa_gen_question
                   WHERE task_id=? AND status='approved' AND chunk_id IS NOT NULL""",
                (qa_task_id,)
            )

            for row in rows:
                chunk_id = row["chunk_id"]
                question = row["question"]
                if chunk_id not in chunk_questions:
                    chunk_questions[chunk_id] = []
                chunk_questions[chunk_id].append(question)

        if not chunk_questions:
            return False, {"reason": "no_questions_yet"}

        # 评估覆盖率
        results = await self.monitor.evaluate_batch_coverage(chunk_questions, client)
        summary = self.monitor.get_batch_summary(results)

        # 判断收敛条件
        should_stop = summary["should_stop"]

        details = {
            "summary": summary,
            "chunk_details": {
                chunk_id: {
                    "questions": r.total_questions,
                    "coverage_score": r.coverage_score,
                    "is_converged": r.is_converged,
                    "action": r.recommended_action,
                }
                for chunk_id, r in results.items()
            },
        }

        return should_stop, details


# 集成到loop_engine的示例代码（供参考）
LOOP_ENGINE_INTEGRATION = '''
# 在 loop_engine.py 中的 _do_run_loop 函数中添加

async def _check_semantic_convergence(
    self,
    qa_task_id: str,
    llm_client,
) -> Tuple[bool, Dict]:
    """检查语义覆盖率是否收敛"""
    from .semantic_coverage import SemanticCoverageMonitor, LoopConvergenceChecker

    monitor = SemanticCoverageMonitor(
        threshold=0.15,
        min_questions=3,
        max_questions=20,
    )
    checker = LoopConvergenceChecker(monitor)

    should_stop, details = await checker.check_convergence(qa_task_id, llm_client)
    return should_stop, details

# 在每轮结束时调用
should_stop, convergence_details = await self._check_semantic_convergence(
    qa_task_id, llm_client
)
if should_stop:
    print(f"[Loop] Semantic convergence reached, stopping...")
    break
'''


# 命令行工具
async def main():
    """分析当前任务的语义覆盖率"""
    import argparse

    parser = argparse.ArgumentParser(description="语义覆盖率分析工具")
    parser.add_argument("--task-id", help="QA生成任务ID")
    parser.add_argument("--threshold", type=float, default=0.15, help="收敛阈值")
    parser.add_argument("--base-url", default="https://api.openai.com/v1", help="API base URL")
    parser.add_argument("--api-key", required=True, help="API key")

    args = parser.parse_args()

    from openai import AsyncOpenAI

    client = AsyncOpenAI(
        base_url=args.base_url,
        api_key=args.api_key,
    )

    monitor = SemanticCoverageMonitor(threshold=args.threshold)
    checker = LoopConvergenceChecker(monitor)

    if args.task_id:
        should_stop, details = await checker.check_convergence(args.task_id, client)
        print(json.dumps(details, indent=2, ensure_ascii=False))
        print(f"\n建议: {'停止' if should_stop else '继续'}生成问题")
    else:
        print("请提供 --task-id 参数")


if __name__ == "__main__":
    asyncio.run(main())
