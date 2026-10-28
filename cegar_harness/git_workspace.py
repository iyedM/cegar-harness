"""Git Workspace Adapter with pre-commit RegressionGate verification and atomic rollback."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from cegar_harness.gate import RegressionGate
from cegar_harness.ledger import CounterexampleLedger
from cegar_harness.models import GateEvaluationResult, GateStatus
from cegar_harness.replay import IsolatedTestRunner


@dataclass
class GitPatchApplicationResult:
    """Outcome of attempting to apply a patch or unified diff to a Git repository."""

    applied: bool
    rolled_back: bool
    gate_result: GateEvaluationResult
    modified_files: List[str]
    git_diff: str

    @property
    def decision(self) -> GateEvaluationResult:
        return self.gate_result


class GitWorkspaceAdapter:
    """Applies candidate file patches or unified diffs to a local Git repository with atomic rollback on regression."""

    def __init__(
        self,
        repo_path: str | Path,
        gate: Optional[RegressionGate] = None,
        ledger: Optional[CounterexampleLedger] = None,
        runner: Optional[IsolatedTestRunner] = None,
    ) -> None:
        self.repo_path = Path(repo_path).resolve()
        if not (self.repo_path / ".git").exists():
            raise ValueError(f"Not a valid Git repository: {self.repo_path}")
        if gate is not None:
            self.gate = gate
        elif ledger is not None:
            self.gate = RegressionGate(ledger=ledger, runner=runner or IsolatedTestRunner())
        else:
            raise ValueError("GitWorkspaceAdapter requires either `gate` or `ledger`.")

    def _validate_safe_repo_path(self, rel_path: str) -> Path:
        """Validates that `rel_path` is strictly inside `self.repo_path` and never touches `.git/`."""
        if not isinstance(rel_path, str) or not rel_path.strip() or "\x00" in rel_path:
            raise ValueError(f"Invalid or empty repository path rejected: {rel_path!r}")

        cleaned = rel_path.strip()
        raw_path = Path(cleaned)
        norm_parts = Path(cleaned.replace("\\", "/")).parts
        if raw_path.is_absolute() or cleaned.startswith(("/", "\\")):
            raise ValueError(f"Absolute path outside repository rejected: {rel_path}")
        if ".." in raw_path.parts or ".." in norm_parts:
            raise ValueError(f"Path traversal outside repository rejected: {rel_path}")
        if ".git" in raw_path.parts or ".git" in norm_parts:
            raise ValueError(f"Modification of .git directory rejected: {rel_path}")

        target = (self.repo_path / raw_path).resolve()
        if not target.is_relative_to(self.repo_path) or target == self.repo_path:
            raise ValueError(f"Path traversal outside repository rejected: {rel_path}")

        rel_to_repo = target.relative_to(self.repo_path)
        if ".git" in rel_to_repo.parts:
            raise ValueError(f"Modification of .git directory rejected: {rel_path}")

        return target

    def _validate_unified_diff_headers(self, unified_diff: str) -> None:
        """Inspects `---` / `+++` / `diff --git` headers in `unified_diff` before invoking `git apply`."""
        if not isinstance(unified_diff, str) or not unified_diff.strip():
            raise ValueError("Empty unified diff rejected")

        for line in unified_diff.splitlines():
            if line.startswith(("+++ ", "--- ")):
                raw_target = line[4:].strip().split("\t", 1)[0].strip()
                if raw_target == "/dev/null":
                    continue
                if raw_target.startswith(("a/", "b/")):
                    raw_target = raw_target[2:]
                self._validate_safe_repo_path(raw_target)
            elif line.startswith("diff --git "):
                parts = line[len("diff --git "):].strip().split()
                for part in parts[:2]:
                    cleaned = part[2:] if part.startswith(("a/", "b/")) else part
                    if cleaned != "/dev/null":
                        self._validate_safe_repo_path(cleaned)

    def _collect_repo_python_files(self, overlay_files: Dict[str, str]) -> Dict[str, str]:
        """Collects all non-test Python modules in the repository working tree merged with `overlay_files`."""
        merged: Dict[str, str] = {}
        for py_file in sorted(self.repo_path.rglob("*.py")):
            rel = py_file.relative_to(self.repo_path).as_posix()
            if rel.startswith("tests/") or rel.startswith(".git/"):
                continue
            merged[rel] = py_file.read_text(encoding="utf-8")
        merged.update(overlay_files)
        return merged

    def apply_candidate_files(
        self,
        task_id: str,
        candidate_files: Dict[str, str],
        contract_version: str = "v1",
    ) -> GitPatchApplicationResult:
        """Applies `candidate_files` to the working tree, runs RegressionGate, and rolls back if REGRESSION_DETECTED."""
        validated_targets: List[tuple[str, Path, str]] = []
        for rel_path, new_content in candidate_files.items():
            target = self._validate_safe_repo_path(rel_path)
            validated_targets.append((rel_path, target, new_content))

        snapshots: Dict[str, Optional[str]] = {}
        modified_paths: List[str] = []

        for rel_path, target, new_content in validated_targets:
            if target.exists():
                snapshots[rel_path] = target.read_text(encoding="utf-8")
            else:
                snapshots[rel_path] = None
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(new_content, encoding="utf-8")
            modified_paths.append(rel_path)

        diff_text = self.get_working_diff()
        eval_files = self._collect_repo_python_files(candidate_files)
        gate_res = self.gate.evaluate(
            task_id=task_id,
            candidate_files=eval_files,
            current_contract_version=contract_version,
        )

        if gate_res.status == GateStatus.REGRESSION_DETECTED:
            self._rollback_snapshots(snapshots)
            return GitPatchApplicationResult(
                applied=False,
                rolled_back=True,
                gate_result=gate_res,
                modified_files=modified_paths,
                git_diff=diff_text,
            )

        return GitPatchApplicationResult(
            applied=True,
            rolled_back=False,
            gate_result=gate_res,
            modified_files=modified_paths,
            git_diff=diff_text,
        )

    def apply_candidate_with_gate(
        self,
        task_id: str,
        candidate_files: Dict[str, str],
        contract_version: str = "v1",
    ) -> GitPatchApplicationResult:
        """Alias for `apply_candidate_files`."""
        return self.apply_candidate_files(
            task_id=task_id,
            candidate_files=candidate_files,
            contract_version=contract_version,
        )

    def apply_unified_diff(
        self,
        task_id: str,
        unified_diff: str,
        tracked_files: List[str],
        contract_version: str = "v1",
    ) -> GitPatchApplicationResult:
        """Applies a unified `git diff` patch via `git apply`, evaluates RegressionGate, and rolls back on regression."""
        self._validate_unified_diff_headers(unified_diff)
        snapshots: Dict[str, Optional[str]] = {}
        for rel_path in tracked_files:
            target = self._validate_safe_repo_path(rel_path)
            snapshots[rel_path] = target.read_text(encoding="utf-8") if target.exists() else None

        proc = subprocess.run(
            ["git", "apply", "--whitespace=nowarn", "-"],
            input=unified_diff,
            cwd=str(self.repo_path),
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"git apply failed: {proc.stderr.strip()}")

        candidate_files: Dict[str, str] = {}
        for rel_path in tracked_files:
            target = self._validate_safe_repo_path(rel_path)
            if target.exists():
                candidate_files[rel_path] = target.read_text(encoding="utf-8")

        diff_text = self.get_working_diff()
        eval_files = self._collect_repo_python_files(candidate_files)
        gate_res = self.gate.evaluate(
            task_id=task_id,
            candidate_files=eval_files,
            current_contract_version=contract_version,
        )

        if gate_res.status == GateStatus.REGRESSION_DETECTED:
            self._rollback_snapshots(snapshots)
            return GitPatchApplicationResult(
                applied=False,
                rolled_back=True,
                gate_result=gate_res,
                modified_files=tracked_files,
                git_diff=diff_text,
            )

        return GitPatchApplicationResult(
            applied=True,
            rolled_back=False,
            gate_result=gate_res,
            modified_files=tracked_files,
            git_diff=diff_text,
        )

    def get_working_diff(self) -> str:
        """Returns the current `git diff` of the working tree."""
        proc = subprocess.run(
            ["git", "diff"],
            cwd=str(self.repo_path),
            capture_output=True,
            text=True,
            check=False,
        )
        return proc.stdout

    def _rollback_snapshots(self, snapshots: Dict[str, Optional[str]]) -> None:
        """Atomically restores pre-patch file contents and removes newly created files."""
        for rel_path, original in snapshots.items():
            target = self.repo_path / rel_path
            if original is None:
                if target.exists():
                    target.unlink()
            else:
                target.write_text(original, encoding="utf-8")
        subprocess.run(
            ["git", "checkout", "--", "."],
            cwd=str(self.repo_path),
            capture_output=True,
            text=True,
            check=False,
        )
