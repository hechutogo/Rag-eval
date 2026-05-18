"""
多跳召回测试 CLI。

用法：
  python -m rag_eval.multi_hop.cli \\
    --env-url https://your-dagent-env.com \\
    --org-id cd6e121594984516... \\
    --qa-file path/to/multi_hop.md \\
    --top-k 10 \\
    --concurrency 5 \\
    --output report.json
"""
import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from rag_eval.multi_hop.parser import parse_multi_hop_file
from rag_eval.multi_hop.tester import MultiHopTester
from rag_eval.multi_hop.report import build_report
from rag_eval.single_jump.mapper import FileMapper


async def run(args):
    # 1. 解析 MD 文件
    print(f"[1/4] 解析多跳问答文件: {args.qa_file}")
    case = parse_multi_hop_file(args.qa_file)
    qa_pairs = case.qa_pairs
    if not qa_pairs:
        print("ERROR: 未解析到任何多跳问答对，请检查文件格式")
        sys.exit(1)
    print(f"      共 {len(qa_pairs)} 个问题，"
          f"hop 数分布: {_hop_dist(qa_pairs)}")

    # 2. 拉取知识库文件列表，构建 section_path -> file_id 映射
    print(f"[2/4] 拉取知识库文件列表...")
    mapper = FileMapper(args.env_url, args.org_id, args.d_user_id)
    file_count = await mapper.load_files()
    print(f"      共 {file_count} 个文件")

    # 收集所有 hop 的 section_path，批量映射
    all_paths = {hop.section_path for qa in qa_pairs for hop in qa.hops}
    file_map = {path: mapper.map_section_to_file(path) for path in all_paths}

    mapped   = sum(1 for v in file_map.values() if v)
    unmapped = sum(1 for v in file_map.values() if not v)
    print(f"      映射成功: {mapped}  未映射: {unmapped}")
    if unmapped:
        for path, v in file_map.items():
            if not v:
                print(f"      [未映射] {path}")

    # 3. 执行多跳召回测试
    print(f"[3/4] 执行召回测试 (top_k={args.top_k}, concurrency={args.concurrency})...")
    tester = MultiHopTester(args.env_url, args.org_id, args.d_user_id)

    done_count = 0

    async def progress_cb(result, done, total):
        nonlocal done_count
        done_count = done
        status = "全命中" if result.full_hit else (
            f"部分命中({result.hop_hit_count}/{result.hop_count})" if result.partial_hit else "未命中"
        )
        if result.error:
            status = f"ERROR: {result.error[:40]}"
        print(f"      [{done:>4}/{total}] {result.qid} {status}")

    results = await tester.run(
        qa_pairs,
        file_map,
        top_k=args.top_k,
        concurrency=args.concurrency,
        result_cb=progress_cb,
    )

    # 4. 生成报告
    print(f"[4/4] 生成报告...")
    report = build_report(results, args.env_url, args.org_id, args.top_k)
    print()
    print(report.summary())

    if args.output:
        out_path = Path(args.output)
        out_path.write_text(
            json.dumps(report.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"\n报告已保存: {out_path}")


def _hop_dist(qa_pairs) -> str:
    from collections import Counter
    c = Counter(len(qa.hops) for qa in qa_pairs)
    return "  ".join(f"{k}跳×{v}" for k, v in sorted(c.items()))


def main():
    parser = argparse.ArgumentParser(description="多跳召回测试")
    parser.add_argument("--env-url",     required=True,  help="Dagent 环境地址")
    parser.add_argument("--org-id",      required=True,  help="组织 ID")
    parser.add_argument("--d-user-id",   default="test", help="d-user-id 请求头")
    parser.add_argument("--qa-file",     required=True,  help="多跳问答 MD 文件路径")
    parser.add_argument("--top-k",       type=int, default=10, help="召回数量（建议 ≥10）")
    parser.add_argument("--concurrency", type=int, default=5,  help="并发数")
    parser.add_argument("--output",      default=None,   help="报告输出路径（JSON）")
    args = parser.parse_args()
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
