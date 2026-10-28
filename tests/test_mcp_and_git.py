"""End-to-end tests for GitWorkspaceAdapter, MCP JSON-RPC 2.0 Server, and LangGraph Middleware."""

from __future__ import annotations

import io
import json
import subprocess
from pathlib import Path

from cegar_harness.ast_filter import compute_canonical_ast_hash
from cegar_harness.gate import RegressionGate
from cegar_harness.git_workspace import GitWorkspaceAdapter
from cegar_harness.langgraph_adapter import AgentGraphState, CEGARHarnessMiddleware
from cegar_harness.ledger import CounterexampleLedger
from cegar_harness.mcp_server import CEGARMCPServer
from cegar_harness.models import CounterexampleRecord, GateStatus
from cegar_harness.replay import IsolatedTestRunner


def _init_temp_git_repo(repo_dir: Path, initial_files: dict[str, str]) -> None:
    repo_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init"], cwd=str(repo_dir), check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@cegar.local"],
        cwd=str(repo_dir),
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "CEGAR Test"],
        cwd=str(repo_dir),
        check=True,
        capture_output=True,
    )
    for rel, content in initial_files.items():
        target = repo_dir / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=str(repo_dir), check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "initial commit"],
        cwd=str(repo_dir),
        check=True,
        capture_output=True,
    )


def test_git_workspace_adapter_atomic_rollback_on_regression(tmp_path: Path) -> None:
    repo_dir = tmp_path / "repo"
    initial_code = "def clamp_limit(limit, max_limit=100):\n    return min(limit, max_limit)\n"
    _init_temp_git_repo(repo_dir, {"pagination.py": initial_code})

    ledger = CounterexampleLedger(":memory:")
    runner = IsolatedTestRunner(timeout_seconds=3.0)
    bad_files = {
        "pagination.py": (
            "def clamp_limit(limit, max_limit=100):\n"
            "    if limit < 0:\n"
            "        return 1\n"
            "    return min(limit, max_limit)\n"
        )
    }
    witness_code = (
        "from pagination import clamp_limit\n"
        "def test_zero_clamped():\n"
        "    assert clamp_limit(0, 100) == 1\n"
    )
    exec_res = runner.run_test_code(bad_files, witness_code)
    assert not exec_res.passed

    ledger.record(
        CounterexampleRecord(
            ce_id="CE-GIT-01",
            task_id="T01",
            target_file="pagination.py",
            target_symbol="clamp_limit",
            contract_version="v1",
            ast_hash=compute_canonical_ast_hash(bad_files),
            witness_name="test_zero_clamped",
            witness_test_code=witness_code,
            failure_predicate=exec_res.failure_predicate,
            discovered_at_step=1,
        )
    )

    gate = RegressionGate(ledger=ledger, runner=runner)
    adapter = GitWorkspaceAdapter(repo_path=repo_dir, gate=gate)

    # 1. Attempting to apply a syntactic variant regression triggers atomic rollback
    syn_variant_bad = {
        "pagination.py": (
            "def clamp_limit(limit, max_limit=100):\n"
            "    return 1 if limit < 0 else min(limit, max_limit)\n"
        )
    }
    res_reg = adapter.apply_candidate_files("T01", syn_variant_bad, contract_version="v1")
    assert res_reg.applied is False
    assert res_reg.rolled_back is True
    assert res_reg.gate_result.status == GateStatus.REGRESSION_DETECTED
    assert "def clamp_limit" in res_reg.git_diff
    # Verify working tree was atomically rolled back to initial_code
    assert (repo_dir / "pagination.py").read_text(encoding="utf-8") == initial_code
    assert adapter.get_working_diff() == ""

    # 2. Applying a valid patch via unified diff succeeds and stays applied
    unified_diff = (
        "--- a/pagination.py\n"
        "+++ b/pagination.py\n"
        "@@ -1,2 +1,4 @@\n"
        " def clamp_limit(limit, max_limit=100):\n"
        "+    if limit <= 0:\n"
        "+        return 1\n"
        "     return min(limit, max_limit)\n"
    )
    res_ok = adapter.apply_unified_diff(
        task_id="T01",
        unified_diff=unified_diff,
        tracked_files=["pagination.py"],
        contract_version="v1",
    )
    assert res_ok.applied is True
    assert res_ok.rolled_back is False
    assert res_ok.gate_result.status == GateStatus.PASS
    assert "if limit <= 0:" in (repo_dir / "pagination.py").read_text(encoding="utf-8")
    ledger.close()


def test_mcp_jsonrpc_server_stdio_and_four_tools(tmp_path: Path) -> None:
    db_file = tmp_path / "mcp_ledger.sqlite"
    server = CEGARMCPServer(db_path=db_file)

    requests = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "cegar_record_witness",
                "arguments": {
                    "ce_id": "CE-MCP-01",
                    "task_id": "T26",
                    "target_file": "filters.py",
                    "target_symbol": "compact_ints",
                    "contract_version": "v1",
                    "files": {
                        "filters.py": "def compact_ints(items):\n    return [x for x in items if x]\n"
                    },
                    "witness_name": "test_zero_preserved",
                    "witness_test_code": (
                        "from filters import compact_ints\n"
                        "def test_zero_preserved():\n"
                        "    assert compact_ints([0, 1, None, 2]) == [0, 1, 2]\n"
                    ),
                },
            },
        },
        {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {
                "name": "cegar_evaluate_patch",
                "arguments": {
                    "task_id": "T26",
                    "contract_version": "v1",
                    "files": {
                        "filters.py": (
                            "def compact_ints(items):\n"
                            "    out = []\n"
                            "    for item in items:\n"
                            "        if item:\n"
                            "            out.append(item)\n"
                            "    return out\n"
                        )
                    },
                },
            },
        },
        {
            "jsonrpc": "2.0",
            "id": 5,
            "method": "tools/call",
            "params": {
                "name": "cegar_compact_trajectory",
                "arguments": {
                    "task_id": "T26",
                    "specification": "Keep 0, drop None.",
                    "contract_version": "v1",
                    "strategy": "CEGAR_HARNESS_FULL",
                    "turns": [
                        {
                            "step": 1,
                            "role": "agent_action",
                            "content": "Trying `[x for x in items if x]`",
                        },
                        {
                            "step": 2,
                            "role": "tool_observation",
                            "content": "FAILED test_zero_preserved: [1, 2] != [0, 1, 2]\n" + ("log line\n" * 20),
                            "is_failure_observation": True,
                            "witness_predicate": "ASSERTION_FAILED",
                        },
                        {
                            "step": 3,
                            "role": "agent_action",
                            "content": "Inspecting filters.py",
                        },
                    ],
                },
            },
        },
        {
            "jsonrpc": "2.0",
            "id": 6,
            "method": "tools/call",
            "params": {
                "name": "cegar_query_ledger",
                "arguments": {"task_id": "T26", "target_file": "filters.py"},
            },
        },
    ]

    in_buf = io.StringIO("\n".join(json.dumps(r) for r in requests) + "\n")
    out_buf = io.StringIO()
    server.serve_stdio(in_stream=in_buf, out_stream=out_buf)
    server.close()

    responses = [json.loads(line) for line in out_buf.getvalue().splitlines() if line.strip()]
    assert len(responses) == 6  # notification produces no response

    by_id = {r["id"]: r["result"] for r in responses}
    assert by_id[1]["serverInfo"]["name"] == "cegar-harness-mcp"
    tool_names = {t["name"] for t in by_id[2]["tools"]}
    assert tool_names == {
        "cegar_evaluate_patch",
        "cegar_record_witness",
        "cegar_compact_trajectory",
        "cegar_query_ledger",
    }

    assert by_id[3]["structuredContent"]["recorded"] is True
    assert by_id[4]["structuredContent"]["status"] == "REGRESSION_DETECTED"
    assert by_id[4]["structuredContent"]["triggered_by"] == "witness_replay"
    assert by_id[5]["structuredContent"]["pinned_counterexample_count"] == 1
    assert "CE-MCP-01" in by_id[5]["structuredContent"]["rendered_context"]
    assert by_id[6]["structuredContent"]["count"] == 1


def test_langgraph_middleware_interception_and_compaction() -> None:
    mw = CEGARHarnessMiddleware(db_path=":memory:", token_budget=60)
    state = AgentGraphState(
        task_id="T01",
        specification="Clamp limit <= 0 to 1.",
        contract_version="v1",
    )

    mw.record_oracle_failure(
        state=state,
        ce_id="CE-LG-01",
        target_file="pagination.py",
        target_symbol="clamp_limit",
        failed_files={"pagination.py": "def clamp_limit(x):\n    return 1 if x < 0 else x\n"},
        witness_name="test_zero",
        witness_test_code="from pagination import clamp_limit\ndef test_zero():\n    assert clamp_limit(0) == 1\n",
    )

    # Propose alpha-renamed regression -> blocked by middleware before tool execution
    res_blocked = mw.intercept_code_edit(
        state=state,
        candidate_files={"pagination.py": "def clamp_limit(val):\n    return 1 if val < 0 else val\n"},
    )
    assert res_blocked["allowed"] is False
    assert res_blocked["gate_status"] == "REGRESSION_DETECTED"
    assert state.gate_interceptions == 1

    # Propose valid fix -> allowed by middleware and triggers automatic compaction once over budget
    res_allowed = mw.intercept_code_edit(
        state=state,
        candidate_files={"pagination.py": "def clamp_limit(val):\n    return 1 if val <= 0 else val\n"},
    )
    assert res_allowed["allowed"] is True
    assert res_allowed["gate_status"] == "PASS"
    assert state.compaction_count >= 1
    assert "CE-LG-01" in state.compacted_prompt
    mw.close()
