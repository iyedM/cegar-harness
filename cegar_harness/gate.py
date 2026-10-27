"""Three-State Regression Gate (PASS, REGRESSION_DETECTED, INCONCLUSIVE)."""

from __future__ import annotations

import time
from typing import Dict, Optional

from cegar_harness.ast_filter import compute_canonical_ast_hash
from cegar_harness.ledger import CounterexampleLedger
from cegar_harness.models import GateEvaluationResult, GateStatus
from cegar_harness.replay import IsolatedTestRunner
from cegar_harness.telemetry import TelemetryRecorder


class RegressionGate:
    """Evaluates candidate patches against the persistent Counterexample Ledger.

    Supports ablation configurations:
      - enable_ast_filter: fast syntactic check for exact/alpha-renamed AST duplicates
      - enable_witness_replay: behavioral execution of stored failing witness tests
      - enforce_contract_version: returns INCONCLUSIVE instead of REGRESSION_DETECTED
        when a witness fails under a newer specification/contract version.
    """

    def __init__(
        self,
        ledger: CounterexampleLedger,
        runner: Optional[IsolatedTestRunner] = None,
        telemetry: Optional[TelemetryRecorder] = None,
        enable_ast_filter: bool = True,
        enable_witness_replay: bool = True,
        enforce_contract_version: bool = True,
    ) -> None:
        self.ledger = ledger
        self.runner = runner or IsolatedTestRunner()
        self.telemetry = telemetry
        self.enable_ast_filter = enable_ast_filter
        self.enable_witness_replay = enable_witness_replay
        self.enforce_contract_version = enforce_contract_version

    def evaluate(
        self,
        task_id: str,
        candidate_files: Dict[str, str],
        current_contract_version: str,
    ) -> GateEvaluationResult:
        """Evaluates a candidate patch and returns PASS, REGRESSION_DETECTED, or INCONCLUSIVE."""
        start_ns = time.perf_counter_ns()
        ast_hash = compute_canonical_ast_hash(candidate_files)
        records = self.ledger.get_by_task(task_id, include_resolved=True)

        if not records:
            latency_ms = (time.perf_counter_ns() - start_ns) / 1e6
            res = GateEvaluationResult(
                status=GateStatus.PASS,
                triggered_by="none",
                reason="No prior counterexamples in ledger for task.",
                latency_ms=latency_ms,
                witnesses_checked=0,
                ast_hash=ast_hash,
            )
            self._emit_telemetry(task_id, res)
            return res

        # Stage 1: Optional syntactic AST pre-filter (optimization, not semantic proof)
        if self.enable_ast_filter:
            for ce in records:
                if ce.ast_hash == ast_hash:
                    latency_ms = (time.perf_counter_ns() - start_ns) / 1e6
                    if self.enforce_contract_version and ce.contract_version != current_contract_version:
                        if not self.enable_witness_replay:
                            res = GateEvaluationResult(
                                status=GateStatus.INCONCLUSIVE,
                                triggered_by="contract_mismatch",
                                matched_ce_id=ce.ce_id,
                                reason=(
                                    f"AST matches {ce.ce_id}, but contract version changed "
                                    f"({ce.contract_version} -> {current_contract_version})."
                                ),
                                latency_ms=latency_ms,
                                witnesses_checked=0,
                                ast_hash=ast_hash,
                            )
                            self._emit_telemetry(task_id, res)
                            return res
                        continue
                    res = GateEvaluationResult(
                        status=GateStatus.REGRESSION_DETECTED,
                        triggered_by="ast_filter",
                        matched_ce_id=ce.ce_id,
                        reason=f"Canonical AST matches previously refuted patch ({ce.ce_id}: {ce.failure_predicate})",
                        latency_ms=latency_ms,
                        witnesses_checked=0,
                        ast_hash=ast_hash,
                    )
                    self._emit_telemetry(task_id, res)
                    return res

        # Stage 2: Isolated Witness Replay
        witnesses_checked = 0
        inconclusive_match: Optional[GateEvaluationResult] = None

        if self.enable_witness_replay:
            for ce in records:
                witnesses_checked += 1
                exec_res = self.runner.run_test_code(candidate_files, ce.witness_test_code)
                if exec_res.execution_error or exec_res.timed_out:
                    latency_ms = (time.perf_counter_ns() - start_ns) / 1e6
                    res = GateEvaluationResult(
                        status=GateStatus.INCONCLUSIVE,
                        triggered_by="replay_error",
                        matched_ce_id=ce.ce_id,
                        reason=f"Witness replay execution error on {ce.ce_id}: {exec_res.failure_predicate}",
                        latency_ms=latency_ms,
                        witnesses_checked=witnesses_checked,
                        ast_hash=ast_hash,
                    )
                    self._emit_telemetry(task_id, res)
                    return res

                if not exec_res.passed:
                    latency_ms = (time.perf_counter_ns() - start_ns) / 1e6
                    if self.enforce_contract_version and ce.contract_version != current_contract_version:
                        inconclusive_match = GateEvaluationResult(
                            status=GateStatus.INCONCLUSIVE,
                            triggered_by="contract_mismatch",
                            matched_ce_id=ce.ce_id,
                            reason=(
                                f"Witness {ce.ce_id} failed ({exec_res.failure_predicate}), "
                                f"but witness contract ({ce.contract_version}) differs from "
                                f"active contract ({current_contract_version})."
                            ),
                            latency_ms=latency_ms,
                            witnesses_checked=witnesses_checked,
                            ast_hash=ast_hash,
                        )
                        continue

                    res = GateEvaluationResult(
                        status=GateStatus.REGRESSION_DETECTED,
                        triggered_by="witness_replay",
                        matched_ce_id=ce.ce_id,
                        reason=f"Witness {ce.ce_id} ({ce.witness_name}) failed: {exec_res.failure_predicate}",
                        latency_ms=latency_ms,
                        witnesses_checked=witnesses_checked,
                        ast_hash=ast_hash,
                    )
                    self._emit_telemetry(task_id, res)
                    return res

        if inconclusive_match is not None:
            inconclusive_match.latency_ms = (time.perf_counter_ns() - start_ns) / 1e6
            inconclusive_match.witnesses_checked = witnesses_checked
            self._emit_telemetry(task_id, inconclusive_match)
            return inconclusive_match

        latency_ms = (time.perf_counter_ns() - start_ns) / 1e6
        res = GateEvaluationResult(
            status=GateStatus.PASS,
            triggered_by="none",
            reason="All applicable counterexample witnesses passed.",
            latency_ms=latency_ms,
            witnesses_checked=witnesses_checked,
            ast_hash=ast_hash,
        )
        self._emit_telemetry(task_id, res)
        return res

    def _emit_telemetry(self, task_id: str, res: GateEvaluationResult) -> None:
        if self.telemetry:
            self.telemetry.record_gate_evaluation(task_id=task_id, result=res)
