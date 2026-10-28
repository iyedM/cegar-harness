"""End-to-end integrity tests for the 30-task benchmark, Partial Witness Coverage, Ablation, Experiment B, and CLI."""

from __future__ import annotations

import json
from pathlib import Path
from typing import List, Optional

from cegar_harness.ast_filter import compute_canonical_ast_hash
from cegar_harness.benchmark import run_experiment_a, run_experiment_b
from cegar_harness.cli import main as cli_main
from cegar_harness.llm_provider import LLMGenerationResult, LiveLLMClient
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
    partial_count = 0
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

        for pc in t.partial_coverage_candidates:
            partial_count += 1
            res_pc_wit = runner.run_test_code(pc.files, t.witness_test_code)
            res_pc_ref = runner.run_test_code(pc.files, t.reference_test_code)
            assert res_pc_wit.passed, f"{pc.patch_id} must pass initial witness (partial coverage)"
            assert not res_pc_ref.passed, f"{pc.patch_id} must fail full reference oracle"

        res_c2_ref = runner.run_test_code(c2.files, t.reference_test_code)
        assert res_c2_ref.passed, f"{t.task_id} c2 valid patch should pass reference suite"

    assert partial_count >= 10


def test_experiment_a_and_b_and_cli_end_to_end(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("CEGAR_LLM_API_BASE", raising=False)
    monkeypatch.delenv("CEGAR_LLM_MODEL", raising=False)

    out_dir = tmp_path / "bench_out"
    rc = cli_main(["bench", "--output-dir", str(out_dir)])
    assert rc == 0

    for expected_file in (
        "benchmark_report.json",
        "experiment_a_results.json",
        "experiment_b_live_results.json",
        "ablation_study.json",
        "strategy_metrics.csv",
        "experiment_a_summary.csv",
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

    # Verify CompactionStrategy properties & non-binary multi-turn hierarchy
    full_hist = strategies[CompactionStrategy.FULL_HISTORY.value]
    obs_mask = strategies[CompactionStrategy.OBSERVATION_MASKING.value]
    lossy_sum = strategies[CompactionStrategy.LOSSY_SUMMARY.value]
    ledger_only = strategies[CompactionStrategy.CEGAR_LEDGER_ONLY.value]
    cegar_full = strategies[CompactionStrategy.CEGAR_HARNESS_FULL.value]

    assert full_hist["mean_compression_ratio_pct"] == 0.0
    assert obs_mask["witness_retention_rate_pct"] == 0.0
    assert lossy_sum["witness_retention_rate_pct"] == 0.0
    assert ledger_only["witness_retention_rate_pct"] == 100.0
    assert cegar_full["witness_retention_rate_pct"] == 100.0

    # Non-trivial ordering: LOSSY_SUMMARY < OBSERVATION_MASKING < CEGAR_LEDGER_ONLY < CEGAR_HARNESS_FULL < 100%
    assert 0.0 < lossy_sum["resolution_rate_pct"] < obs_mask["resolution_rate_pct"]
    assert obs_mask["resolution_rate_pct"] < ledger_only["resolution_rate_pct"]
    assert ledger_only["resolution_rate_pct"] < cegar_full["resolution_rate_pct"] < 100.0
    assert cegar_full["unblocked_regression_rate_pct"] == 0.0
    assert cegar_full["secondary_witnesses_synthesized"] >= 8
    assert cegar_full["resolution_ci95_low_pct"] < cegar_full["resolution_rate_pct"] <= cegar_full["resolution_ci95_high_pct"]
    assert cegar_full["mean_oracle_turns_to_convergence"] < obs_mask["mean_oracle_turns_to_convergence"]

    # Verify Ablation Study causal findings
    ablations = {a["config_id"]: a for a in exp_a["ablation_study"]}
    assert ablations["full_cegar_harness"]["gate_precision_pct"] == 100.0
    assert ablations["full_cegar_harness"]["regression_recall_pct"] == 100.0
    assert ablations["full_cegar_harness"]["gate_f1_pct"] == 100.0
    assert ablations["full_cegar_harness"]["cat6_recall_pct"] == 100.0
    assert ablations["full_cegar_harness"]["false_block_rate_pct"] == 0.0
    assert ablations["full_cegar_harness"]["final_resolution_rate_pct"] == 100.0

    # AST filter alone misses Category 6 syntactic variants
    assert ablations["ast_filter_only"]["cat6_recall_pct"] == 0.0
    assert ablations["ast_filter_only"]["regression_recall_pct"] < 100.0
    assert ablations["ast_filter_only"]["mean_replay_overhead_ms"] == 0.0

    # Unversioned ledger falsely blocks Category 5 evolved contracts (lowering precision)
    assert ablations["unversioned_ledger"]["cat5_evolved_contract_false_blocks"] == 5
    assert ablations["unversioned_ledger"]["false_block_rate_pct"] > 0.0
    assert ablations["unversioned_ledger"]["gate_precision_pct"] < 100.0

    # Experiment B honesty check when unconfigured
    exp_b = report["experiment_b_live_llm"]
    assert exp_b["executed"] is False
    assert exp_b["status"] == "NOT_EXECUTED_NO_CONFIG"

    # CLI inspect-ledger and live-eval subcommands
    assert cli_main(["inspect-ledger", "--db", str(out_dir / "counterexamples.sqlite"), "--task-id", "T01"]) == 0
    assert cli_main(["live-eval", "--max-tasks", "2", "--output-dir", str(out_dir)]) == 0


def test_experiment_b_multi_turn_self_repair_loop(tmp_path: Path) -> None:
    """Verifies Experiment B multi-turn repair loop when a live LLM client is active."""
    tasks = [t for t in get_all_tasks() if t.task_id == "T26"]
    t26 = tasks[0]

    class _StubMultiTurnLLM(LiveLLMClient):
        def __init__(self) -> None:
            super().__init__(api_base="http://stub-llm/v1", api_key="k", model_name="stub-coder")

        def generate_patch(
            self,
            compacted_context: str,
            target_file: str,
            repair_feedback: Optional[List[str]] = None,
        ) -> LLMGenerationResult:
            # Turn 1: emits syntactic variant regression (list comprehension dropping 0)
            if not repair_feedback:
                code = t26.post_compaction_candidates[0].files[target_file]
            else:
                # Turn 2 (after receiving RegressionGate or oracle feedback): emits valid fix
                code = t26.post_compaction_candidates[1].files[target_file]
            return LLMGenerationResult(
                executed=True,
                status="EXECUTED",
                model_name=self.model_name,
                generated_code=code,
                prompt_tokens=120,
                completion_tokens=45,
            )

    res = run_experiment_b(
        tasks=tasks,
        client=_StubMultiTurnLLM(),
        max_turns=3,
        strategies=[CompactionStrategy.CEGAR_LEDGER_ONLY, CompactionStrategy.CEGAR_HARNESS_FULL],
        output_dir=tmp_path,
    )
    assert res["executed"] is True
    assert res["status"] == "EXECUTED"
    by_strat = {r["strategy"]: r for r in res["results"]}

    # Under CEGAR_HARNESS_FULL, Turn 1 regression was blocked by RegressionGate (0 oracle executions wasted on Turn 1)
    full_run = by_strat[CompactionStrategy.CEGAR_HARNESS_FULL.value]
    assert full_run["resolved"] is True
    assert full_run["gate_blocks"] == 1
    assert full_run["turn_traces"][0]["gate_status"] == "REGRESSION_DETECTED"
    assert full_run["turn_traces"][0]["oracle_executed"] is False
    assert full_run["turn_traces"][1]["oracle_passed"] is True
