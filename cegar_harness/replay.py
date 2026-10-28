"""Isolated and reproducible Witness Replay and Oracle Test Runner."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Dict


@dataclass
class ExecutionResult:
    """Result of executing a witness or reference test suite in an isolated workspace."""

    passed: bool
    exit_code: int
    failure_predicate: str
    stdout: str
    stderr: str
    duration_ms: float
    timed_out: bool = False
    execution_error: bool = False


class IsolatedTestRunner:
    """Runs Python witness assertions or reference tests in an isolated temporary directory."""

    RESERVED_RUNNER_NAME = "_cegar_runner.py"

    def __init__(self, timeout_seconds: float = 5.0) -> None:
        self.timeout_seconds = timeout_seconds

    @classmethod
    def _validate_sandbox_path(cls, root_resolved: Path, rel_path: str) -> tuple[bool, str, Path]:
        """Validates that `rel_path` is strictly confined inside `root_resolved` and does not touch reserved paths."""
        if not isinstance(rel_path, str) or not rel_path.strip() or "\x00" in rel_path:
            return False, "SecurityError: Empty or invalid file path", root_resolved

        raw_path = Path(rel_path)
        posix_parts = PurePosixPath(rel_path.replace("\\", "/")).parts
        if raw_path.is_absolute() or rel_path.startswith(("/", "\\")):
            return False, f"SecurityError: Absolute path rejected ({rel_path})", root_resolved
        if ".." in raw_path.parts or ".." in posix_parts:
            return False, f"SecurityError: Path traversal outside sandbox ({rel_path})", root_resolved
        if ".git" in raw_path.parts or ".git" in posix_parts:
            return False, f"SecurityError: Access to .git directory rejected ({rel_path})", root_resolved

        target = (root_resolved / raw_path).resolve()
        if not target.is_relative_to(root_resolved) or target == root_resolved:
            return False, f"SecurityError: Path traversal outside sandbox ({rel_path})", root_resolved
        if target.name == cls.RESERVED_RUNNER_NAME:
            return False, f"SecurityError: Overwriting reserved runner file {cls.RESERVED_RUNNER_NAME} rejected", root_resolved

        return True, "", target

    def run_test_code(self, files: Dict[str, str], test_code: str) -> ExecutionResult:
        """Writes `files` and `test_code` to an isolated temp dir and executes the test."""
        start_ns = time.perf_counter_ns()
        with tempfile.TemporaryDirectory(prefix="cegar_replay_") as tmp_dir:
            root = Path(tmp_dir).resolve()
            for rel_path, content in files.items():
                ok, err_msg, target = self._validate_sandbox_path(root, rel_path)
                if not ok:
                    return ExecutionResult(
                        passed=False,
                        exit_code=-2,
                        failure_predicate=err_msg,
                        stdout="",
                        stderr=err_msg,
                        duration_ms=(time.perf_counter_ns() - start_ns) / 1e6,
                        execution_error=True,
                    )
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding="utf-8")

            runner_file = root / self.RESERVED_RUNNER_NAME
            runner_script = (
                "import os, sys, traceback\n"
                "sys.path.insert(0, os.getcwd())\n"
                f"{test_code}\n\n"
                "if __name__ == '__main__':\n"
                "    funcs = [v for k, v in list(globals().items()) if k.startswith('test_') and callable(v)]\n"
                "    if not funcs:\n"
                "        print('NO_TESTS_FOUND', file=sys.stderr)\n"
                "        sys.exit(3)\n"
                "    for fn in funcs:\n"
                "        try:\n"
                "            fn()\n"
                "        except AssertionError as e:\n"
                "            tb = traceback.extract_tb(sys.exc_info()[2])\n"
                "            last = tb[-1] if tb else None\n"
                "            line_info = f'{last.name}:{last.lineno}: {last.line}' if last else ''\n"
                "            msg = str(e) if str(e) else line_info\n"
                "            print(f'ASSERTION_FAILED: {fn.__name__}: {msg}', file=sys.stderr)\n"
                "            sys.exit(1)\n"
                "        except Exception as e:\n"
                "            print(f'EXCEPTION_RAISED: {fn.__name__}: {type(e).__name__}: {e}', file=sys.stderr)\n"
                "            sys.exit(2)\n"
                "    print('ALL_PASSED')\n"
                "    sys.exit(0)\n"
            )
            runner_file.write_text(runner_script, encoding="utf-8")

            env = {
                "PATH": os.environ.get("PATH", ""),
                "PYTHONPATH": str(root),
                "PYTHONDONTWRITEBYTECODE": "1",
            }
            proc = subprocess.Popen(
                [sys.executable, "-B", str(runner_file)],
                cwd=str(root),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                start_new_session=True,
            )
            try:
                stdout_str, stderr_str = proc.communicate(timeout=self.timeout_seconds)
                duration_ms = (time.perf_counter_ns() - start_ns) / 1e6
                returncode = proc.returncode if proc.returncode is not None else -1
                passed = returncode == 0
                predicate = self._extract_predicate(stderr_str, stdout_str, passed)
                return ExecutionResult(
                    passed=passed,
                    exit_code=returncode,
                    failure_predicate=predicate,
                    stdout=stdout_str,
                    stderr=stderr_str,
                    duration_ms=duration_ms,
                    timed_out=False,
                    execution_error=(returncode not in (0, 1, 2)),
                )
            except subprocess.TimeoutExpired as exc:
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                except (ProcessLookupError, PermissionError, OSError):
                    proc.kill()
                try:
                    proc.communicate(timeout=1.0)
                except Exception:
                    pass
                duration_ms = (time.perf_counter_ns() - start_ns) / 1e6
                return ExecutionResult(
                    passed=False,
                    exit_code=-1,
                    failure_predicate=f"TimeoutExpired after {self.timeout_seconds}s",
                    stdout=exc.stdout or "" if isinstance(exc.stdout, str) else "",
                    stderr=exc.stderr or "" if isinstance(exc.stderr, str) else "",
                    duration_ms=duration_ms,
                    timed_out=True,
                    execution_error=True,
                )

    @staticmethod
    def _extract_predicate(stderr: str, stdout: str, passed: bool) -> str:
        if passed:
            return "PASS"
        for line in stderr.splitlines():
            line_s = line.strip()
            if line_s.startswith(("ASSERTION_FAILED:", "EXCEPTION_RAISED:", "SyntaxError:", "IndentationError:")):
                return line_s
        lines = [ln.strip() for ln in stderr.splitlines() if ln.strip()]
        if lines:
            return lines[-1]
        out_lines = [ln.strip() for ln in stdout.splitlines() if ln.strip()]
        return out_lines[-1] if out_lines else "Unknown test failure"
