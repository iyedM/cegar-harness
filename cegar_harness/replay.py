"""Isolated and reproducible Witness Replay and Oracle Test Runner."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
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

    def __init__(self, timeout_seconds: float = 5.0) -> None:
        self.timeout_seconds = timeout_seconds

    def run_test_code(self, files: Dict[str, str], test_code: str) -> ExecutionResult:
        """Writes `files` and `test_code` to an isolated temp dir and executes the test."""
        start_ns = time.perf_counter_ns()
        with tempfile.TemporaryDirectory(prefix="cegar_replay_") as tmp_dir:
            root = Path(tmp_dir)
            for rel_path, content in files.items():
                target = (root / rel_path).resolve()
                if not str(target).startswith(str(root.resolve())):
                    return ExecutionResult(
                        passed=False,
                        exit_code=-2,
                        failure_predicate="SecurityError: Path traversal outside sandbox",
                        stdout="",
                        stderr="Path traversal detected",
                        duration_ms=(time.perf_counter_ns() - start_ns) / 1e6,
                        execution_error=True,
                    )
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding="utf-8")

            runner_file = root / "_cegar_runner.py"
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
            try:
                proc = subprocess.run(
                    [sys.executable, "-B", str(runner_file)],
                    cwd=str(root),
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=self.timeout_seconds,
                )
                duration_ms = (time.perf_counter_ns() - start_ns) / 1e6
                passed = proc.returncode == 0
                predicate = self._extract_predicate(proc.stderr, proc.stdout, passed)
                return ExecutionResult(
                    passed=passed,
                    exit_code=proc.returncode,
                    failure_predicate=predicate,
                    stdout=proc.stdout,
                    stderr=proc.stderr,
                    duration_ms=duration_ms,
                    timed_out=False,
                    execution_error=(proc.returncode not in (0, 1, 2)),
                )
            except subprocess.TimeoutExpired as exc:
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
