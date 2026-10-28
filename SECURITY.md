# Security Architecture & Threat Model

**CEGAR-Harness** executes untrusted, LLM-generated candidate code patches and witness assertions inside an isolated verification pipeline and exposes local Model Context Protocol (MCP) and HTTP inspection interfaces. This document describes the security controls implemented across the codebase and continuously verified by the 16 adversarial tests in [`tests/test_security_hardening.py`](tests/test_security_hardening.py).

---

## 1. Threat Model & Mitigations

### 1.1 Sandbox Path Traversal & Sibling-Prefix Bypass (CWE-22)
- **Threat:** An adversarial or hallucinated LLM patch dictionary (`files`) or unified `git diff` attempts to write outside the sandbox or repository root using `../` sequences, absolute paths (`/etc/passwd`), or sibling-prefix directories (`/tmp/cegar_replay_root_evil/pwn.py`) that bypass naive `str.startswith()` checks.
- **Mitigation:**
  - `IsolatedTestRunner._validate_sandbox_path` (`cegar_harness/replay.py`) and `GitWorkspaceAdapter._validate_safe_repo_path` (`cegar_harness/git_workspace.py`) enforce strict containment via `Path.resolve().is_relative_to(root_resolved)`.
  - Empty paths, null bytes (`\x00`), absolute paths, `..` components, `.git/` targets, and overwrites of the reserved harness entrypoint (`_cegar_runner.py`) are rejected before any file is written to disk.

### 1.2 Git Hook & Configuration Injection (`GitWorkspaceAdapter`)
- **Threat:** A candidate patch or unified diff targets `.git/hooks/pre-commit` or `.git/config` to achieve arbitrary command execution on subsequent Git operations.
- **Mitigation:**
  - `GitWorkspaceAdapter` explicitly forbids any path containing a `.git` component in both `apply_candidate_files` and `apply_unified_diff`.
  - Before invoking `git apply`, `_validate_unified_diff_headers` inspects all `--- a/...`, `+++ b/...`, and `diff --git` lines and rejects any diff referencing `.git/` or paths outside the repository root.

### 1.3 Runaway Subprocess & Zombie Process Groups (CWE-400)
- **Threat:** A candidate patch introduces an infinite loop (`while True: pass`) or spawns background child processes that outlive the test timeout.
- **Mitigation:**
  - `IsolatedTestRunner.run_test_code` launches the child Python interpreter with `start_new_session=True`, placing it in an dedicated POSIX process group.
  - On `subprocess.TimeoutExpired`, the runner terminates the entire process group via `os.killpg(os.getpgid(proc.pid), signal.SIGKILL)` and reaps the process descriptor.

### 1.4 HTTP Dashboard DoS, Malformed Headers & DOM XSS (`cegar_harness/ui_server.py`)
- **Threat:** Oversized `POST /api/evaluate` bodies exhaust server memory, negative/invalid `Content-Length` values cause handler exceptions, or crafted failure predicates trigger DOM-based Cross-Site Scripting (XSS) in the Web Inspector UI.
- **Mitigation:**
  - `MAX_POST_BODY_BYTES = 1_048_576` (1 MiB): payloads exceeding this threshold are immediately rejected with **HTTP `413 Payload Too Large`** before reading the request stream; missing, non-integer, or non-positive `Content-Length` headers return **HTTP `400 Bad Request`**.
  - Every HTTP response includes `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, and `Content-Security-Policy: default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; img-src 'self' data:;`.
  - All dynamic strings rendered into the dashboard DOM pass through `escapeHtml(str)`.

### 1.5 MCP JSON-RPC 2.0 Input Bounds & Schema Validation (`cegar_harness/mcp_server.py`)
- **Threat:** Malformed JSON, non-object JSON payloads (`[]`, `42`, `"str"`, `null`), oversized stdio lines, or unsafe file paths in `cegar_evaluate_patch` / `cegar_record_witness` crash or compromise the MCP server.
- **Mitigation:**
  - `serve_stdio` enforces `MAX_LINE_BYTES = 2_097_152` (2 MiB) per JSON-RPC line.
  - `handle_request` validates that every request is a `dict` with `jsonrpc == "2.0"` and a non-empty string `method`, returning standard JSON-RPC error codes (`-32700` Parse error, `-32600` Invalid Request, `-32601` Method not found, `-32602` Invalid params).
  - `_validate_safe_files_map` validates all file paths passed to MCP tools prior to gate evaluation or witness recording.

### 1.6 SQLite Concurrency, Parameterized Queries & SSRF/LFI Prevention
- **SQLite Ledger (`cegar_harness/ledger.py`):** All SQL statements use parameterized `?` bindings (preventing SQL injection), lifecycle statuses are restricted to `{"ACTIVE", "RESOLVED", "OBSOLETE"}`, and connections enable `PRAGMA journal_mode = WAL;`, `PRAGMA busy_timeout = 5000;`, `PRAGMA foreign_keys = ON;`, and a re-entrant thread lock (`threading.RLock()`).
- **LLM Client (`cegar_harness/llm_provider.py`):** `LiveLLMClient._validate_api_base_url` parses `api_base` via `urllib.parse.urlparse` and strictly permits only `http` and `https` schemes with a valid host, blocking `file://`, `ftp://`, `gopher://`, and other local-file or SSRF vectors.

---

## 2. Running the Security Test Suite

```bash
pytest tests/test_security_hardening.py -v
```

## 3. Reporting a Vulnerability

If you discover a security issue in `cegar-harness`, please report it privately via email to `iyed.mohamed@esprit.tn` or by opening a security advisory on GitHub at `https://github.com/iyedM/cegar-harness/security`.
