"""End-to-end integrity tests for the 30-task benchmark, Ablation Study, Experiment B, and CLI."""

from __future__ import annotations

import json
from pathlib import Path

from cegar_harness.ast_filter import compute_canonical_ast_hash
from cegar_harness.benchmark import run_experiment_a, run_experiment_b
from cegar_harness.cli import main as cli_main
from cegar_harness.models import BugCategory, CompactionStrategy
from cegar_harness.replay import IsolatedTestRunner
from cegar_harness.tasks import get_all_tasks


def test_thirty_tasks_distribution_and_execution_invariants() -> None:
    tasks = get_all_tasks()
    assert len(tasks) == 30

    by_cat = {cat: [t for t in tasks if t.category == cat] for cat in BugCategory}
    for cat, cat_tasks in by_cat.items():
        assert len(cat_tasks) == 5, f"Category {cat} should have 5 tasks, found {len(cat_tasks)}"

    runner = IsolatedTestRunner(timeout_seconds=4.0)
    for t in tasks:
        res_pre = runner.run_test_code(t.pre_compaction_failed_patch.files, t.witness_test_code)
        assert not res_pre.passed, f"{t.task_id} pre_compaction should fail witness"

        c1, c2 = t.post_compaction_candidates[0], t.post_compaction_candidates[1]
        h_pre = compute_canonical_ast_hash(t.pre_compaction_failed_patch.files)
        h_c1 = compute_canonical_ast_hash(c1.files)

        if t.category == BugCategory.SYNTACTIC_VARIANTS:
            assert h_c1 != h_pre, f"{t.task_id} syntactic variant must have distinct canonical AST hash"
        else:
            assert h_c1 == h_pre, f"{t.task_id} alpha-renamed regression must match canonical AST hash"

        res_c1 = runner.run_test_code(c1.files, t.witness_test_code)
        assert not res_c1.passed, f"{t.task_id} c1 regression should fail witness"

        res_c2_ref = runner.run_test_code(c2.files, t.reference_test_code)
        assert res_c2_ref.passed, f"{t.task_id} c2 valid patch should pass reference suite"


def test_experiment_a_and_b_and_cli_end_to_end(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("CEGAR_LLM_API_BASE", raising=False)
    monkeypatch.delenv("CEGAR_LLM_MODEL", raising=False)

    out_dir = tmp_path / "bench_out"
    rc = cli_main(["bench", "--output-dir", str(out_dir)])
    assert rc == 0

    for expected_file in (
        "benchmark_report.json",
        "strategy_metrics.csv",
        "ablation_metrics.csv",
        "category_breakdown.csv",
        "benchmark_summary.md",
        "counterexamples.sqlite",
        "telemetry_events.jsonl",
    ):
        assert (out_dir / expected_file).exists(), f"Missing artifact: {expected_file}"

    report = json.loads((out_dir / "benchmark_report.json").read_text(encoding="utf-8"))
    exp_a = report["experiment_a_controlled_replay"]
    strategies = {s["strategy"]: s for s in exp_a["strategies"]}

    # Verify CompactionStrategy properties
    assert strategies[CompactionStrategy.FULL_HISTORY.value]["mean_compression_ratio_pct"] == 0.0
    assert strategies[CompactionStrategy.OBSERVATION_MASKING.value]["witness_retention_rate_pct"] == 0.0
    assert strategies[CompactionStrategy.LOSSY_SUMMARY.value]["witness_retention_rate_pct"] == 0.0
    assert strategies[CompactionStrategy.CEGAR_LEDGER_ONLY.value]["witness_retention_rate_pct"] == 100.0
    assert strategies[CompactionStrategy.CEGAR_HARNESS_FULL.value]["witness_retention_rate_pct"] == 100.0
    assert strategies[CompactionStrategy.CEGAR_HARNESS_FULL.value]["unblocked_regression_rate_pct"] == 0.0
    assert strategies[CompactionStrategy.CEGAR_HARNESS_FULL.value]["resolution_rate_pct"] == 100.0

    # Verify Ablation Study causal findings
    ablations = {a["config_id"]: a for a in exp_a["ablation_study"]}
    assert ablations["full_cegar_harness"]["regression_recall_pct"] == 100.0
    assert ablations["full_cegar_harness"]["cat6_recall_pct"] == 100.0
    assert ablations["full_cegar_harness"]["false_block_rate_pct"] == 0.0
    assert ablations["full_cegar_harness"]["final_resolution_rate_pct"] == 100.0

    # AST filter alone misses Category 6 syntactic variants
    assert ablations["ast_filter_only"]["cat6_recall_pct"] == 0.0
    assert ablations["ast_filter_only"]["regression_recall_pct"] < 100.0

    # Unversioned ledger falsely blocks Category 5 evolved contracts
    assert ablations["unversioned_ledger"]["cat5_evolved_contract_false_blocks"] == 5
    assert ablations["unversioned_ledger"]["false_block_rate_pct"] > 0.0

    # Experiment B honesty check when unconfigured
    exp_b = report["experiment_b_live_llm"]
    assert exp_b["executed"] is False
    assert exp_b["status"] == "NOT_EXECUTED_NO_CONFIG"

    # CLI inspect-ledger and live-eval subcommands
    assert cli_main(["inspect-ledger", "--db", str(out_dir / "counterexamples.sqlite"), "--task-id", "T01"]) == 0
    assert cli_main(["live-eval", "--max-tasks", "2"]) == 0
