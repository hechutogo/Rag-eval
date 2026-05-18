"""
单跳召回测试 CLI 入口。

用法：
  python -m rag_eval.single_jump.cli \
    --env-url https://cloud-dev.d-robotics.cc \
    --org-id dc778d0ae0aade4c33e19342ddd4fe72e68021623de5ff0e7c6b63dc04c7a1a7 \
    --qa-file "D:/evb知识库/EVB知识库完整问答集.md" \
    --top-k 5 \
    --output report.json
"""
import asyncio
import argparse
import sys
from pathlib import Path


async def run(args):
    sys.path.insert(0, str(Path(__file__).parent.parent.parent))

    from rag_eval.single_jump.parser import parse_qa_file
    from rag_eval.single_jump.mapper import FileMapper
    from rag_eval.single_jump.tester import RecallTester
    from rag_eval.single_jump.quality import check_recall_quality
    from rag_eval.single_jump.report import build_report

    # ── Step 1: 解析 MD 文件 ──────────────────────────────────────
    print(f"解析问答集文件: {args.qa_file}")
    sections = parse_qa_file(args.qa_file)
    total_qa = sum(len(s.qa_pairs) for s in sections)
    print(f"  共 {len(sections)} 个章节，{total_qa} 条问答对")

    # 限制测试数量（调试用）
    if args.max_questions and args.max_questions > 0:
        count = 0
        trimmed = []
        for s in sections:
            if count >= args.max_questions:
                break
            keep = s.qa_pairs[:max(0, args.max_questions - count)]
            if keep:
                s.qa_pairs = keep
                trimmed.append(s)
                count += len(keep)
        sections = trimmed
        total_qa = sum(len(s.qa_pairs) for s in sections)
        print(f"  限制为 {total_qa} 条（--max-questions {args.max_questions}）")

    # ── Step 2: 文件名映射 ────────────────────────────────────────
    print(f"\n拉取知识库文件列表...")
    mapper = FileMapper(
        env_url=args.env_url,
        org_id=args.org_id,
        d_user_id=args.user_id,
    )
    file_count = await mapper.load_files()
    print(f"  共 {file_count} 个文件")

    file_map: dict[str, dict | None] = {}
    unmatched = []
    for s in sections:
        if s.section_path not in file_map:
            result = mapper.map_section_to_file(s.section_path)
            file_map[s.section_path] = result
            if not result:
                unmatched.append(s.section_path)

    matched = len(file_map) - len(unmatched)
    print(f"  映射成功: {matched}/{len(file_map)} 个章节")
    if unmatched:
        print(f"  未匹配章节 ({len(unmatched)}): {unmatched[:5]}{'...' if len(unmatched) > 5 else ''}")

    # ── Step 3: 执行召回测试 ──────────────────────────────────────
    print(f"\n开始召回测试 (top_k={args.top_k}, concurrency={args.concurrency}, cross_chunk={args.cross_chunk})...")
    tester = RecallTester(
        env_url=args.env_url,
        org_id=args.org_id,
        d_user_id=args.user_id,
    )

    finished = 0
    def progress(done, total):
        nonlocal finished
        finished = done
        print(f"\r  进度: {done}/{total}", end="", flush=True)

    results = await tester.run(
        sections=sections,
        file_map=file_map,
        top_k=args.top_k,
        concurrency=args.concurrency,
        cross_chunk=args.cross_chunk,
        progress_cb=progress,
    )
    print(f"\r  完成: {len(results)} 条")

    # ── Step 4: 质量检测 ──────────────────────────────────────────
    quality_info = check_recall_quality(results)

    # ── Step 5: 生成报告 ──────────────────────────────────────────
    report = build_report(
        results=results,
        env_url=args.env_url,
        org_id=args.org_id,
        qa_file=args.qa_file,
        top_k=args.top_k,
        cross_chunk=args.cross_chunk,
        quality_info=quality_info,
    )

    print("\n" + report.summary_text())

    report.save(args.output)
    print(f"\n报告已保存: {args.output}")


def main():
    parser = argparse.ArgumentParser(
        prog="single-jump-eval",
        description="单跳知识库召回自动化测试",
    )
    parser.add_argument("--env-url", required=True, help="dagent 环境地址，如 https://cloud-dev.d-robotics.cc")
    parser.add_argument("--org-id", required=True, help="组织 ID")
    parser.add_argument("--user-id", default="test", help="d-user-id 请求头（默认 test）")
    parser.add_argument("--qa-file", required=True, help="问答集 MD 文件路径")
    parser.add_argument("--top-k", type=int, default=5, help="召回数量（默认 5）")
    parser.add_argument("--concurrency", type=int, default=5, help="并发数（默认 5）")
    parser.add_argument("--cross-chunk", action="store_true", help="跨切片模式（不限定 file_id）")
    parser.add_argument("--max-questions", type=int, default=0, help="限制测试问题数（0=不限制，调试用）")
    parser.add_argument("--output", default="single_jump_report.json", help="输出报告路径")

    args = parser.parse_args()
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
