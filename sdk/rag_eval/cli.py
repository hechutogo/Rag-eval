"""
CLI entry point: rag-eval run --config config.yaml
"""
import asyncio
import argparse
import json
import yaml
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(prog="rag-eval", description="RAG Evaluation Framework")
    sub = parser.add_subparsers(dest="command")

    # rag-eval run
    run_p = sub.add_parser("run", help="Run evaluation")
    run_p.add_argument("--config", required=True, help="Path to YAML config file")
    run_p.add_argument("--dataset", required=True, help="Path to dataset JSON file")
    run_p.add_argument("--output", default="eval_report.json", help="Output report path")

    # rag-eval generate
    gen_p = sub.add_parser("generate", help="Generate dataset from knowledge base")
    gen_p.add_argument("--config", required=True, help="Path to YAML config file")
    gen_p.add_argument("--output", default="dataset.json", help="Output dataset path")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    asyncio.run(_dispatch(args))


async def _dispatch(args):
    config = _load_config(args.config)

    from rag_eval.adapters.dagent import DagentAdapter
    from rag_eval.judge.openai_compatible import OpenAICompatibleJudge

    adapter = DagentAdapter(
        base_url=config["platform"]["base_url"],
        org_id=config["platform"]["org_id"],
        token=config["platform"].get("token", ""),
    )
    judge = OpenAICompatibleJudge(
        base_url=config["judge"]["base_url"],
        api_key=config["judge"]["api_key"],
        model=config["judge"]["model"],
        embed_base_url=config["judge"].get("embed_base_url", ""),
        embed_api_key=config["judge"].get("embed_api_key", ""),
        embed_model=config["judge"].get("embed_model", "text-embedding-3-small"),
    )

    if args.command == "run":
        from rag_eval.runner import EvalRunner, RunConfig
        from rag_eval.dataset.schema import EvalDataset

        run_cfg = RunConfig(
            agent_id=config["eval"]["agent_id"],
            knowledge_hub_id=config["eval"]["knowledge_hub_id"],
            top_k=config["eval"].get("top_k", 10),
            eval_retrieval=config["eval"].get("eval_retrieval", True),
            eval_generation=config["eval"].get("eval_generation", True),
            file_id_list=config["eval"].get("file_id_list"),
            concurrency=config["eval"].get("concurrency", 3),
        )

        runner = EvalRunner(adapter=adapter, judge=judge)

        def _progress(done, total):
            print(f"\r  Progress: {done}/{total}", end="", flush=True)

        print(f"Running evaluation on {args.dataset} ...")
        report = await runner.run(args.dataset, run_cfg, progress_cb=_progress)
        print()
        print(report.summary())
        report.save(args.output)

    elif args.command == "generate":
        from rag_eval.dataset.generator import DatasetGenerator

        gen = DatasetGenerator(judge=judge, adapter=adapter)
        dataset = await gen.generate(
            knowledge_hub_id=config["eval"]["knowledge_hub_id"],
            file_id_list=config["eval"]["file_id_list"],
            questions_per_chunk=config["eval"].get("questions_per_chunk", 2),
            max_chunks=config["eval"].get("max_chunks", 50),
        )
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(dataset.to_dict(), f, ensure_ascii=False, indent=2)
        print(f"Generated {len(dataset.samples)} samples → {args.output}")


def _load_config(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)
