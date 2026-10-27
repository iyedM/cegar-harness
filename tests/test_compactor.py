"""Unit tests for the 5 context compaction strategies."""

from cegar_harness.compactor import CompactionController, TrajectoryTurn
from cegar_harness.ledger import CounterexampleLedger
from cegar_harness.models import CompactionStrategy, CounterexampleRecord


def test_compaction_strategies_preserve_or_drop_witnesses() -> None:
    ledger = CounterexampleLedger(":memory:")
    predicate = "ASSERTION_FAILED: test_negative_amount: ValueError not raised"
    ledger.record(
        CounterexampleRecord(
            ce_id="CE-01",
            task_id="T01",
            target_file="pay.py",
            target_symbol="charge",
            contract_version="v1",
            ast_hash="abc123456789",
            witness_name="test_negative_amount",
            witness_test_code="def test_negative_amount(): assert False",
            failure_predicate=predicate,
            discovered_at_step=2,
        )
    )

    turns = [
        TrajectoryTurn(step=1, role="agent_action", content="Proposed patch 1"),
        TrajectoryTurn(
            step=2,
            role="tool_observation",
            content="Verbose test log " * 80 + "\n" + predicate,
            is_failure_observation=True,
            witness_predicate=predicate,
        ),
        TrajectoryTurn(step=3, role="agent_action", content="Reading file..."),
        TrajectoryTurn(step=4, role="tool_observation", content="File contents " * 60),
        TrajectoryTurn(step=5, role="agent_action", content="Inspecting helper..."),
        TrajectoryTurn(step=6, role="tool_observation", content="Recent observation"),
    ]
    controller = CompactionController(sliding_window_turns=2)

    res_full = controller.compact("T01", "Spec text", "v1", turns, CompactionStrategy.FULL_HISTORY, ledger)
    res_mask = controller.compact("T01", "Spec text", "v1", turns, CompactionStrategy.OBSERVATION_MASKING, ledger)
    res_lossy = controller.compact("T01", "Spec text", "v1", turns, CompactionStrategy.LOSSY_SUMMARY, ledger)
    res_cegar = controller.compact("T01", "Spec text", "v1", turns, CompactionStrategy.CEGAR_HARNESS_FULL, ledger)

    assert res_full.witness_predicate_retained is True
    assert res_mask.witness_predicate_retained is False
    assert res_lossy.witness_predicate_retained is False
    assert res_cegar.witness_predicate_retained is True
    assert res_cegar.tokens_after < res_full.tokens_before
    ledger.close()
