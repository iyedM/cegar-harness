"""Tests for the 6-repository Multi-File Git Workspace Benchmark (`cegar-harness repo-eval`)."""

from __future__ import annotations

import json
from pathlib import Path

from cegar_harness.cli import main as cli_main
from cegar_harness.real_repo_bench import get_multi_file_repo_specs, run_multi_file_repo_benchmark


def test_multi_file_repo_specs_and_atomic_git_rollback(tmp_path: Path) -> None:
    specs = get_multi_file_repo_specs()
    assert len(specs) == 6

    out_dir = tmp_path / "repo_eval_out"
    rc = cli_main(["repo-eval", "--output-dir", str(out_dir)])
    assert rc == 0

    report_path = out_dir / "real_repo_eval.json"
    assert report_path.exists()

    summary = json.loads(report_path.read_text(encoding="utf-8"))
    assert summary["repositories_evaluated"] == 6
    assert summary["regressions_intercepted"] == 6
    assert summary["atomic_rollbacks_verified"] == 6
    assert summary["atomic_rollback_rate_pct"] == 100.0
    assert summary["valid_patches_resolved"] == 6
    assert summary["resolution_rate_pct"] == 100.0

    for repo_res in summary["repositories"]:
        assert repo_res["files_count"] >= 5
        assert len(repo_res["initial_commit_sha"]) >= 7
        assert repo_res["regression_gate_status"] == "REGRESSION_DETECTED"
        assert repo_res["atomic_rollback_verified"] is True
        assert repo_res["git_status_clean_after_rollback"] is True
        assert repo_res["files_identical_after_rollback"] is True
        assert repo_res["valid_patch_gate_status"] == "PASS"
        assert repo_res["valid_patch_applied"] is True
        assert repo_res["full_test_suite_passed"] is True
        assert repo_res["diff_lines_changed"] >= 1


def test_direct_run_multi_file_repo_benchmark_returns_summary(tmp_path: Path) -> None:
    res = run_multi_file_repo_benchmark(output_dir=tmp_path)
    assert res["repositories_evaluated"] == 6
    assert res["atomic_rollback_rate_pct"] == 100.0
