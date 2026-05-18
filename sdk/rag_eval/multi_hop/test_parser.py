"""
快速测试多跳模块的解析和数据结构。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from rag_eval.multi_hop.parser import parse_multi_hop_file, dump_multi_hop_md


def test_parser():
    print("=" * 60)
    print("测试多跳 MD 文件解析")
    print("=" * 60)

    example_file = Path(__file__).parent / "example.md"
    if not example_file.exists():
        print(f"ERROR: 示例文件不存在: {example_file}")
        return

    case = parse_multi_hop_file(str(example_file))
    print(f"\n解析结果: 共 {len(case.qa_pairs)} 个问题\n")

    for qa in case.qa_pairs:
        print(f"问题 {qa.qid} ({qa.type}):")
        print(f"  Q: {qa.question}")
        print(f"  A: {qa.answer[:80]}...")
        print(f"  Hops ({len(qa.hops)}):")
        for i, hop in enumerate(qa.hops, 1):
            print(f"    {i}. {hop.section_path}")
            print(f"       → {hop.contribution}")
        print()

    # 测试序列化
    print("=" * 60)
    print("测试序列化")
    print("=" * 60)
    md_text = dump_multi_hop_md(case.qa_pairs)
    print(md_text[:500])
    print("...")
    print("\nOK: 解析和序列化测试通过")


if __name__ == "__main__":
    test_parser()
