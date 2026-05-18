"""
测试样例质量检测器。
"""
from .parser import QAPair, Section
from .tester import RecallResult


def check_qa_quality(qa: QAPair) -> dict:
    """
    检查单条问答对的质量。
    返回：{"is_valid": bool, "issues": [str]}
    """
    issues = []

    # 问题完整性
    if len(qa.question) < 5:
        issues.append("问题过短")
    if not qa.question.endswith("？") and not qa.question.endswith("?"):
        issues.append("问题未以问号结尾")

    # 答案完整性
    if len(qa.answer) < 10:
        issues.append("答案过短")

    # 问答一致性（答案中应包含问题的关键词）
    q_words = set(qa.question.replace("？", "").replace("?", "").split())
    a_words = set(qa.answer.split())
    if len(q_words & a_words) == 0:
        issues.append("答案与问题无关键词重叠")

    return {
        "is_valid": len(issues) == 0,
        "issues": issues,
    }


def check_recall_quality(results: list[RecallResult]) -> dict:
    """
    通过召回结果反向验证样例质量。
    返回：{"low_quality": [RecallResult], "suspicious": [RecallResult]}
    """
    low_quality = []
    suspicious = []

    for r in results:
        if r.error or r.is_empty:
            continue

        # 召回相似度极低（< 0.5）
        if r.best_cosine_sim and r.best_cosine_sim < 0.5:
            low_quality.append(r)

        # 召回的文件与预期不符（跨文件召回）
        if r.file_id and r.file_id not in r.retrieved_file_ids:
            suspicious.append(r)

    return {
        "low_quality": low_quality,
        "suspicious": suspicious,
    }


def detect_duplicates(sections: list[Section], threshold: float = 0.9) -> list[tuple[str, str]]:
    """
    检测重复问题（简单基于字符串相似度）。
    返回：[(qid1, qid2), ...]
    """
    from difflib import SequenceMatcher

    all_qa = [(s.section_path, qa) for s in sections for qa in s.qa_pairs]
    duplicates = []

    for i, (path1, qa1) in enumerate(all_qa):
        for path2, qa2 in all_qa[i + 1:]:
            sim = SequenceMatcher(None, qa1.question, qa2.question).ratio()
            if sim > threshold:
                duplicates.append((f"{path1}/{qa1.qid}", f"{path2}/{qa2.qid}"))

    return duplicates
