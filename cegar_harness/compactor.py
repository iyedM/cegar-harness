"""Context Compaction Controller implementing the 5 benchmark strategies."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List

from cegar_harness.ledger import CounterexampleLedger
from cegar_harness.models import CompactionStrategy, CounterexampleRecord


def estimate_tokens(text: str) -> int:
    """Deterministic subword/punctuation token count estimator for reproducible measurement."""
    if not text:
        return 0
    return len(re.findall(r"\w+|[^\w\s]", text))


@dataclass
class TrajectoryTurn:
    """Single turn in an agent's coding session prior to compaction."""

    step: int
    role: str  # "system", "agent_action", "tool_observation"
    content: str
    is_failure_observation: bool = False
    witness_predicate: str = ""


@dataclass
class CompactedContextResult:
    """Output of the Compaction Controller."""

    strategy: CompactionStrategy
    rendered_context: str
    tokens_before: int
    tokens_after: int
    compression_ratio: float
    witness_predicate_retained: bool
    pinned_counterexample_count: int


class CompactionController:
    """Applies one of five context compaction strategies to an agent trajectory."""

    def __init__(self, sliding_window_turns: int = 2) -> None:
        self.sliding_window_turns = sliding_window_turns

    def compact(
        self,
        task_id: str,
        specification: str,
        contract_version: str,
        turns: List[TrajectoryTurn],
        strategy: CompactionStrategy,
        ledger: CounterexampleLedger,
    ) -> CompactedContextResult:
        full_text = self._render_full_history(specification, contract_version, turns)
        tokens_before = estimate_tokens(full_text)

        witness_predicates = [t.witness_predicate for t in turns if t.witness_predicate]
        active_ces: List[CounterexampleRecord] = []

        if strategy == CompactionStrategy.FULL_HISTORY:
            rendered = full_text
        elif strategy == CompactionStrategy.OBSERVATION_MASKING:
            rendered = self._render_observation_masking(specification, contract_version, turns)
        elif strategy == CompactionStrategy.LOSSY_SUMMARY:
            rendered = self._render_lossy_summary(specification, contract_version, turns)
        elif strategy in (CompactionStrategy.CEGAR_LEDGER_ONLY, CompactionStrategy.CEGAR_HARNESS_FULL):
            active_ces = [
                ce
                for ce in ledger.get_by_task(task_id, include_resolved=False)
                if ce.contract_version == contract_version
            ]
            rendered = self._render_cegar_compacted(
                specification, contract_version, turns, active_ces
            )
        else:
            raise ValueError(f"Unsupported compaction strategy: {strategy}")

        tokens_after = estimate_tokens(rendered)
        ratio = 1.0 - (tokens_after / tokens_before) if tokens_before > 0 else 0.0
        retained = all(wp in rendered for wp in witness_predicates) if witness_predicates else True

        return CompactedContextResult(
            strategy=strategy,
            rendered_context=rendered,
            tokens_before=tokens_before,
            tokens_after=tokens_after,
            compression_ratio=round(ratio, 4),
            witness_predicate_retained=retained,
            pinned_counterexample_count=len(active_ces),
        )

    def _render_full_history(
        self, specification: str, contract_version: str, turns: List[TrajectoryTurn]
    ) -> str:
        blocks = [f"[SPECIFICATION v={contract_version}]\n{specification}\n"]
        for t in turns:
            blocks.append(f"[STEP {t.step} | {t.role.upper()}]\n{t.content}\n")
        return "\n".join(blocks)

    def _render_observation_masking(
        self, specification: str, contract_version: str, turns: List[TrajectoryTurn]
    ) -> str:
        """Masks older tool observations while keeping recent `sliding_window_turns` turns."""
        blocks = [f"[SPECIFICATION v={contract_version}]\n{specification}\n"]
        cutoff = max(0, len(turns) - self.sliding_window_turns)
        for idx, t in enumerate(turns):
            if idx < cutoff and t.role == "tool_observation":
                blocks.append(
                    f"[STEP {t.step} | TOOL_OBSERVATION_MASKED]\n"
                    f"<observation masked during context compaction ({estimate_tokens(t.content)} tokens elided)>\n"
                )
            else:
                blocks.append(f"[STEP {t.step} | {t.role.upper()}]\n{t.content}\n")
        return "\n".join(blocks)

    def _render_lossy_summary(
        self, specification: str, contract_version: str, turns: List[TrajectoryTurn]
    ) -> str:
        """Compresses older turns into a high-level narrative summary (dropping exact tracebacks/predicates)."""
        blocks = [f"[SPECIFICATION v={contract_version}]\n{specification}\n"]
        cutoff = max(0, len(turns) - self.sliding_window_turns)
        old_turns = turns[:cutoff]
        recent_turns = turns[cutoff:]

        fail_count = sum(1 for t in old_turns if t.is_failure_observation)
        blocks.append(
            "[COMPACTED EPISODIC SUMMARY]\n"
            f"The agent explored {len(old_turns)} prior steps and encountered {fail_count} test failure(s) "
            "while attempting initial candidate patches. Detailed tool outputs and stack traces were compacted.\n"
        )
        for t in recent_turns:
            blocks.append(f"[STEP {t.step} | {t.role.upper()}]\n{t.content}\n")
        return "\n".join(blocks)

    def _render_cegar_compacted(
        self,
        specification: str,
        contract_version: str,
        turns: List[TrajectoryTurn],
        active_ces: List[CounterexampleRecord],
    ) -> str:
        """Compresses verbose observations while pinning verified counterexample predicates."""
        blocks = [f"[SPECIFICATION v={contract_version}]\n{specification}\n"]
        if active_ces:
            blocks.append("[PINNED COUNTEREXAMPLE LEDGER (DO NOT REPEAT REFUTED MUTATIONS)]")
            for ce in active_ces:
                blocks.append(
                    f"- {ce.ce_id} ({ce.target_file}::{ce.target_symbol} | witness={ce.witness_name}): "
                    f"Failed with `{ce.failure_predicate}` | AST={ce.ast_hash[:12]}"
                )
            blocks.append("")

        cutoff = max(0, len(turns) - self.sliding_window_turns)
        for t in turns[cutoff:]:
            blocks.append(f"[STEP {t.step} | {t.role.upper()}]\n{t.content}\n")
        return "\n".join(blocks)
