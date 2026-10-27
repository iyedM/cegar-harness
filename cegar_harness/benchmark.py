"""Benchmark Runner for Experiment A (Controlled Replay + Ablation) and Experiment B (Live LLM)."""

from __future__ import annotations

import csv
import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from cegar_harness.ast_filter import compute_canonical_ast_hash
from cegar_harness.compactor import CompactionController, TrajectoryTurn
from cegar_harness.gate import RegressionGate
from cegar_harness.ledger import CounterexampleLedger
from cegar_harness.llm_provider import LiveLLMClient
from cegar_harness.models import (
    BugCategory,
    CandidatePatch,
    CompactionStrategy,
    CounterexampleRecord,
    GateStatus,
    TaskSpec,
)
from cegar_harness.replay import IsolatedTestRunner
from cegar_harness.tasks import get_all_tasks
from cegar_harness.telemetry import TelemetryRecorder


@dataclass
class StrategySummaryMetrics:
    """Aggregated empirical metrics for a single CompactionStrategy across all 30 tasks."""

    strategy: str
    tasks_total: int
    mean_tokens_before: float
    mean_tokens_after: float
    mean_compression_ratio_pct: float
    witness_retention_count: int
    witness_retention_rate_pct: float
    regressions_blocked_by_gate: int
    unblocked_regressions: int
    unblocked_regression_rate_pct: float
    false_blocks: int
    false_block_rate_pct: float
    inconclusive_gates: int
    tasks_resolved: int
    resolution_rate_pct: float
    mean_gate_latency_ms: float


@dataclass
class AblationSummaryMetrics:
    """Aggregated empirical metrics for a RegressionGate ablation configuration across all 30 tasks."""

    config_id: str
    description: str
    enable_ast_filter: bool
    enable_witness_replay: bool
    enforce_contract_version: bool
    total_regression_candidates: int
    regressions_caught: int
    regression_recall_pct: float
    caught_by_ast_filter: int
    caught_by_witness_replay: int
    cat6_syntactic_variants_caught: int
    cat6_syntactic_variants_total: int
    cat6_recall_pct: float
    valid_candidates_evaluated: int
    false_blocks_on_valid: int
    false_block_rate_pct: float
    cat5_evolved_contract_false_blocks: int
    inconclusive_on_evolved_contract: int
    final_tasks_resolved: int
    final_resolution_rate_pct: float
    mean_gate_latency_ms: float


def _build_pre_compaction_turns(task: TaskSpec, failure_predicate: str) -> List[TrajectoryTurn]:
    """Constructs the multi-turn pre-compaction trajectory for a task."""
    patch_preview = "\n".join(
        f"# File: {path}\n{code.strip()}"
        for path, code in sorted(task.pre_compaction_failed_patch.files.items())
    )
    verbose_test_output = (
        f"[PYTEST EXECUTION TRACE | task={task.task_id} | witness={task.witness_name}]\n"
        + ("collecting ... collected 1 item\nexecuting isolated witness harness...\n" * 4)
        + f"FAILED {task.target_file}::{task.witness_name}\n"
        + f"Witness Failure Predicate: {failure_predicate}\n"
    )
    turns = [
        TrajectoryTurn(
            step=1,
            role="agent_action",
            content=f"Proposing initial patch `{task.pre_compaction_failed_patch.patch_id}`:\n{patch_preview}",
        ),
        TrajectoryTurn(
            step=2,
            role="tool_observation",
            content=verbose_test_output,
            is_failure_observation=True,
            witness_predicate=failure_predicate,
        ),
        TrajectoryTurn(
            step=3,
            role="agent_action",
            content=f"Inspecting call sites and symbol usages for `{task.target_symbol}` in `{task.target_file}`.",
        ),
        TrajectoryTurn(
            step=4,
            role="tool_observation",
            content=task.verbose_observations[0],
        ),
        TrajectoryTurn(
            step=5,
            role="agent_action",
            content=f"Running static control-flow inspection on `{task.target_file}` before next attempt.",
        ),
        TrajectoryTurn(
            step=6,
            role="tool_observation",
            content=task.verbose_observations[1],
        ),
    ]
    return turns


def run_experiment_a(
    output_dir: str | Path = "results",
    tasks: Optional[List[TaskSpec]] = None,
) -> Dict[str, Any]:
    """Executes Experiment A (Controlled Replay Benchmark + 4-way Ablation Study) on all 30 tasks."""
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    task_list = tasks if tasks is not None else get_all_tasks()
    runner = IsolatedTestRunner(timeout_seconds=5.0)
    compactor = CompactionController(sliding_window_turns=2)

    db_path = out_path / "counterexamples.sqlite"
    if db_path.exists():
        db_path.unlink()
    jsonl_path = out_path / "telemetry_events.jsonl"
    if jsonl_path.exists():
        jsonl_path.unlink()

    ledger = CounterexampleLedger(db_path)
    telemetry = TelemetryRecorder(jsonl_path)

    # 1. Pre-compaction phase: execute every task's pre-compaction failed patch and populate the ledger
    pre_compaction_predicates: Dict[str, str] = {}
    for task in task_list:
        exec_res = runner.run_test_code(
            task.pre_compaction_failed_patch.files, task.witness_test_code
        )
        if exec_res.passed:
            raise RuntimeError(
                f"Benchmark integrity failure: pre-compaction patch for {task.task_id} passed witness test."
            )
        ce = CounterexampleRecord(
            ce_id=f"CE-{task.task_id}-01",
            task_id=task.task_id,
            target_file=task.target_file,
            target_symbol=task.target_symbol,
            contract_version=task.contract_version_initial,
            ast_hash=compute_canonical_ast_hash(task.pre_compaction_failed_patch.files),
            witness_name=task.witness_name,
            witness_test_code=task.witness_test_code,
            failure_predicate=exec_res.failure_predicate,
            discovered_at_step=2,
            status="ACTIVE",
            provenance="oracle_witness_failure",
        )
        ledger.record(ce)
        pre_compaction_predicates[task.task_id] = exec_res.failure_predicate

    # 2. Evaluate the 5 Context Compaction Strategies
    strategy_summaries: List[StrategySummaryMetrics] = []
    per_task_strategy_details: Dict[str, List[Dict[str, Any]]] = {}

    for strategy in CompactionStrategy:
        tokens_before_list: List[int] = []
        tokens_after_list: List[int] = []
        compression_ratios: List[float] = []
        retained_count = 0
        blocked_by_gate = 0
        unblocked_regressions = 0
        false_blocks = 0
        inconclusive_count = 0
        resolved_count = 0
        gate_latencies: List[float] = []
        task_rows: List[Dict[str, Any]] = []

        use_gate = strategy == CompactionStrategy.CEGAR_HARNESS_FULL
        gate = RegressionGate(
            ledger=ledger,
            runner=runner,
            telemetry=telemetry,
            enable_ast_filter=True,
            enable_witness_replay=True,
            enforce_contract_version=True,
        )

        for task in task_list:
            pred = pre_compaction_predicates[task.task_id]
            turns = _build_pre_compaction_turns(task, pred)
            comp_res = compactor.compact(
                task_id=task.task_id,
                specification=task.specification,
                contract_version=task.contract_version_initial,
                turns=turns,
                strategy=strategy,
                ledger=ledger,
            )
            telemetry.record_compaction(
                task_id=task.task_id,
                strategy=strategy.value,
                tokens_before=comp_res.tokens_before,
                tokens_after=comp_res.tokens_after,
                witness_retained=comp_res.witness_predicate_retained,
            )

            tokens_before_list.append(comp_res.tokens_before)
            tokens_after_list.append(comp_res.tokens_after)
            compression_ratios.append(comp_res.compression_ratio)
            if comp_res.witness_predicate_retained:
                retained_count += 1

            c1_reg, c2_fix = task.post_compaction_candidates[0], task.post_compaction_candidates[1]

            # Deterministic candidate proposal rules conditioned on witness retention in context:
            # - If witness predicate was lost during compaction, the agent proposes [c1_reg, c2_fix].
            # - If witness predicate was retained in context, exact/alpha-renamed repeats (Categories 1-5)
            #   are avoided in prompt, EXCEPT for syntactic variants (Category 6) where prompt text alone
            #   does not prevent a syntactically distinct implementation of the same logical bug.
            if not comp_res.witness_predicate_retained:
                proposed_queue: List[CandidatePatch] = [c1_reg, c2_fix]
            else:
                if c1_reg.syntactic_variant_of is not None:
                    proposed_queue = [c1_reg, c2_fix]
                else:
                    proposed_queue = [c2_fix]

            task_resolved = False
            task_unblocked_regression = False
            task_blocked_count = 0
            task_false_block = False
            task_inconclusive = 0

            for cand in proposed_queue:
                if use_gate:
                    gate_res = gate.evaluate(
                        task_id=task.task_id,
                        candidate_files=cand.files,
                        current_contract_version=cand.contract_version,
                    )
                    gate_latencies.append(gate_res.latency_ms)
                    if gate_res.status == GateStatus.REGRESSION_DETECTED:
                        if cand.is_valid_solution:
                            false_blocks += 1
                            task_false_block = True
                        else:
                            blocked_by_gate += 1
                            task_blocked_count += 1
                        # Gate rejected candidate; move to next candidate in trajectory queue
                        continue
                    elif gate_res.status == GateStatus.INCONCLUSIVE:
                        inconclusive_count += 1
                        task_inconclusive += 1

                # Candidate reaches full reference oracle evaluation
                witness_check = runner.run_test_code(cand.files, task.witness_test_code)
                oracle_check = runner.run_test_code(cand.files, task.reference_test_code)

                if not oracle_check.passed:
                    if not witness_check.passed or cand.is_known_regression:
                        unblocked_regressions += 1
                        task_unblocked_regression = True
                    break
                else:
                    task_resolved = True
                    resolved_count += 1
                    break

            task_rows.append(
                {
                    "task_id": task.task_id,
                    "category": task.category.value,
                    "tokens_before": comp_res.tokens_before,
                    "tokens_after": comp_res.tokens_after,
                    "compression_ratio": comp_res.compression_ratio,
                    "witness_retained": comp_res.witness_predicate_retained,
                    "blocked_by_gate": task_blocked_count,
                    "unblocked_regression": task_unblocked_regression,
                    "false_block": task_false_block,
                    "inconclusive_gate": task_inconclusive,
                    "resolved": task_resolved,
                }
            )

        n_tasks = len(task_list)
        strategy_summaries.append(
            StrategySummaryMetrics(
                strategy=strategy.value,
                tasks_total=n_tasks,
                mean_tokens_before=round(sum(tokens_before_list) / n_tasks, 2),
                mean_tokens_after=round(sum(tokens_after_list) / n_tasks, 2),
                mean_compression_ratio_pct=round((sum(compression_ratios) / n_tasks) * 100.0, 2),
                witness_retention_count=retained_count,
                witness_retention_rate_pct=round((retained_count / n_tasks) * 100.0, 2),
                regressions_blocked_by_gate=blocked_by_gate,
                unblocked_regressions=unblocked_regressions,
                unblocked_regression_rate_pct=round((unblocked_regressions / n_tasks) * 100.0, 2),
                false_blocks=false_blocks,
                false_block_rate_pct=round((false_blocks / n_tasks) * 100.0, 2),
                inconclusive_gates=inconclusive_count,
                tasks_resolved=resolved_count,
                resolution_rate_pct=round((resolved_count / n_tasks) * 100.0, 2),
                mean_gate_latency_ms=round(
                    sum(gate_latencies) / len(gate_latencies), 3
                )
                if gate_latencies
                else 0.0,
            )
        )
        per_task_strategy_details[strategy.value] = task_rows

    # 3. Run 4-Way RegressionGate Ablation Study across all 30 tasks ([c1_reg, c2_fix] evaluated on every task)
    ablation_configs = [
        (
            "full_cegar_harness",
            "Full CEGAR-Harness (AST Filter + Witness Replay + Contract Versioning)",
            True,
            True,
            True,
        ),
        (
            "ast_filter_only",
            "AST Canonicalization Filter Only (No Behavioral Witness Replay)",
            True,
            False,
            True,
        ),
        (
            "witness_replay_only",
            "Behavioral Witness Replay Only (No AST Pre-Filter)",
            False,
            True,
            True,
        ),
        (
            "unversioned_ledger",
            "Unversioned Counterexample Ledger (No Contract Version Check)",
            True,
            True,
            False,
        ),
    ]

    ablation_summaries: List[AblationSummaryMetrics] = []
    for cfg_id, desc, ast_on, replay_on, ver_on in ablation_configs:
        gate = RegressionGate(
            ledger=ledger,
            runner=runner,
            telemetry=telemetry,
            enable_ast_filter=ast_on,
            enable_witness_replay=replay_on,
            enforce_contract_version=ver_on,
        )
        reg_total = 0
        reg_caught = 0
        by_ast = 0
        by_replay = 0
        cat6_total = 0
        cat6_caught = 0
        valid_total = 0
        false_blocks_cnt = 0
        cat5_false_blocks = 0
        inconc_evolved = 0
        tasks_resolved_cnt = 0
        latencies: List[float] = []

        for task in task_list:
            c1_reg, c2_fix = task.post_compaction_candidates[0], task.post_compaction_candidates[1]

            # Evaluate regression candidate c1_reg
            reg_total += 1
            if task.category == BugCategory.SYNTACTIC_VARIANTS:
                cat6_total += 1

            res_c1 = gate.evaluate(task.task_id, c1_reg.files, c1_reg.contract_version)
            latencies.append(res_c1.latency_ms)

            c1_blocked = res_c1.status == GateStatus.REGRESSION_DETECTED
            if c1_blocked:
                reg_caught += 1
                if res_c1.triggered_by == "ast_filter":
                    by_ast += 1
                elif res_c1.triggered_by == "witness_replay":
                    by_replay += 1
                if task.category == BugCategory.SYNTACTIC_VARIANTS:
                    cat6_caught += 1

            # Evaluate valid candidate c2_fix
            valid_total += 1
            res_c2 = gate.evaluate(task.task_id, c2_fix.files, c2_fix.contract_version)
            latencies.append(res_c2.latency_ms)

            c2_blocked = res_c2.status == GateStatus.REGRESSION_DETECTED
            if c2_blocked:
                false_blocks_cnt += 1
                if task.category == BugCategory.FEATURE_REGRESSIONS:
                    cat5_false_blocks += 1
            elif res_c2.status == GateStatus.INCONCLUSIVE:
                inconc_evolved += 1

            # A task resolves in the [c1_reg, c2_fix] trajectory iff c1_reg is blocked by the gate
            # and c2_fix is NOT falsely blocked by the gate (and passes the reference oracle).
            if c1_blocked and not c2_blocked:
                oracle_res = runner.run_test_code(c2_fix.files, task.reference_test_code)
                if oracle_res.passed:
                    tasks_resolved_cnt += 1

        ablation_summaries.append(
            AblationSummaryMetrics(
                config_id=cfg_id,
                description=desc,
                enable_ast_filter=ast_on,
                enable_witness_replay=replay_on,
                enforce_contract_version=ver_on,
                total_regression_candidates=reg_total,
                regressions_caught=reg_caught,
                regression_recall_pct=round((reg_caught / reg_total) * 100.0, 2),
                caught_by_ast_filter=by_ast,
                caught_by_witness_replay=by_replay,
                cat6_syntactic_variants_caught=cat6_caught,
                cat6_syntactic_variants_total=cat6_total,
                cat6_recall_pct=round((cat6_caught / cat6_total) * 100.0, 2) if cat6_total else 0.0,
                valid_candidates_evaluated=valid_total,
                false_blocks_on_valid=false_blocks_cnt,
                false_block_rate_pct=round((false_blocks_cnt / valid_total) * 100.0, 2),
                cat5_evolved_contract_false_blocks=cat5_false_blocks,
                inconclusive_on_evolved_contract=inconc_evolved,
                final_tasks_resolved=tasks_resolved_cnt,
                final_resolution_rate_pct=round((tasks_resolved_cnt / len(task_list)) * 100.0, 2),
                mean_gate_latency_ms=round(sum(latencies) / len(latencies), 3) if latencies else 0.0,
            )
        )

    # 4. Compute Per-Category Breakdown across key strategies and ablations
    category_breakdown: List[Dict[str, Any]] = []
    for cat in BugCategory:
        cat_tasks = [t for t in task_list if t.category == cat]
        cat_ids = {t.task_id for t in cat_tasks}
        n_cat = len(cat_tasks)

        mask_rows = [
            r for r in per_task_strategy_details[CompactionStrategy.OBSERVATION_MASKING.value]
            if r["task_id"] in cat_ids
        ]
        ledger_rows = [
            r for r in per_task_strategy_details[CompactionStrategy.CEGAR_LEDGER_ONLY.value]
            if r["task_id"] in cat_ids
        ]
        full_rows = [
            r for r in per_task_strategy_details[CompactionStrategy.CEGAR_HARNESS_FULL.value]
            if r["task_id"] in cat_ids
        ]

        category_breakdown.append(
            {
                "category": cat.value,
                "tasks_count": n_cat,
                "obs_masking_unblocked_regressions": sum(1 for r in mask_rows if r["unblocked_regression"]),
                "cegar_ledger_only_unblocked_regressions": sum(
                    1 for r in ledger_rows if r["unblocked_regression"]
                ),
                "cegar_full_unblocked_regressions": sum(1 for r in full_rows if r["unblocked_regression"]),
                "cegar_full_resolved": sum(1 for r in full_rows if r["resolved"]),
                "cegar_full_inconclusive_gates": sum(r["inconclusive_gate"] for r in full_rows),
            }
        )

    # 5. Experiment B status check (never simulated if unconfigured)
    exp_b_result = run_experiment_b(tasks=task_list[:3])

    report = {
        "generated_at_epoch": time.time(),
        "benchmark_version": "0.1.0",
        "experiment_a_controlled_replay": {
            "total_tasks": len(task_list),
            "categories_count": len(BugCategory),
            "strategies": [asdict(s) for s in strategy_summaries],
            "ablation_study": [asdict(a) for a in ablation_summaries],
            "category_breakdown": category_breakdown,
            "per_task_details": per_task_strategy_details,
        },
        "experiment_b_live_llm": exp_b_result,
    }

    _export_reports(out_path, report, strategy_summaries, ablation_summaries, category_breakdown)
    ledger.close()
    return report


def run_experiment_b(
    tasks: Optional[List[TaskSpec]] = None,
    client: Optional[LiveLLMClient] = None,
) -> Dict[str, Any]:
    """Executes Experiment B (Live LLM Agent Continuation) if configured, or reports NOT_EXECUTED_NO_CONFIG."""
    llm = client or LiveLLMClient()
    if not llm.is_configured:
        Probe = llm.generate_patch("", "")
        return {
            "executed": False,
            "status": Probe.status,
            "model_name": Probe.model_name,
            "message": Probe.error_message,
            "results": [],
        }

    task_list = tasks if tasks is not None else get_all_tasks()[:5]
    runner = IsolatedTestRunner(timeout_seconds=5.0)
    compactor = CompactionController(sliding_window_turns=2)
    ledger = CounterexampleLedger(":memory:")

    live_results: List[Dict[str, Any]] = []
    for task in task_list:
        exec_res = runner.run_test_code(
            task.pre_compaction_failed_patch.files, task.witness_test_code
        )
        ce = CounterexampleRecord(
            ce_id=f"CE-{task.task_id}-LIVE",
            task_id=task.task_id,
            target_file=task.target_file,
            target_symbol=task.target_symbol,
            contract_version=task.contract_version_initial,
            ast_hash=compute_canonical_ast_hash(task.pre_compaction_failed_patch.files),
            witness_name=task.witness_name,
            witness_test_code=task.witness_test_code,
            failure_predicate=exec_res.failure_predicate,
            discovered_at_step=2,
        )
        ledger.record(ce)
        turns = _build_pre_compaction_turns(task, exec_res.failure_predicate)
        comp = compactor.compact(
            task.task_id,
            task.specification,
            task.contract_version_initial,
            turns,
            CompactionStrategy.CEGAR_HARNESS_FULL,
            ledger,
        )
        gen = llm.generate_patch(comp.rendered_context, task.target_file)
        if not gen.executed:
            live_results.append(
                {
                    "task_id": task.task_id,
                    "status": gen.status,
                    "error": gen.error_message,
                }
            )
            continue

        candidate_files = dict(task.initial_files)
        candidate_files[task.target_file] = gen.generated_code
        gate = RegressionGate(ledger=ledger, runner=runner)
        gate_res = gate.evaluate(task.task_id, candidate_files, task.contract_version_post_compaction)
        oracle_res = runner.run_test_code(candidate_files, task.reference_test_code)
        live_results.append(
            {
                "task_id": task.task_id,
                "status": "EXECUTED",
                "gate_status": gate_res.status.value,
                "oracle_passed": oracle_res.passed,
                "prompt_tokens": gen.prompt_tokens,
                "completion_tokens": gen.completion_tokens,
            }
        )

    ledger.close()
    return {
        "executed": True,
        "status": "EXECUTED",
        "model_name": llm.model_name,
        "results": live_results,
    }


def _export_reports(
    out_path: Path,
    report: Dict[str, Any],
    strategies: List[StrategySummaryMetrics],
    ablations: List[AblationSummaryMetrics],
    categories: List[Dict[str, Any]],
) -> None:
    """Writes JSON, CSV, and Markdown summary reports to `out_path`."""
    json_file = out_path / "benchmark_report.json"
    json_file.write_text(json.dumps(report, indent=2), encoding="utf-8")

    strat_csv = out_path / "strategy_metrics.csv"
    with strat_csv.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(asdict(strategies[0]).keys()))
        writer.writeheader()
        for s in strategies:
            writer.writerow(asdict(s))

    ablation_csv = out_path / "ablation_metrics.csv"
    with ablation_csv.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(asdict(ablations[0]).keys()))
        writer.writeheader()
        for a in ablations:
            writer.writerow(asdict(a))

    cat_csv = out_path / "category_breakdown.csv"
    with cat_csv.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(categories[0].keys()))
        writer.writeheader()
        for c in categories:
            writer.writerow(c)

    md_lines = [
        "# CEGAR-Harness Empirical Benchmark Report",
        "",
        "## 1. Experiment A: Context Compaction Strategies (30 Tasks)",
        "",
        "| Strategy | Mean Tokens Before | Mean Tokens After | Compression (%) | Witness Retention (%) | Gate Blocked | Unblocked Regressions (%) | False Block (%) | Resolution Rate (%) |",
        "| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for s in strategies:
        md_lines.append(
            f"| `{s.strategy}` | {s.mean_tokens_before:.1f} | {s.mean_tokens_after:.1f} | "
            f"{s.mean_compression_ratio_pct:.2f}% | {s.witness_retention_rate_pct:.1f}% | "
            f"{s.regressions_blocked_by_gate} | {s.unblocked_regression_rate_pct:.2f}% ({s.unblocked_regressions}/{s.tasks_total}) | "
            f"{s.false_block_rate_pct:.2f}% | {s.resolution_rate_pct:.2f}% ({s.tasks_resolved}/{s.tasks_total}) |"
        )

    md_lines.extend(
        [
            "",
            "## 2. Experiment A: Regression Gate Ablation Study (30 Tasks, 60 Candidate Evaluations)",
            "",
            "| Ablation Config | AST Filter | Witness Replay | Contract Ver. | Regression Recall (%) | Cat. 6 Syntactic Recall (%) | False Block Rate (%) | Inconclusive | Final Resolved (%) | Mean Gate Latency (ms) |",
            "| :--- | :---: | :---: | :---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for a in ablations:
        md_lines.append(
            f"| `{a.config_id}` | {'ON' if a.enable_ast_filter else 'OFF'} | "
            f"{'ON' if a.enable_witness_replay else 'OFF'} | "
            f"{'ON' if a.enforce_contract_version else 'OFF'} | "
            f"{a.regression_recall_pct:.2f}% ({a.regressions_caught}/{a.total_regression_candidates}) | "
            f"{a.cat6_recall_pct:.1f}% ({a.cat6_syntactic_variants_caught}/{a.cat6_syntactic_variants_total}) | "
            f"{a.false_block_rate_pct:.2f}% ({a.false_blocks_on_valid}/{a.valid_candidates_evaluated}) | "
            f"{a.inconclusive_on_evolved_contract} | "
            f"{a.final_resolution_rate_pct:.2f}% ({a.final_tasks_resolved}/30) | "
            f"{a.mean_gate_latency_ms:.2f} |"
        )

    md_lines.extend(
        [
            "",
            "## 3. Experiment A: Per-Category Regression Breakdown",
            "",
            "| Category | Tasks | Obs. Masking Unblocked Reg. | CEGAR Ledger-Only Unblocked Reg. | CEGAR Full Unblocked Reg. | CEGAR Full Resolved | Inconclusive (Contract Drift) |",
            "| :--- | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for c in categories:
        md_lines.append(
            f"| `{c['category']}` | {c['tasks_count']} | "
            f"{c['obs_masking_unblocked_regressions']}/{c['tasks_count']} | "
            f"{c['cegar_ledger_only_unblocked_regressions']}/{c['tasks_count']} | "
            f"{c['cegar_full_unblocked_regressions']}/{c['tasks_count']} | "
            f"{c['cegar_full_resolved']}/{c['tasks_count']} | "
            f"{c['cegar_full_inconclusive_gates']} |"
        )

    exp_b = report["experiment_b_live_llm"]
    md_lines.extend(
        [
            "",
            "## 4. Experiment B: Live LLM Agent Continuation",
            "",
            f"- **Status:** `{exp_b['status']}`",
            f"- **Executed:** `{exp_b['executed']}`",
            f"- **Model:** `{exp_b['model_name']}`",
            f"- **Note:** {exp_b.get('message', 'Live LLM execution completed.')}",
            "",
        ]
    )

    (out_path / "benchmark_summary.md").write_text("\n".join(md_lines), encoding="utf-8")
