import math


def hit_rate(retrieved_ids: list[str], relevant_ids: list[str]) -> float:
    if not relevant_ids:
        return 0.0
    return 1.0 if any(r in set(relevant_ids) for r in retrieved_ids) else 0.0


def mrr(retrieved_ids: list[str], relevant_ids: list[str]) -> float:
    if not relevant_ids:
        return 0.0
    relevant_set = set(relevant_ids)
    for rank, rid in enumerate(retrieved_ids, start=1):
        if rid in relevant_set:
            return 1.0 / rank
    return 0.0


def ndcg(retrieved_ids: list[str], relevant_ids: list[str], k: int = 10) -> float:
    if not relevant_ids:
        return 0.0
    relevant_set = set(relevant_ids)
    top_k = retrieved_ids[:k]
    dcg = sum(
        1.0 / math.log2(i + 2)
        for i, rid in enumerate(top_k)
        if rid in relevant_set
    )
    ideal_hits = min(len(relevant_set), k)
    idcg = sum(1.0 / math.log2(i + 2) for i in range(ideal_hits))
    return round(dcg / idcg, 4) if idcg > 0 else 0.0
