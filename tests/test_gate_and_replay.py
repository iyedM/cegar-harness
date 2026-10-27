"""Unit tests for the SQLite CounterexampleLedger and 3-state RegressionGate."""

from pathlib import Path

from cegar_harness.ast_filter import compute_canonical_ast_hash
from cegar_harness.gate import RegressionGate
from cegar_harness.ledger import CounterexampleLedger
from cegar_harness.models import CounterexampleRecord, GateStatus
from cegar_harness.replay import IsolatedTestRunner
from cegar_harness.telemetry import TelemetryRecorder


def test_ledger_and_three_state_regression_gate(tmp_path: Path) -> None:
    db_file = tmp_path / "ledger.sqlite"
    jsonl_file = tmp_path / "events.jsonl"
    ledger = CounterexampleLedger(db_file)
    telemetry = TelemetryRecorder(jsonl_file)
    runner = IsolatedTestRunner(timeout_seconds=3.0)

    bad_files = {"calc.py": "def divide(a, b):\n    return a / b\n"}
    witness_code = (
        "from calc import divide\n"
        "def test_divide_by_zero_returns_none():\n"
        "    assert divide(10, 0) is None\n"
    )
    exec_res = runner.run_test_code(bad_files, witness_code)
    assert not exec_res.passed
    assert "ZeroDivisionError" in exec_res.failure_predicate

    ce = CounterexampleRecord(
        ce_id="CE-TEST-01",
        task_id="T01",
        target_file="calc.py",
        target_symbol="divide",
        contract_version="v1",
        ast_hash=compute_canonical_ast_hash(bad_files),
        witness_name="test_divide_by_zero_returns_none",
        witness_test_code=witness_code,
        failure_predicate=exec_res.failure_predicate,
        discovered_at_step=1,
    )
    ledger.record(ce)
    assert ledger.count("T01") == 1

    gate = RegressionGate(ledger=ledger, runner=runner, telemetry=telemetry)

    # 1. Alpha-renamed duplicate caught by AST filter
    renamed_bad = {"calc.py": "def divide(num, den):\n    return num / den\n"}
    res_ast = gate.evaluate("T01", renamed_bad, current_contract_version="v1")
    assert res_ast.status == GateStatus.REGRESSION_DETECTED
    assert res_ast.triggered_by == "ast_filter"

    # 2. Syntactically distinct variant of the same bug caught by Witness Replay
    syntactic_variant = {
        "calc.py": "def divide(a, b):\n    res = float(a) / float(b)\n    return res\n"
    }
    res_replay = gate.evaluate("T01", syntactic_variant, current_contract_version="v1")
    assert res_replay.status == GateStatus.REGRESSION_DETECTED
    assert res_replay.triggered_by == "witness_replay"

    # 3. Contract evolution (v1 -> v2 where divide by zero now raises ValueError instead of returning None)
    v2_valid_files = {
        "calc.py": (
            "def divide(a, b):\n"
            "    if b == 0:\n"
            "        raise ValueError('zero denominator')\n"
            "    return a / b\n"
        )
    }
    res_inconc = gate.evaluate("T01", v2_valid_files, current_contract_version="v2")
    assert res_inconc.status == GateStatus.INCONCLUSIVE
    assert res_inconc.triggered_by == "contract_mismatch"

    # 4. Valid v1 patch passes
    v1_valid_files = {
        "calc.py": "def divide(a, b):\n    return None if b == 0 else a / b\n"
    }
    res_pass = gate.evaluate("T01", v1_valid_files, current_contract_version="v1")
    assert res_pass.status == GateStatus.PASS
    assert len(telemetry.exporter.get_finished_spans()) == 4
    ledger.close()
