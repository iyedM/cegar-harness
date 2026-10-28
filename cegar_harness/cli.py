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

    print(f"=== CEGAR-Harness Multi-Turn Controlled Replay Benchmark ({exp_a['total_tasks']} tasks) ===")
    print(
        f"{'Strategy':<22} {'Comp%':>7} {'Retain%':>8} {'Blocked':>8} "
        f"{'UnblkReg%':>10} {'2ndCE':>6} {'Turn1%':>8} {'Final% [95% CI]':<22} {'Turns':>6}"
    )
    print("-" * 105)
    for s in exp_a["strategies"]:
        ci_str = f"{s['resolution_rate_pct']:>6.2f}% [{s['resolution_ci95_low_pct']:.1f},{s['resolution_ci95_high_pct']:.1f}]"
        print(
            f"{s['strategy']:<22} {s['mean_compression_ratio_pct']:>6.2f}% "
            f"{s['witness_retention_rate_pct']:>7.1f}% {s['regressions_blocked_by_gate']:>8} "
            f"{s['unblocked_regression_rate_pct']:>9.2f}% {s['secondary_witnesses_synthesized']:>6} "
            f"{s['turn1_resolution_rate_pct']:>7.2f}% {ci_str:<22} {s['mean_oracle_turns_to_convergence']:>6.2f}"
        )

    print("\n=== Regression Gate Ablation Study (60 Candidate Evaluations across 30 Tasks) ===")
    print(
        f"{'Ablation Config':<22} {'Prec%':>7} {'Recall%':>8} {'F1%':>7} {'Cat6Syn%':>9} "
        f"{'FalseBlk%':>10} {'Inconc':>7} {'Resolved%':>10} {'Med/p95(ms)':>14}"
    )
    print("-" * 102)
    for a in exp_a["ablation_study"]:
        lat_str = f"{a['median_gate_latency_ms']:.2f}/{a['p95_gate_latency_ms']:.2f}"
        print(
            f"{a['config_id']:<22} {a['gate_precision_pct']:>6.2f}% {a['regression_recall_pct']:>7.2f}% "
            f"{a['gate_f1_pct']:>6.2f}% {a['cat6_recall_pct']:>8.1f}% "
            f"{a['false_block_rate_pct']:>9.2f}% {a['inconclusive_on_evolved_contract']:>7} "
            f"{a['final_resolution_rate_pct']:>9.2f}% {lat_str:>14}"
        )

    print(f"\nArtifacts written to: {out_dir.resolve()}")
    return 0


def _cmd_live_eval(args: argparse.Namespace) -> int:
    from cegar_harness.llm_provider import LiveLLMClient

    tasks = get_all_tasks()[: args.max_tasks]
    client = LiveLLMClient(
        api_base=args.api_base,
        api_key=args.api_key,
        model_name=args.model,
    )
    res = run_experiment_b(
        tasks=tasks,
        client=client,
        max_turns=args.max_turns,
        output_dir=args.output_dir,
    )
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


def _cmd_mcp_serve(args: argparse.Namespace) -> int:
    from cegar_harness.mcp_server import CEGARMCPServer

    server = CEGARMCPServer(db_path=args.db, jsonl_path=args.telemetry_log)
    try:
        server.serve_stdio()
    finally:
        server.close()
    return 0


def _cmd_ui(args: argparse.Namespace) -> int:
    from cegar_harness.ui_server import create_ui_server

    server = create_ui_server(host=args.host, port=args.port, results_dir=args.results_dir)
    host, port = server.server_address
    print(f"CEGAR Trajectory & Compaction Inspector UI listening on http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
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
        help="Run Experiment B (Multi-Turn Live LLM Repair Loop; requires CEGAR_LLM_API_BASE & CEGAR_LLM_MODEL or CLI flags)",
    )
    p_live.add_argument("--max-tasks", type=int, default=5, help="Max tasks to evaluate live")
    p_live.add_argument("--max-turns", type=int, default=3, help="Max post-compaction turns per task")
    p_live.add_argument("--model", default=None, help="LLM model name override (or CEGAR_LLM_MODEL)")
    p_live.add_argument("--api-base", default=None, help="OpenAI-compatible API base URL override")
    p_live.add_argument("--api-key", default=None, help="API key override")
    p_live.add_argument("--output-dir", default="results", help="Output directory for experiment_b_live_results.json")
    p_live.set_defaults(func=_cmd_live_eval)

    p_insp = sub.add_parser("inspect-ledger", help="Inspect stored counterexamples in SQLite ledger")
    p_insp.add_argument(
        "--db",
        default="results/counterexamples.sqlite",
        help="Path to SQLite counterexample ledger",
    )
    p_insp.add_argument("--task-id", default=None, help="Filter by specific task_id (e.g. T01)")
    p_insp.set_defaults(func=_cmd_inspect_ledger)

    p_mcp = sub.add_parser("mcp-serve", help="Run the Model Context Protocol (MCP) JSON-RPC 2.0 server over stdio")
    p_mcp.add_argument(
        "--db",
        default="results/counterexamples.sqlite",
        help="Path to SQLite counterexample ledger",
    )
    p_mcp.add_argument(
        "--telemetry-log",
        default=None,
        help="Optional path to JSONL telemetry log file",
    )
    p_mcp.set_defaults(func=_cmd_mcp_serve)

    p_ui = sub.add_parser("ui", help="Launch the interactive CEGAR Trajectory & Compaction Inspector Web UI")
    p_ui.add_argument("--host", default="127.0.0.1", help="Bind host (default: 127.0.0.1)")
    p_ui.add_argument("--port", type=int, default=8080, help="Bind port (default: 8080)")
    p_ui.add_argument("--results-dir", default="results", help="Path to benchmark results directory")
    p_ui.set_defaults(func=_cmd_ui)

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
