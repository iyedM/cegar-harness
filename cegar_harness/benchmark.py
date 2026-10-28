"""Benchmark Runner for Experiment A (Multi-Turn Controlled Replay + Ablation) and Experiment B (Multi-Turn Live LLM)."""

from __future__ import annotations

import csv
import json
import math
import statistics
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

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


def _percentile(values: List[float], pct: float) -> float:
    """Computes a percentile (e.g. 95.0 for p95) on a non-empty list of floats."""
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, math.ceil((pct / 100.0) * len(ordered)) - 1))
    return ordered[idx]


def _wilson_ci_95(successes: int, total: int) -> Tuple[float, float]:
    """Computes the 95% Wilson score confidence interval (in percentage points) for a binomial proportion."""
    if total <= 0:
        return (0.0, 0.0)
    z = 1.959963984540054  # 95% normal quantile
    phat = successes / total
    denom = 1.0 + (z * z) / total
    center = (phat + (z * z) / (2.0 * total)) / denom
    half_width = (z * math.sqrt((phat * (1.0 - phat) + (z * z) / (4.0 * total)) / total)) / denom
    low = max(0.0, (center - half_width) * 100.0)
    high = min(100.0, (center + half_width) * 100.0)
    return (round(low, 2), round(high, 2))


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
    regression_ci95_low_pct: float
    regression_ci95_high_pct: float
    secondary_witnesses_synthesized: int
    false_blocks: int
    false_block_rate_pct: float
    inconclusive_gates: int
    turn1_resolved: int
    turn1_resolution_rate_pct: float
    tasks_resolved: int
    resolution_rate_pct: float
    resolution_ci95_low_pct: float
    resolution_ci95_high_pct: float
    mean_oracle_turns_to_convergence: float
    mean_gate_latency_ms: float
    median_gate_latency_ms: float
    p95_gate_latency_ms: float


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
    gate_precision_pct: float
    regression_recall_pct: float
    gate_f1_pct: float
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
    median_gate_latency_ms: float
    p95_gate_latency_ms: float
    mean_ledger_overhead_ms: float
    mean_replay_overhead_ms: float


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
    max_oracle_turns: int = 2,
) -> Dict[str, Any]:
    """Executes Experiment A (Multi-Turn Controlled Replay + Partial Witness Coverage + 4-way Ablation)."""
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

    # 2. Evaluate the 5 Context Compaction Strategies under a bounded multi-turn oracle budget
    strategy_summaries: List[StrategySummaryMetrics] = []
    per_task_strategy_details: Dict[str, List[Dict[str, Any]]] = {}

    for strategy in CompactionStrategy:
        tokens_before_list: List[int] = []
        tokens_after_list: List[int] = []
        compression_ratios: List[float] = []
        retained_count = 0
        blocked_by_gate = 0
        unblocked_regressions = 0
        secondary_witnesses = 0
        false_blocks = 0
        inconclusive_count = 0
        turn1_resolved_count = 0
        resolved_count = 0
        oracle_turns_list: List[int] = []
        gate_latencies: List[float] = []
        task_rows: List[Dict[str, Any]] = []

        use_gate = strategy == CompactionStrategy.CEGAR_HARNESS_FULL
        tracks_ledger = strategy in (
            CompactionStrategy.CEGAR_LEDGER_ONLY,
            CompactionStrategy.CEGAR_HARNESS_FULL,
        )
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
            partials = list(task.partial_coverage_candidates)
            distractors = (
                list(task.lossy_distractor_candidates)
                if strategy == CompactionStrategy.LOSSY_SUMMARY
                else []
            )

            # Candidate proposal queue conditioned on witness retention + partial witness coverage:
            # - If witness predicate was lost (OBSERVATION_MASKING, LOSSY_SUMMARY), the agent proposes
            #   [c1_reg, *distractors, *partials, c2_fix].
            # - If witness predicate was retained (FULL_HISTORY, CEGAR_LEDGER_ONLY, CEGAR_HARNESS_FULL),
            #   exact/alpha-renamed repeats on Categories 1-5 are avoided in prompt, EXCEPT Category 6
            #   syntactic variants where prompt text alone does not prevent a syntactically distinct rewrite.
            if not comp_res.witness_predicate_retained:
                proposed_queue: List[CandidatePatch] = [c1_reg, *distractors, *partials, c2_fix]
            else:
                if c1_reg.syntactic_variant_of is not None:
                    proposed_queue = [c1_reg, *partials, c2_fix]
                else:
                    proposed_queue = [*partials, c2_fix]

            task_resolved = False
            task_turn1_resolved = False
            task_unblocked_regression = False
            task_blocked_count = 0
            task_secondary_witnesses = 0
            task_false_block = False
            task_inconclusive = 0
            oracle_turns_used = 0

            for cand in proposed_queue:
                if oracle_turns_used >= max_oracle_turns:
                    break

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
                        # Pre-execution gate intercepted the regression before consuming an oracle turn
                        continue
                    elif gate_res.status == GateStatus.INCONCLUSIVE:
                        inconclusive_count += 1
                        task_inconclusive += 1

                # Candidate reaches full reference oracle evaluation (consumes 1 oracle turn)
                oracle_turns_used += 1
                witness_check = runner.run_test_code(cand.files, task.witness_test_code)
                oracle_check = runner.run_test_code(cand.files, task.reference_test_code)

                if not oracle_check.passed:
                    if not witness_check.passed or cand.is_known_regression:
                        if not task_unblocked_regression:
                            unblocked_regressions += 1
                            task_unblocked_regression = True
                    else:
                        # Candidate passed initial witness (Partial Witness Coverage) but failed reference suite!
                        if tracks_ledger:
                            secondary_witnesses += 1
                            task_secondary_witnesses += 1
                            if use_gate:
                                ce_round2 = CounterexampleRecord(
                                    ce_id=f"CE-{task.task_id}-0{1 + task_secondary_witnesses}",
                                    task_id=task.task_id,
                                    target_file=task.target_file,
                                    target_symbol=task.target_symbol,
                                    contract_version=cand.contract_version,
                                    ast_hash=compute_canonical_ast_hash(cand.files),
                                    witness_name=f"test_secondary_refinement_{task_secondary_witnesses}",
                                    witness_test_code=task.witness_test_code,
                                    failure_predicate=oracle_check.failure_predicate,
                                    discovered_at_step=6 + oracle_turns_used,
                                    status="ACTIVE",
                                    provenance="partial_witness_refinement",
                                )
                                ledger.record(ce_round2)
                    continue
                else:
                    task_resolved = True
                    resolved_count += 1
                    if oracle_turns_used == 1:
                        task_turn1_resolved = True
                        turn1_resolved_count += 1
                    break

            oracle_turns_list.append(oracle_turns_used)
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
                    "secondary_witnesses_synthesized": task_secondary_witnesses,
                    "false_block": task_false_block,
                    "inconclusive_gate": task_inconclusive,
                    "oracle_turns_used": oracle_turns_used,
                    "turn1_resolved": task_turn1_resolved,
                    "resolved": task_resolved,
                }
            )

        n_tasks = len(task_list)
        reg_ci_low, reg_ci_high = _wilson_ci_95(unblocked_regressions, n_tasks)
        res_ci_low, res_ci_high = _wilson_ci_95(resolved_count, n_tasks)

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
                regression_ci95_low_pct=reg_ci_low,
                regression_ci95_high_pct=reg_ci_high,
                secondary_witnesses_synthesized=secondary_witnesses,
                false_blocks=false_blocks,
                false_block_rate_pct=round((false_blocks / n_tasks) * 100.0, 2),
                inconclusive_gates=inconclusive_count,
                turn1_resolved=turn1_resolved_count,
                turn1_resolution_rate_pct=round((turn1_resolved_count / n_tasks) * 100.0, 2),
                tasks_resolved=resolved_count,
                resolution_rate_pct=round((resolved_count / n_tasks) * 100.0, 2),
                resolution_ci95_low_pct=res_ci_low,
                resolution_ci95_high_pct=res_ci_high,
                mean_oracle_turns_to_convergence=round(sum(oracle_turns_list) / n_tasks, 2),
                mean_gate_latency_ms=round(sum(gate_latencies) / len(gate_latencies), 3)
                if gate_latencies
                else 0.0,
                median_gate_latency_ms=round(statistics.median(gate_latencies), 3)
                if gate_latencies
                else 0.0,
                p95_gate_latency_ms=round(_percentile(gate_latencies, 95.0), 3)
                if gate_latencies
                else 0.0,
            )
        )
        per_task_strategy_details[strategy.value] = task_rows

    # 3. Reset ledger to initial pre-compaction state before running the 4-Way RegressionGate Ablation Study
    #    so all 4 ablation configs evaluate against the identical initial 30 witnesses (CE-T01-01 .. CE-T30-01)
    ablation_ledger = CounterexampleLedger(":memory:")
    for task in task_list:
        for ce in ledger.get_by_task(task.task_id, include_resolved=True):
            if ce.ce_id.endswith("-01"):
                ablation_ledger.record(ce)

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
            ledger=ablation_ledger,
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
        ledger_overheads: List[float] = []
        replay_overheads: List[float] = []

        for task in task_list:
            c1_reg, c2_fix = task.post_compaction_candidates[0], task.post_compaction_candidates[1]

            # Evaluate regression candidate c1_reg
            reg_total += 1
            if task.category == BugCategory.SYNTACTIC_VARIANTS:
                cat6_total += 1

            res_c1 = gate.evaluate(task.task_id, c1_reg.files, c1_reg.contract_version)
            latencies.append(res_c1.latency_ms)
            ledger_overheads.append(res_c1.ledger_lookup_ms)
            replay_overheads.append(res_c1.replay_latency_ms)

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
            ledger_overheads.append(res_c2.ledger_lookup_ms)
            replay_overheads.append(res_c2.replay_latency_ms)

            c2_blocked = res_c2.status == GateStatus.REGRESSION_DETECTED
            if c2_blocked:
                false_blocks_cnt += 1
                if task.category == BugCategory.FEATURE_REGRESSIONS:
                    cat5_false_blocks += 1
            elif res_c2.status == GateStatus.INCONCLUSIVE:
                inconc_evolved += 1

            # A task resolves in the 2-candidate ablation probe [c1_reg, c2_fix] iff c1_reg is blocked
            # by the gate and c2_fix is NOT falsely blocked by the gate (and passes the reference oracle).
            if c1_blocked and not c2_blocked:
                oracle_res = runner.run_test_code(c2_fix.files, task.reference_test_code)
                if oracle_res.passed:
                    tasks_resolved_cnt += 1

        tp = reg_caught
        fp = false_blocks_cnt
        precision = (tp / (tp + fp)) * 100.0 if (tp + fp) > 0 else 0.0
        recall = (tp / reg_total) * 100.0 if reg_total > 0 else 0.0
        f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0

        ablation_summaries.append(
            AblationSummaryMetrics(
                config_id=cfg_id,
                description=desc,
                enable_ast_filter=ast_on,
                enable_witness_replay=replay_on,
                enforce_contract_version=ver_on,
                total_regression_candidates=reg_total,
                regressions_caught=reg_caught,
                gate_precision_pct=round(precision, 2),
                regression_recall_pct=round(recall, 2),
                gate_f1_pct=round(f1, 2),
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
                median_gate_latency_ms=round(statistics.median(latencies), 3) if latencies else 0.0,
                p95_gate_latency_ms=round(_percentile(latencies, 95.0), 3) if latencies else 0.0,
                mean_ledger_overhead_ms=round(sum(ledger_overheads) / len(ledger_overheads), 3)
                if ledger_overheads
                else 0.0,
                mean_replay_overhead_ms=round(sum(replay_overheads) / len(replay_overheads), 3)
                if replay_overheads
                else 0.0,
            )
        )
    ablation_ledger.close()

    # 4. Compute Per-Category Breakdown across key strategies and ablations
    category_breakdown: List[Dict[str, Any]] = []
    for cat in BugCategory:
        cat_tasks = [t for t in task_list if t.category == cat]
        cat_ids = {t.task_id for t in cat_tasks}
        n_cat = len(cat_tasks)

        mask_rows = [
            r
            for r in per_task_strategy_details[CompactionStrategy.OBSERVATION_MASKING.value]
            if r["task_id"] in cat_ids
        ]
        ledger_rows = [
            r
            for r in per_task_strategy_details[CompactionStrategy.CEGAR_LEDGER_ONLY.value]
            if r["task_id"] in cat_ids
        ]
        full_rows = [
            r
            for r in per_task_strategy_details[CompactionStrategy.CEGAR_HARNESS_FULL.value]
            if r["task_id"] in cat_ids
        ]

        category_breakdown.append(
            {
                "category": cat.value,
                "tasks_count": n_cat,
                "obs_masking_unblocked_regressions": sum(1 for r in mask_rows if r["unblocked_regression"]),
                "obs_masking_resolved": sum(1 for r in mask_rows if r["resolved"]),
                "cegar_ledger_only_unblocked_regressions": sum(
                    1 for r in ledger_rows if r["unblocked_regression"]
                ),
                "cegar_ledger_only_resolved": sum(1 for r in ledger_rows if r["resolved"]),
                "cegar_full_unblocked_regressions": sum(1 for r in full_rows if r["unblocked_regression"]),
                "cegar_full_turn1_resolved": sum(1 for r in full_rows if r["turn1_resolved"]),
                "cegar_full_resolved": sum(1 for r in full_rows if r["resolved"]),
                "cegar_full_secondary_witnesses": sum(
                    r["secondary_witnesses_synthesized"] for r in full_rows
                ),
                "cegar_full_inconclusive_gates": sum(r["inconclusive_gate"] for r in full_rows),
            }
        )

    # 5. Experiment B status check (preserve existing executed live results if unconfigured, never simulate)
    exp_b_file = out_path / "experiment_b_live_results.json"
    existing_exp_b: Optional[Dict[str, Any]] = None
    if exp_b_file.exists():
        try:
            loaded_b = json.loads(exp_b_file.read_text(encoding="utf-8"))
            if loaded_b.get("executed") is True:
                existing_exp_b = loaded_b
        except Exception:
            existing_exp_b = None

    llm_probe = LiveLLMClient()
    if llm_probe.is_configured:
        exp_b_result = run_experiment_b(tasks=task_list[:6], client=llm_probe, max_turns=2, output_dir=out_path)
    elif existing_exp_b is not None:
        exp_b_result = existing_exp_b
    else:
        exp_b_result = run_experiment_b(tasks=task_list[:3], client=llm_probe, max_turns=2, output_dir=out_path)

    report = {
        "generated_at_epoch": time.time(),
        "benchmark_version": "0.2.0",
        "max_oracle_turns": max_oracle_turns,
        "experiment_a_controlled_replay": {
            "total_tasks": len(task_list),
            "categories_count": len(BugCategory),
            "max_oracle_turns": max_oracle_turns,
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
    max_turns: int = 2,
    strategies: Optional[List[CompactionStrategy]] = None,
    output_dir: Optional[str | Path] = None,
) -> Dict[str, Any]:
    """Executes Experiment B (Multi-Turn Live Agent Repair Loop) if configured, or reports NOT_EXECUTED_NO_CONFIG."""
    llm = client or LiveLLMClient()
    if not llm.is_configured:
        probe = llm.generate_patch("", "")
        res_payload = {
            "executed": False,
            "status": probe.status,
            "model_name": probe.model_name,
            "max_turns": max_turns,
            "cli_example": (
                "CEGAR_LLM_API_BASE=http://localhost:11434/v1 "
                "CEGAR_LLM_MODEL=llama3:latest "
                "cegar-harness live-eval --max-tasks 6 --max-turns 2"
            ),
            "message": probe.error_message,
            "strategy_summaries": [],
            "results": [],
        }
        if output_dir:
            Path(output_dir).mkdir(parents=True, exist_ok=True)
            (Path(output_dir) / "experiment_b_live_results.json").write_text(
                json.dumps(res_payload, indent=2), encoding="utf-8"
            )
        return res_payload

    if tasks is not None:
        task_list = tasks
    else:
        all_t = {t.task_id: t for t in get_all_tasks()}
        rep_ids = ["T01", "T06", "T11", "T16", "T21", "T26"]
        task_list = [all_t[tid] for tid in rep_ids if tid in all_t]

    eval_strategies = strategies or [
        CompactionStrategy.LOSSY_SUMMARY,
        CompactionStrategy.CEGAR_HARNESS_FULL,
    ]
    runner = IsolatedTestRunner(timeout_seconds=5.0)
    compactor = CompactionController(sliding_window_turns=2)

    live_results: List[Dict[str, Any]] = []
    strategy_summaries: List[Dict[str, Any]] = []

    for strategy in eval_strategies:
        use_gate = strategy == CompactionStrategy.CEGAR_HARNESS_FULL
        tracks_cegar = strategy in (
            CompactionStrategy.CEGAR_LEDGER_ONLY,
            CompactionStrategy.CEGAR_HARNESS_FULL,
        )
        strat_turn1_resolved = 0
        strat_final_resolved = 0
        strat_gate_blocks = 0
        strat_unblocked_regressions = 0
        strat_latencies: List[float] = []
        strat_prompt_tokens = 0
        strat_completion_tokens = 0

        for task in task_list:
            ledger = CounterexampleLedger(":memory:")
            exec_res = runner.run_test_code(
                task.pre_compaction_failed_patch.files, task.witness_test_code
            )
            ce = CounterexampleRecord(
                ce_id=f"CE-{task.task_id}-LIVE-01",
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

            # In LOSSY_SUMMARY / OBSERVATION_MASKING, exact witness assertions from Step 2 are lost;
            # the agent sees the current workspace file and high-level task title.
            # In CEGAR_LEDGER_ONLY / CEGAR_HARNESS_FULL, the pinned ledger preserves the exact specification,
            # contract version, and failing witness assertion.
            current_file_src = task.pre_compaction_failed_patch.files[task.target_file].strip()
            if tracks_cegar:
                spec_header = (
                    f"{task.specification}\n\n"
                    f"[CURRENT WORKSPACE FILE: {task.target_file}]\n```python\n{current_file_src}\n```\n\n"
                    f"[PINNED WITNESS TEST CODE ({task.witness_name})]\n```python\n{task.witness_test_code.strip()}\n```"
                )
            else:
                spec_header = (
                    f"Task {task.task_id} ({task.title}): Review `{task.target_symbol}` in `{task.target_file}`.\n"
                    f"[CURRENT WORKSPACE FILE: {task.target_file}]\n```python\n{current_file_src}\n```\n"
                    f"Note: Earlier test failure details were compacted. Return the Python module `{task.target_file}`."
                )

            comp = compactor.compact(
                task.task_id,
                spec_header,
                task.contract_version_initial,
                turns,
                strategy,
                ledger,
            )
            gate = RegressionGate(ledger=ledger, runner=runner)
            repair_feedback: List[str] = []
            turn_traces: List[Dict[str, Any]] = []
            resolved = False
            turn1_resolved = False
            total_prompt_tokens = 0
            total_completion_tokens = 0
            total_latency_ms = 0.0
            gate_blocks = 0
            unblocked_regs = 0

            for turn_idx in range(1, max_turns + 1):
                gen = llm.generate_patch(
                    comp.rendered_context,
                    task.target_file,
                    repair_feedback=repair_feedback if repair_feedback else None,
                )
                if not gen.executed:
                    turn_traces.append(
                        {
                            "turn": turn_idx,
                            "status": gen.status,
                            "error": gen.error_message,
                        }
                    )
                    break

                total_prompt_tokens += gen.prompt_tokens
                total_completion_tokens += gen.completion_tokens
                total_latency_ms += gen.latency_ms
                strat_latencies.append(gen.latency_ms)

                candidate_files = dict(task.initial_files)
                candidate_files[task.target_file] = gen.generated_code

                if use_gate:
                    gate_res = gate.evaluate(
                        task.task_id, candidate_files, task.contract_version_post_compaction
                    )
                    if gate_res.status == GateStatus.REGRESSION_DETECTED:
                        gate_blocks += 1
                        strat_gate_blocks += 1
                        repair_feedback.append(
                            f"Turn {turn_idx} REJECTED by CEGAR RegressionGate ({gate_res.matched_ce_id}, "
                            f"triggered_by={gate_res.triggered_by}): {gate_res.reason}\n"
                            f"Full Specification: {task.specification}\n"
                            f"You MUST fix the bug so that `{task.witness_name}` and all edge cases pass."
                        )
                        turn_traces.append(
                            {
                                "turn": turn_idx,
                                "llm_latency_ms": gen.latency_ms,
                                "prompt_tokens": gen.prompt_tokens,
                                "completion_tokens": gen.completion_tokens,
                                "gate_status": gate_res.status.value,
                                "triggered_by": gate_res.triggered_by,
                                "matched_ce_id": gate_res.matched_ce_id,
                                "oracle_executed": False,
                                "oracle_passed": False,
                                "generated_code": gen.generated_code,
                            }
                        )
                        continue
                else:
                    gate_res = None

                # Check if an un-gated candidate actually violates the initial witness (unblocked regression)
                wit_check = runner.run_test_code(candidate_files, task.witness_test_code)
                if (
                    not wit_check.passed
                    and task.contract_version_initial == task.contract_version_post_compaction
                ):
                    unblocked_regs += 1

                oracle_res = runner.run_test_code(candidate_files, task.reference_test_code)
                turn_traces.append(
                    {
                        "turn": turn_idx,
                        "llm_latency_ms": gen.latency_ms,
                        "prompt_tokens": gen.prompt_tokens,
                        "completion_tokens": gen.completion_tokens,
                        "gate_status": gate_res.status.value if gate_res else "BYPASSED",
                        "oracle_executed": True,
                        "oracle_passed": oracle_res.passed,
                        "failure_predicate": oracle_res.failure_predicate,
                        "generated_code": gen.generated_code,
                    }
                )
                if oracle_res.passed:
                    resolved = True
                    if turn_idx == 1:
                        turn1_resolved = True
                    break

                # Synthesize counterexample for next turn and append feedback
                if tracks_cegar:
                    new_ce = CounterexampleRecord(
                        ce_id=f"CE-{task.task_id}-LIVE-0{turn_idx + 1}",
                        task_id=task.task_id,
                        target_file=task.target_file,
                        target_symbol=task.target_symbol,
                        contract_version=task.contract_version_post_compaction,
                        ast_hash=compute_canonical_ast_hash(candidate_files),
                        witness_name=f"test_live_turn_{turn_idx}",
                        witness_test_code=task.reference_test_code,
                        failure_predicate=oracle_res.failure_predicate,
                        discovered_at_step=6 + turn_idx,
                    )
                    ledger.record(new_ce)
                    repair_feedback.append(
                        f"Turn {turn_idx} failed reference verification with exact counterexample predicate: "
                        f"`{oracle_res.failure_predicate}`.\n"
                        f"Full Specification: {task.specification}\n"
                        f"Reference Test Assertions:\n```python\n{task.reference_test_code.strip()}\n```"
                    )
                else:
                    repair_feedback.append(
                        f"Turn {turn_idx} failed test suite (1 failure; detailed witness predicate masked by lossy harness)."
                    )

            ledger.close()
            if turn1_resolved:
                strat_turn1_resolved += 1
            if resolved:
                strat_final_resolved += 1
            if unblocked_regs > 0:
                strat_unblocked_regressions += 1
            strat_prompt_tokens += total_prompt_tokens
            strat_completion_tokens += total_completion_tokens

            live_results.append(
                {
                    "task_id": task.task_id,
                    "category": task.category.value,
                    "target_file": task.target_file,
                    "target_symbol": task.target_symbol,
                    "strategy": strategy.value,
                    "turn1_resolved": turn1_resolved,
                    "resolved": resolved,
                    "turns_executed": len(turn_traces),
                    "gate_blocks": gate_blocks,
                    "unblocked_regressions": unblocked_regs,
                    "total_prompt_tokens": total_prompt_tokens,
                    "total_completion_tokens": total_completion_tokens,
                    "total_llm_latency_ms": round(total_latency_ms, 2),
                    "turn_traces": turn_traces,
                }
            )

        n_eval = len(task_list)
        ci_low, ci_high = _wilson_ci_95(strat_final_resolved, n_eval)
        strategy_summaries.append(
            {
                "strategy": strategy.value,
                "model_name": llm.model_name,
                "tasks_evaluated": n_eval,
                "max_turns": max_turns,
                "gate_regressions_blocked": strat_gate_blocks,
                "unblocked_regressions": strat_unblocked_regressions,
                "unblocked_regression_rate_pct": round((strat_unblocked_regressions / n_eval) * 100.0, 2)
                if n_eval
                else 0.0,
                "turn1_resolved": strat_turn1_resolved,
                "turn1_resolution_rate_pct": round((strat_turn1_resolved / n_eval) * 100.0, 2)
                if n_eval
                else 0.0,
                "final_resolved": strat_final_resolved,
                "final_resolution_rate_pct": round((strat_final_resolved / n_eval) * 100.0, 2)
                if n_eval
                else 0.0,
                "resolution_ci95_low_pct": ci_low,
                "resolution_ci95_high_pct": ci_high,
                "mean_llm_latency_ms": round(sum(strat_latencies) / len(strat_latencies), 2)
                if strat_latencies
                else 0.0,
                "total_prompt_tokens": strat_prompt_tokens,
                "total_completion_tokens": strat_completion_tokens,
            }
        )

    payload = {
        "executed": True,
        "status": "EXECUTED",
        "model_name": llm.model_name,
        "max_turns": max_turns,
        "tasks_evaluated": len(task_list),
        "task_ids": [t.task_id for t in task_list],
        "strategy_summaries": strategy_summaries,
        "results": live_results,
    }
    if output_dir:
        out_p = Path(output_dir)
        out_p.mkdir(parents=True, exist_ok=True)
        (out_p / "experiment_b_live_results.json").write_text(
            json.dumps(payload, indent=2), encoding="utf-8"
        )
        if strategy_summaries:
            exp_b_csv = out_p / "experiment_b_summary.csv"
            with exp_b_csv.open("w", newline="", encoding="utf-8") as fh:
                writer = csv.DictWriter(fh, fieldnames=list(strategy_summaries[0].keys()))
                writer.writeheader()
                for s_row in strategy_summaries:
                    writer.writerow(s_row)

        bench_report_file = out_p / "benchmark_report.json"
        if bench_report_file.exists():
            try:
                bench_report = json.loads(bench_report_file.read_text(encoding="utf-8"))
                bench_report["experiment_b_live_llm"] = payload
                bench_report_file.write_text(json.dumps(bench_report, indent=2), encoding="utf-8")
            except Exception:
                pass

    return payload


def _export_reports(
    out_path: Path,
    report: Dict[str, Any],
    strategies: List[StrategySummaryMetrics],
    ablations: List[AblationSummaryMetrics],
    categories: List[Dict[str, Any]],
) -> None:
    """Writes JSON, CSV, and Markdown summary reports to `out_path`."""
    json_payload = json.dumps(report, indent=2)
    (out_path / "benchmark_report.json").write_text(json_payload, encoding="utf-8")
    (out_path / "experiment_a_results.json").write_text(
        json.dumps(report["experiment_a_controlled_replay"], indent=2), encoding="utf-8"
    )
    (out_path / "ablation_study.json").write_text(
        json.dumps([asdict(a) for a in ablations], indent=2), encoding="utf-8"
    )

    for csv_name in ("strategy_metrics.csv", "experiment_a_summary.csv"):
        strat_csv = out_path / csv_name
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
        "## 1. Experiment A: Multi-Turn Context Compaction Strategies (30 Tasks, Max 2 Oracle Turns)",
        "",
        "| Strategy | Tokens (Before -> After) | Comp. (%) | Witness Retention (%) | Gate Blocked | Unblocked Reg. (%) [95% CI] | 2nd-Round Witnesses | Turn-1 Resolved (%) | Final Resolved (%) [95% CI] | Mean Oracle Turns |",
        "| :--- | :---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for s in strategies:
        md_lines.append(
            f"| `{s.strategy}` | {s.mean_tokens_before:.1f} -> {s.mean_tokens_after:.1f} | "
            f"{s.mean_compression_ratio_pct:.2f}% | {s.witness_retention_rate_pct:.1f}% | "
            f"{s.regressions_blocked_by_gate} | "
            f"{s.unblocked_regression_rate_pct:.2f}% [{s.regression_ci95_low_pct:.1f}, {s.regression_ci95_high_pct:.1f}] | "
            f"{s.secondary_witnesses_synthesized} | "
            f"{s.turn1_resolution_rate_pct:.2f}% ({s.turn1_resolved}/{s.tasks_total}) | "
            f"{s.resolution_rate_pct:.2f}% ({s.tasks_resolved}/{s.tasks_total}) [{s.resolution_ci95_low_pct:.1f}, {s.resolution_ci95_high_pct:.1f}] | "
            f"{s.mean_oracle_turns_to_convergence:.2f} |"
        )

    md_lines.extend(
        [
            "",
            "## 2. Experiment A: Regression Gate Ablation Study (30 Tasks, 60 Candidate Evaluations)",
            "",
            "| Ablation Config | AST Filter | Witness Replay | Contract Ver. | Precision (%) | Recall (%) | F1 (%) | Cat. 6 Syn. Recall (%) | False Block (%) | Inconclusive | Final Resolved (%) | Median / p95 Latency (ms) |",
            "| :--- | :---: | :---: | :---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for a in ablations:
        md_lines.append(
            f"| `{a.config_id}` | {'ON' if a.enable_ast_filter else 'OFF'} | "
            f"{'ON' if a.enable_witness_replay else 'OFF'} | "
            f"{'ON' if a.enforce_contract_version else 'OFF'} | "
            f"{a.gate_precision_pct:.2f}% | "
            f"{a.regression_recall_pct:.2f}% ({a.regressions_caught}/{a.total_regression_candidates}) | "
            f"{a.gate_f1_pct:.2f}% | "
            f"{a.cat6_recall_pct:.1f}% ({a.cat6_syntactic_variants_caught}/{a.cat6_syntactic_variants_total}) | "
            f"{a.false_block_rate_pct:.2f}% ({a.false_blocks_on_valid}/{a.valid_candidates_evaluated}) | "
            f"{a.inconclusive_on_evolved_contract} | "
            f"{a.final_resolution_rate_pct:.2f}% ({a.final_tasks_resolved}/30) | "
            f"{a.median_gate_latency_ms:.2f} / {a.p95_gate_latency_ms:.2f} |"
        )

    md_lines.extend(
        [
            "",
            "## 3. Experiment A: Per-Category Regression & Convergence Breakdown",
            "",
            "| Category | Tasks | Obs. Masking Unblocked Reg. | Obs. Masking Resolved | CEGAR Ledger-Only Unblocked Reg. | CEGAR Ledger-Only Resolved | CEGAR Full Unblocked Reg. | CEGAR Full Turn-1 Resolved | CEGAR Full Final Resolved | 2nd-Round Witnesses | Inconclusive |",
            "| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for c in categories:
        md_lines.append(
            f"| `{c['category']}` | {c['tasks_count']} | "
            f"{c['obs_masking_unblocked_regressions']}/{c['tasks_count']} | "
            f"{c['obs_masking_resolved']}/{c['tasks_count']} | "
            f"{c['cegar_ledger_only_unblocked_regressions']}/{c['tasks_count']} | "
            f"{c['cegar_ledger_only_resolved']}/{c['tasks_count']} | "
            f"{c['cegar_full_unblocked_regressions']}/{c['tasks_count']} | "
            f"{c['cegar_full_turn1_resolved']}/{c['tasks_count']} | "
            f"{c['cegar_full_resolved']}/{c['tasks_count']} | "
            f"{c['cegar_full_secondary_witnesses']} | "
            f"{c['cegar_full_inconclusive_gates']} |"
        )

    exp_b = report["experiment_b_live_llm"]
    md_lines.extend(
        [
            "",
            "## 4. Experiment B: Multi-Turn Live LLM Agent Repair Loop",
            "",
            f"- **Status:** `{exp_b['status']}`",
            f"- **Executed:** `{exp_b['executed']}`",
            f"- **Model:** `{exp_b['model_name']}`",
            f"- **Max Post-Compaction Turns:** `{exp_b.get('max_turns', 2)}`",
        ]
    )
    if exp_b.get("executed") and exp_b.get("strategy_summaries"):
        md_lines.extend(
            [
                "",
                "| Strategy | Model | Tasks | Gate Blocked | Unblocked Reg. (%) | Turn-1 Resolved (%) | Final Resolved (%) [95% CI] | Mean LLM Latency (ms) | Prompt / Completion Tokens |",
                "| :--- | :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
            ]
        )
        for sb in exp_b["strategy_summaries"]:
            md_lines.append(
                f"| `{sb['strategy']}` | `{sb['model_name']}` | {sb['tasks_evaluated']} | "
                f"{sb['gate_regressions_blocked']} | {sb['unblocked_regression_rate_pct']:.2f}% | "
                f"{sb['turn1_resolution_rate_pct']:.2f}% ({sb['turn1_resolved']}/{sb['tasks_evaluated']}) | "
                f"{sb['final_resolution_rate_pct']:.2f}% ({sb['final_resolved']}/{sb['tasks_evaluated']}) "
                f"[{sb['resolution_ci95_low_pct']:.1f}, {sb['resolution_ci95_high_pct']:.1f}] | "
                f"{sb['mean_llm_latency_ms']:.1f} | {sb['total_prompt_tokens']} / {sb['total_completion_tokens']} |"
            )
    else:
        md_lines.append(f"- **Note:** {exp_b.get('message', 'Live LLM execution completed.')}")
    md_lines.append("")

    (out_path / "benchmark_summary.md").write_text("\n".join(md_lines), encoding="utf-8")

