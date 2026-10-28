"""LangGraph-compatible Middleware and Node Adapter for CEGAR-Harness."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from cegar_harness.ast_filter import compute_canonical_ast_hash
from cegar_harness.compactor import CompactionController, TrajectoryTurn, estimate_tokens
from cegar_harness.gate import RegressionGate
from cegar_harness.ledger import CounterexampleLedger
from cegar_harness.models import CompactionStrategy, CounterexampleRecord, GateStatus
from cegar_harness.replay import IsolatedTestRunner
from cegar_harness.telemetry import TelemetryRecorder


@dataclass
class AgentGraphState:
    """Typed state container compatible with LangGraph StateGraph workflows."""

    task_id: str
    specification: str
    contract_version: str = "v1"
    turns: List[TrajectoryTurn] = field(default_factory=list)
    compacted_prompt: str = ""
    compaction_count: int = 0
    gate_interceptions: int = 0
    last_gate_status: str = "NONE"


class CEGARHarnessMiddleware:
    """Reusable middleware that wraps LangGraph / agentic tool execution and context compaction.

    Responsibilities:
      1. Intercepts code-editing tool calls (`apply_patch`, `write_file`) before execution and
         evaluates them against the SQLite CounterexampleLedger via `RegressionGate`.
      2. Short-circuits regressive patches (`GateStatus.REGRESSION_DETECTED`) and returns a
         structured refutation observation to the agent without running the full test suite.
      3. Synthesizes and records new counterexamples when an oracle test fails.
      4. Automatically triggers `CompactionController` when trajectory tokens exceed `token_budget`.
    """

    def __init__(
        self,
        db_path: str | Path = ":memory:",
        token_budget: int = 450,
        strategy: CompactionStrategy = CompactionStrategy.CEGAR_HARNESS_FULL,
        sliding_window_turns: int = 2,
        jsonl_path: Optional[str | Path] = None,
    ) -> None:
        self.ledger = CounterexampleLedger(db_path)
        self.runner = IsolatedTestRunner(timeout_seconds=5.0)
        self.telemetry = TelemetryRecorder(jsonl_path)
        self.gate = RegressionGate(
            ledger=self.ledger,
            runner=self.runner,
            telemetry=self.telemetry,
        )
        self.compactor = CompactionController(sliding_window_turns=sliding_window_turns)
        self.token_budget = token_budget
        self.strategy = strategy

    def intercept_code_edit(
        self,
        state: AgentGraphState,
        candidate_files: Dict[str, str],
        tool_executor: Optional[Callable[[Dict[str, str]], str]] = None,
    ) -> Dict[str, Any]:
        """LangGraph tool-node interceptor for code modifications."""
        step_num = len(state.turns) + 1
        state.turns.append(
            TrajectoryTurn(
                step=step_num,
                role="agent_action",
                content=f"Tool call `apply_patch` on {sorted(candidate_files.keys())}",
            )
        )

        gate_res = self.gate.evaluate(
            task_id=state.task_id,
            candidate_files=candidate_files,
            current_contract_version=state.contract_version,
        )
        state.last_gate_status = gate_res.status.value

        if gate_res.status == GateStatus.REGRESSION_DETECTED:
            state.gate_interceptions += 1
            feedback = (
                f"[CEGAR_REGRESSION_BLOCKED | ce_id={gate_res.matched_ce_id} | "
                f"triggered_by={gate_res.triggered_by}] {gate_res.reason}"
            )
            state.turns.append(
                TrajectoryTurn(
                    step=step_num + 1,
                    role="tool_observation",
                    content=feedback,
                    is_failure_observation=True,
                    witness_predicate=gate_res.reason,
                )
            )
            self.maybe_compact(state)
            return {
                "allowed": False,
                "gate_status": gate_res.status.value,
                "matched_ce_id": gate_res.matched_ce_id,
                "observation": feedback,
            }

        obs_text = (
            tool_executor(candidate_files)
            if tool_executor is not None
            else f"Applied patch to {sorted(candidate_files.keys())} (Gate: {gate_res.status.value})"
        )
        state.turns.append(
            TrajectoryTurn(
                step=step_num + 1,
                role="tool_observation",
                content=obs_text,
            )
        )
        self.maybe_compact(state)
        return {
            "allowed": True,
            "gate_status": gate_res.status.value,
            "matched_ce_id": gate_res.matched_ce_id,
            "observation": obs_text,
        }

    def record_oracle_failure(
        self,
        state: AgentGraphState,
        ce_id: str,
        target_file: str,
        target_symbol: str,
        failed_files: Dict[str, str],
        witness_name: str,
        witness_test_code: str,
    ) -> CounterexampleRecord:
        """Runs the failing witness to extract its failure predicate and records it in SQLite."""
        exec_res = self.runner.run_test_code(failed_files, witness_test_code)
        step_num = len(state.turns) + 1
        ce = CounterexampleRecord(
            ce_id=ce_id,
            task_id=state.task_id,
            target_file=target_file,
            target_symbol=target_symbol,
            contract_version=state.contract_version,
            ast_hash=compute_canonical_ast_hash(failed_files),
            witness_name=witness_name,
            witness_test_code=witness_test_code,
            failure_predicate=exec_res.failure_predicate,
            discovered_at_step=step_num,
            status="ACTIVE",
            provenance="langgraph_oracle_failure",
        )
        self.ledger.record(ce)
        state.turns.append(
            TrajectoryTurn(
                step=step_num,
                role="tool_observation",
                content=f"FAILED {target_file}::{witness_name} -> {exec_res.failure_predicate}",
                is_failure_observation=True,
                witness_predicate=exec_res.failure_predicate,
            )
        )
        self.maybe_compact(state)
        return ce

    def maybe_compact(self, state: AgentGraphState, force: bool = False) -> bool:
        """Triggers context compaction if current trajectory exceeds `token_budget` or `force=True`."""
        raw_text = "\n".join(t.content for t in state.turns)
        if not force and estimate_tokens(raw_text) < self.token_budget:
            return False

        comp_res = self.compactor.compact(
            task_id=state.task_id,
            specification=state.specification,
            contract_version=state.contract_version,
            turns=state.turns,
            strategy=self.strategy,
            ledger=self.ledger,
        )
        state.compacted_prompt = comp_res.rendered_context
        state.compaction_count += 1
        self.telemetry.record_compaction(
            task_id=state.task_id,
            strategy=self.strategy.value,
            tokens_before=comp_res.tokens_before,
            tokens_after=comp_res.tokens_after,
            witness_retained=comp_res.witness_predicate_retained,
        )
        return True

    def close(self) -> None:
        self.ledger.close()
