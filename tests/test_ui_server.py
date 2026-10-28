"""Integration tests for the CEGAR Trajectory & Compaction Inspector Web UI (`cegar-harness ui`)."""

from __future__ import annotations

import json
import threading
import urllib.request
from pathlib import Path

from cegar_harness.ui_server import create_ui_server


def test_inspector_ui_server_endpoints_end_to_end() -> None:
    server = create_ui_server(host="127.0.0.1", port=0, results_dir="results")
    host, port = server.server_address
    base_url = f"http://{host}:{port}"

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        # 1. GET / serves the HTML dashboard
        with urllib.request.urlopen(f"{base_url}/", timeout=5) as resp:
            html = resp.read().decode("utf-8")
            assert resp.status == 200
            assert "CEGAR-Harness" in html
            assert "Side-by-Side Compaction Diff Viewer" in html

        # 2. GET /api/overview returns all 30 tasks and benchmark report
        with urllib.request.urlopen(f"{base_url}/api/overview", timeout=5) as resp:
            overview = json.loads(resp.read().decode("utf-8"))
            assert len(overview["tasks"]) == 30
            assert overview["report"]["experiment_a_controlled_replay"]["total_tasks"] == 30

        # 3. GET /api/compaction?task_id=T26 returns all 5 compaction strategies
        with urllib.request.urlopen(f"{base_url}/api/compaction?task_id=T26", timeout=5) as resp:
            comp = json.loads(resp.read().decode("utf-8"))
            assert comp["task_id"] == "T26"
            assert comp["compactions"]["CEGAR_HARNESS_FULL"]["witness_predicate_retained"] is True
            assert comp["compactions"]["LOSSY_SUMMARY"]["witness_predicate_retained"] is False

        # 4. POST /api/evaluate executes live AST filter + Witness Replay in sandbox
        eval_payload = {
            "task_id": "T26",
            "contract_version": "v1",
            "files": {
                "filters.py": (
                    "def compact_ints(items):\n"
                    "    return [x for x in items if x]\n"
                )
            },
        }
        req = urllib.request.Request(
            f"{base_url}/api/evaluate",
            data=json.dumps(eval_payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            eval_res = json.loads(resp.read().decode("utf-8"))
            assert eval_res["gate"]["status"] == "REGRESSION_DETECTED"
            assert eval_res["reference_oracle"]["passed"] is False
    finally:
        server.shutdown()
        server.server_close()
