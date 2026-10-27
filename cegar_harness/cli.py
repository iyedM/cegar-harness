"""Command-line interface for CEGAR-Harness (`bench`, `live-eval`, `inspect-ledger`)."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import List, Optional

from cegar_harness.benchmark import run_experiment_a, run_experiment_b
from cegar_harness.ledger import CounterexampleLedger
from cegar_harness.tasks import get_all_tasks


def _cmd_bench(args: argparse.Namespace) -> int:
    out_dir = Path(args.output_dir)
    report = run_experiment_a(output_dir=out_dir)
    exp_a = report["experiment_a_controlled_replay"]

    print(f"=== CEGAR-Harness Controlled Replay Benchmark ({exp_a['total_tasks']} tasks) ===")
    print(
        f"{'Strategy':<24} {'Tokens(Pre->Post)':<20} {'Comp%':>7} {'Retain%':>9} "
        f"{'Blocked':>8} {'UnblkReg%':>10} {'Resolved%':>10}"
    )
    print("-" * 94)
    for s in exp_a["strategies"]:
        tok_str = f"{s['mean_tokens_before']:.0f} -> {s['mean_tokens_after']:.0f}"
        print(
            f"{s['strategy']:<24} {tok_str:<20} {s['mean_compression_ratio_pct']:>6.2f}% "
            f"{s['witness_retention_rate_pct']:>8.1f}% {s['regressions_blocked_by_gate']:>8} "
            f"{s['unblocked_regression_rate_pct']:>9.2f}% {s['resolution_rate_pct']:>9.2f}%"
        )

    print("\n=== Regression Gate Ablation Study (60 Candidate Evaluations across 30 Tasks) ===")
    print(
        f"{'Ablation Config':<24} {'Recall%':>9} {'Cat6Syn%':>9} "
        f"{'FalseBlk%':>10} {'Inconc':>7} {'Resolved%':>10} {'Latency(ms)':>12}"
    )
    print("-" * 87)
    for a in exp_a["ablation_study"]:
        print(
            f"{a['config_id']:<24} {a['regression_recall_pct']:>8.2f}% {a['cat6_recall_pct']:>8.1f}% "
            f"{a['false_block_rate_pct']:>9.2f}% {a['inconclusive_on_evolved_contract']:>7} "
            f"{a['final_resolution_rate_pct']:>9.2f}% {a['mean_gate_latency_ms']:>11.2f}"
        )

    print(f"\nArtifacts written to: {out_dir.resolve()}")
    return 0


def _cmd_live_eval(args: argparse.Namespace) -> int:
    tasks = get_all_tasks()[: args.max_tasks]
    res = run_experiment_b(tasks=tasks)
    print(json.dumps(res, indent=2))
    return 0


def _cmd_inspect_ledger(args: argparse.Namespace) -> int:
    db_path = Path(args.db)
    if not db_path.exists():
        print(f"Error: SQLite ledger file not found at {db_path}", file=sys.stderr)
        return 1
    ledger = CounterexampleLedger(db_path)
    try:
        if args.task_id:
            records = ledger.get_by_task(args.task_id, include_resolved=True)
        else:
            records = []
            for t in get_all_tasks():
                records.extend(ledger.get_by_task(t.task_id, include_resolved=True))
        print(json.dumps([asdict(r) for r in records], indent=2))
    finally:
        ledger.close()
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cegar-harness",
        description="CEGAR-Harness: Regression-Aware Context Compaction & Witness Replay for Coding Agents",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_bench = sub.add_parser("bench", help="Run Experiment A (Controlled Replay + Ablation Study)")
    p_bench.add_argument(
        "--output-dir",
        default="results",
        help="Directory for JSON, CSV, Markdown, SQLite, and JSONL outputs (default: results)",
    )
    p_bench.set_defaults(func=_cmd_bench)

    p_live = sub.add_parser(
        "live-eval",
        help="Run Experiment B (Live LLM Continuation; requires CEGAR_LLM_API_BASE & CEGAR_LLM_MODEL)",
    )
    p_live.add_argument("--max-tasks", type=int, default=5, help="Max tasks to evaluate live")
    p_live.set_defaults(func=_cmd_live_eval)

    p_insp = sub.add_parser("inspect-ledger", help="Inspect stored counterexamples in SQLite ledger")
    p_insp.add_argument(
        "--db",
        default="results/counterexamples.sqlite",
        help="Path to SQLite counterexample ledger",
    )
    p_insp.add_argument("--task-id", default=None, help="Filter by specific task_id (e.g. T01)")
    p_insp.set_defaults(func=_cmd_inspect_ledger)

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
