"""Adversarial security hardening test suite for CEGAR-Harness (CWE-22, DoS, XSS, SQLi, MCP, SSRF)."""

from __future__ import annotations

import http.client
import io
import json
import os
import subprocess
import threading
from pathlib import Path

import pytest

from cegar_harness.gate import RegressionGate
from cegar_harness.git_workspace import GitWorkspaceAdapter
from cegar_harness.ledger import CounterexampleLedger
from cegar_harness.llm_provider import LiveLLMClient
from cegar_harness.mcp_server import CEGARMCPServer
from cegar_harness.models import CounterexampleRecord
from cegar_harness.replay import IsolatedTestRunner
from cegar_harness.ui_server import MAX_POST_BODY_BYTES, create_ui_server


def _init_git_repo(repo_dir: Path) -> None:
    repo_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init"], cwd=str(repo_dir), check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "sec@cegar.local"], cwd=str(repo_dir), check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "CEGAR Sec"], cwd=str(repo_dir), check=True, capture_output=True)
    (repo_dir / "app.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=str(repo_dir), check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=str(repo_dir), check=True, capture_output=True)


def test_replay_blocks_classic_and_absolute_path_traversal() -> None:
    runner = IsolatedTestRunner(timeout_seconds=2.0)
    for bad_path in ["../../etc/passwd", "../outside.py", "/etc/passwd", "\\windows\\system32\\cmd.exe", ""]:
        res = runner.run_test_code(
            files={bad_path: "x = 1\n"},
            test_code="def test_ok():\n    assert True\n",
        )
        assert not res.passed
        assert res.exit_code == -2
        assert res.execution_error is True
        assert "SecurityError" in res.failure_predicate


def test_replay_blocks_cwe22_sibling_prefix_traversal(tmp_path: Path) -> None:
    sandbox_root = (tmp_path / "cegar_replay_root").resolve()
    sandbox_root.mkdir(parents=True, exist_ok=True)
    sibling_dir = (tmp_path / "cegar_replay_root_evil").resolve()
    sibling_dir.mkdir(parents=True, exist_ok=True)

    # A naive str(target).startswith(str(sandbox_root)) check would falsely allow ../cegar_replay_root_evil/pwn.py!
    ok, err_msg, _ = IsolatedTestRunner._validate_sandbox_path(
        sandbox_root, "../cegar_replay_root_evil/pwn.py"
    )
    assert ok is False
    assert "SecurityError" in err_msg

    runner = IsolatedTestRunner(timeout_seconds=2.0)
    res = runner.run_test_code(
        files={"../cegar_replay_evil/pwn.py": "pwn = True\n"},
        test_code="def test_ok():\n    assert True\n",
    )
    assert not res.passed
    assert res.exit_code == -2
    assert "SecurityError" in res.failure_predicate


def test_replay_blocks_overwriting_reserved_runner_and_git_dir() -> None:
    runner = IsolatedTestRunner(timeout_seconds=2.0)
    for reserved in ["_cegar_runner.py", "sub/_cegar_runner.py", ".git/hooks/pre-commit", ".git/config"]:
        res = runner.run_test_code(
            files={reserved: "import sys; sys.exit(0)\n"},
            test_code="def test_fail():\n    assert False\n",
        )
        assert not res.passed
        assert res.exit_code == -2
        assert res.execution_error is True
        assert "SecurityError" in res.failure_predicate


def test_git_workspace_blocks_cwe22_sibling_and_absolute_paths(tmp_path: Path) -> None:
    repo_dir = tmp_path / "repo"
    sibling_dir = tmp_path / "repo_evil"
    _init_git_repo(repo_dir)
    sibling_dir.mkdir(parents=True, exist_ok=True)

    ledger = CounterexampleLedger(":memory:")
    adapter = GitWorkspaceAdapter(repo_path=repo_dir, ledger=ledger)

    for unsafe_path in ["../repo_evil/pwn.py", "../../etc/passwd", "/etc/passwd", ""]:
        with pytest.raises(ValueError):
            adapter.apply_candidate_files(
                task_id="T01",
                candidate_files={unsafe_path: "pwned = True\n"},
            )
    assert not (sibling_dir / "pwn.py").exists()
    ledger.close()


def test_git_workspace_blocks_dot_git_hooks_and_config_writes(tmp_path: Path) -> None:
    repo_dir = tmp_path / "repo"
    _init_git_repo(repo_dir)
    ledger = CounterexampleLedger(":memory:")
    adapter = GitWorkspaceAdapter(repo_path=repo_dir, ledger=ledger)

    for git_target in [".git/hooks/pre-commit", ".git/config", "sub/../.git/HEAD"]:
        with pytest.raises(ValueError, match=r"\.git|traversal"):
            adapter.apply_candidate_files(
                task_id="T01",
                candidate_files={git_target: "#!/bin/sh\nexit 1\n"},
            )
    assert not (repo_dir / ".git" / "hooks" / "pre-commit").exists()
    ledger.close()


def test_git_workspace_blocks_malicious_unified_diff_headers(tmp_path: Path) -> None:
    repo_dir = tmp_path / "repo"
    _init_git_repo(repo_dir)
    ledger = CounterexampleLedger(":memory:")
    adapter = GitWorkspaceAdapter(repo_path=repo_dir, ledger=ledger)

    malicious_git_diff = (
        "--- /dev/null\n"
        "+++ b/.git/hooks/pre-commit\n"
        "@@ -0,0 +1,2 @@\n"
        "+#!/bin/sh\n"
        "+echo pwned\n"
    )
    with pytest.raises(ValueError, match=r"\.git"):
        adapter.apply_unified_diff(
            task_id="T01",
            unified_diff=malicious_git_diff,
            tracked_files=["app.py"],
        )

    malicious_traversal_diff = (
        "--- a/../../etc/passwd\n"
        "+++ b/../../etc/passwd\n"
        "@@ -1 +1 @@\n"
        "-root:x:0:0\n"
        "+pwn:x:0:0\n"
    )
    with pytest.raises(ValueError, match="traversal"):
        adapter.apply_unified_diff(
            task_id="T01",
            unified_diff=malicious_traversal_diff,
            tracked_files=["app.py"],
        )
    ledger.close()


def test_replay_infinite_loop_timeout_kills_process_group(tmp_path: Path) -> None:
    pid_file = tmp_path / "spawned_child.pid"
    runner = IsolatedTestRunner(timeout_seconds=0.35)
    test_code = (
        "import subprocess, sys, time\n"
        "def test_hang():\n"
        "    p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
        f"    open({str(pid_file)!r}, 'w').write(str(p.pid))\n"
        "    while True:\n"
        "        time.sleep(0.05)\n"
    )
    res = runner.run_test_code(files={"mod.py": "x = 1\n"}, test_code=test_code)
    assert res.passed is False
    assert res.timed_out is True
    assert res.exit_code == -1
    assert "TimeoutExpired" in res.failure_predicate

    if pid_file.exists():
        child_pid = int(pid_file.read_text(encoding="utf-8").strip())
        with pytest.raises(ProcessLookupError):
            os.kill(child_pid, 0)


def test_ui_server_rejects_oversized_payload_with_http_413(tmp_path: Path) -> None:
    results_dir = tmp_path / "results"
    sh_src = Path(__file__).resolve().parent.parent / "results"
    if (sh_src / "benchmark_report.json").exists() and (sh_src / "counterexamples.sqlite").exists():
        results_dir.mkdir(parents=True, exist_ok=True)
        (results_dir / "benchmark_report.json").write_bytes((sh_src / "benchmark_report.json").read_bytes())
        (results_dir / "counterexamples.sqlite").write_bytes((sh_src / "counterexamples.sqlite").read_bytes())

    server = create_ui_server(host="127.0.0.1", port=0, results_dir=results_dir)
    port = server.server_address[1]
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    try:
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5.0)
        conn.putrequest("POST", "/api/evaluate")
        conn.putheader("Content-Type", "application/json")
        conn.putheader("Content-Length", str(MAX_POST_BODY_BYTES + 1024))
        conn.endheaders()
        resp = conn.getresponse()
        body = json.loads(resp.read().decode("utf-8"))
        assert resp.status == 413
        assert "Payload Too Large" in body["error"]
        conn.close()
    finally:
        server.shutdown()
        server.server_close()


def test_ui_server_rejects_invalid_content_length_and_malformed_json_with_http_400(tmp_path: Path) -> None:
    results_dir = tmp_path / "results"
    sh_src = Path(__file__).resolve().parent.parent / "results"
    if (sh_src / "benchmark_report.json").exists() and (sh_src / "counterexamples.sqlite").exists():
        results_dir.mkdir(parents=True, exist_ok=True)
        (results_dir / "benchmark_report.json").write_bytes((sh_src / "benchmark_report.json").read_bytes())
        (results_dir / "counterexamples.sqlite").write_bytes((sh_src / "counterexamples.sqlite").read_bytes())

    server = create_ui_server(host="127.0.0.1", port=0, results_dir=results_dir)
    port = server.server_address[1]
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    try:
        # 1. Negative Content-Length
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5.0)
        conn.putrequest("POST", "/api/evaluate")
        conn.putheader("Content-Type", "application/json")
        conn.putheader("Content-Length", "-10")
        conn.endheaders()
        resp = conn.getresponse()
        assert resp.status == 400
        conn.close()

        # 2. Malformed JSON body
        conn2 = http.client.HTTPConnection("127.0.0.1", port, timeout=5.0)
        bad_body = b"{not valid json"
        conn2.request(
            "POST",
            "/api/evaluate",
            body=bad_body,
            headers={"Content-Type": "application/json", "Content-Length": str(len(bad_body))},
        )
        resp2 = conn2.getresponse()
        assert resp2.status == 400
        conn2.close()
    finally:
        server.shutdown()
        server.server_close()


def test_ui_server_sets_strict_security_headers_and_escapes_html(tmp_path: Path) -> None:
    results_dir = tmp_path / "results"
    sh_src = Path(__file__).resolve().parent.parent / "results"
    if (sh_src / "benchmark_report.json").exists() and (sh_src / "counterexamples.sqlite").exists():
        results_dir.mkdir(parents=True, exist_ok=True)
        (results_dir / "benchmark_report.json").write_bytes((sh_src / "benchmark_report.json").read_bytes())
        (results_dir / "counterexamples.sqlite").write_bytes((sh_src / "counterexamples.sqlite").read_bytes())

    server = create_ui_server(host="127.0.0.1", port=0, results_dir=results_dir)
    port = server.server_address[1]
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    try:
        for endpoint in ["/", "/api/overview"]:
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5.0)
            conn.request("GET", endpoint)
            resp = conn.getresponse()
            body_text = resp.read().decode("utf-8")
            headers = {k.lower(): v for k, v in resp.getheaders()}
            assert resp.status == 200
            assert headers.get("x-content-type-options") == "nosniff"
            assert headers.get("x-frame-options") == "DENY"
            assert headers.get("referrer-policy") == "no-referrer"
            assert "default-src 'self'" in headers.get("content-security-policy", "")
            if endpoint == "/":
                assert "function escapeHtml(str)" in body_text
            conn.close()
    finally:
        server.shutdown()
        server.server_close()


def test_ledger_sql_injection_resilience() -> None:
    ledger = CounterexampleLedger(":memory:")
    sqli = "' OR '1'='1'; DROP TABLE counterexamples; --"
    normal_ce = CounterexampleRecord(
        ce_id="CE-SAFE-01",
        task_id="T01",
        target_file="a.py",
        target_symbol="fn",
        contract_version="v1",
        ast_hash="abc12345",
        witness_name="test_w",
        witness_test_code="def test_w(): assert False",
        failure_predicate="ASSERTION_FAILED",
        discovered_at_step=1,
    )
    sqli_ce = CounterexampleRecord(
        ce_id=sqli,
        task_id=sqli,
        target_file="b.py",
        target_symbol="fn",
        contract_version="v1",
        ast_hash=sqli,
        witness_name="test_sqli",
        witness_test_code="def test_sqli(): assert False",
        failure_predicate=sqli,
        discovered_at_step=2,
    )
    ledger.record(normal_ce)
    ledger.record(sqli_ce)

    # Querying with SQLi payload must NOT return T01's record or drop the table
    rows = ledger.get_by_task(sqli)
    assert len(rows) == 1
    assert rows[0].ce_id == sqli

    t01_rows = ledger.get_by_task("T01")
    assert len(t01_rows) == 1
    assert t01_rows[0].ce_id == "CE-SAFE-01"
    assert ledger.count() == 2
    ledger.close()


def test_ledger_status_validation_rejects_invalid_statuses() -> None:
    ledger = CounterexampleLedger(":memory:")
    ce = CounterexampleRecord(
        ce_id="CE-01",
        task_id="T01",
        target_file="a.py",
        target_symbol="fn",
        contract_version="v1",
        ast_hash="h1",
        witness_name="test_w",
        witness_test_code="def test_w(): assert False",
        failure_predicate="FAIL",
        discovered_at_step=1,
    )
    ledger.record(ce)

    for bad_status in ["PWNED", "DELETED", "ACTIVE'; DROP TABLE counterexamples; --", ""]:
        with pytest.raises(ValueError, match="Invalid counterexample status"):
            ledger.mark_status("CE-01", bad_status)

    ledger.mark_status("CE-01", "RESOLVED")
    assert ledger.get_by_task("T01", include_resolved=False) == []
    ledger.close()


def test_ledger_concurrent_multithreaded_read_write_safety(tmp_path: Path) -> None:
    db_file = tmp_path / "concurrent_ledger.sqlite"
    ledger = CounterexampleLedger(db_file)
    errors: list[Exception] = []

    def worker(tid: int) -> None:
        try:
            for i in range(20):
                ce = CounterexampleRecord(
                    ce_id=f"CE-T{tid}-{i}",
                    task_id=f"TASK-{tid % 3}",
                    target_file="mod.py",
                    target_symbol="fn",
                    contract_version="v1",
                    ast_hash=f"hash_{tid}_{i}",
                    witness_name="test_conc",
                    witness_test_code="def test_conc(): assert True",
                    failure_predicate="FAIL",
                    discovered_at_step=i,
                )
                ledger.record(ce)
                _ = ledger.get_by_task(f"TASK-{tid % 3}")
                _ = ledger.find_by_ast_hash(f"TASK-{tid % 3}", f"hash_{tid}_{i}")
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(t,)) for t in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []
    assert ledger.count() == 160
    ledger.close()


def test_mcp_server_handles_non_dict_and_malformed_jsonrpc_inputs() -> None:
    server = CEGARMCPServer(db_path=":memory:")
    try:
        for invalid_payload in [[], 42, "string_payload", None, {"jsonrpc": "1.0", "method": "ping"}]:
            resp = server.handle_request(invalid_payload)
            assert resp is not None
            assert resp["error"]["code"] == -32600

        unknown_resp = server.handle_request({"jsonrpc": "2.0", "id": 9, "method": "unknown/method"})
        assert unknown_resp is not None
        assert unknown_resp["error"]["code"] == -32601

        bad_params_resp = server.handle_request(
            {"jsonrpc": "2.0", "id": 10, "method": "tools/call", "params": ["not_a_dict"]}
        )
        assert bad_params_resp is not None
        assert bad_params_resp["error"]["code"] == -32602

        in_buf = io.StringIO("{truncated json\n[]\n")
        out_buf = io.StringIO()
        server.serve_stdio(in_stream=in_buf, out_stream=out_buf)
        responses = [json.loads(line) for line in out_buf.getvalue().splitlines() if line.strip()]
        assert len(responses) == 2
        assert responses[0]["error"]["code"] == -32700
        assert responses[1]["error"]["code"] == -32600
    finally:
        server.close()


def test_mcp_server_blocks_unsafe_file_paths_and_oversized_stdio_lines() -> None:
    server = CEGARMCPServer(db_path=":memory:")
    try:
        for bad_file in ["../../etc/passwd", ".git/config", "_cegar_runner.py", "/etc/hosts"]:
            resp = server.handle_request(
                {
                    "jsonrpc": "2.0",
                    "id": 11,
                    "method": "tools/call",
                    "params": {
                        "name": "cegar_evaluate_patch",
                        "arguments": {
                            "task_id": "T01",
                            "files": {bad_file: "x = 1\n"},
                        },
                    },
                }
            )
            assert resp is not None
            assert "error" in resp
            assert resp["error"]["code"] == -32602

        oversized_line = '{"jsonrpc":"2.0","id":1,"method":"ping","padding":"' + ("A" * (server.MAX_LINE_BYTES + 100)) + '"}\n'
        in_buf = io.StringIO(oversized_line)
        out_buf = io.StringIO()
        server.serve_stdio(in_stream=in_buf, out_stream=out_buf)
        resp_line = json.loads(out_buf.getvalue().strip())
        assert resp_line["error"]["code"] == -32600
    finally:
        server.close()


def test_llm_client_blocks_disallowed_url_schemes_ssrf_lfi() -> None:
    for unsafe_url in [
        "file:///etc/passwd",
        "ftp://internal.corp/v1",
        "gopher://127.0.0.1:70",
        "javascript:alert(1)",
        "http://",
    ]:
        with pytest.raises(ValueError, match="scheme must be 'http' or 'https'"):
            LiveLLMClient(api_base=unsafe_url, model_name="llama3:latest")

    valid_client = LiveLLMClient(api_base="http://127.0.0.1:11434/v1", model_name="llama3:latest")
    assert valid_client.is_configured is True
