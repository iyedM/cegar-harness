# CEGAR-Harness: Regression-Aware Context Compaction & Witness Replay for Coding Agents

[![CI](https://github.com/iyedM/cegar-harness/actions/workflows/ci.yml/badge.svg)](https://github.com/iyedM/cegar-harness/actions/workflows/ci.yml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Technical Report](https://img.shields.io/badge/PDF-11--Page_Technical_Report-b31b1b.svg)](docs/CEGAR_Harness_Technical_Report_Iyed_MOHAMED.pdf)

**CEGAR-Harness** is an open-source research middleware and empirical evaluation harness for autonomous coding agents (*Claude Code*, *Cursor*, *LangGraph*, *OpenHands*). Inspired by Counterexample-Guided Abstraction Refinement (CEGAR), it mitigates **Post-Compaction Regression Loops (PCRL)**—where a coding agent re-introduces a previously refuted bug after context window compaction strips away earlier failure tracebacks—by:

1. **Recording reproducible failure witnesses** (*counterexamples*) in a persistent, contract-versioned SQLite ledger (`CounterexampleLedger`),
2. **Pinning active counterexample predicates** during context compaction (`CompactionController`),
3. **Gating candidate code patches** through a three-state `RegressionGate` (`PASS`, `REGRESSION_DETECTED`, `INCONCLUSIVE`) backed by an optional syntactic AST canonicalization pre-filter and isolated behavioral **Witness Replay** (`IsolatedTestRunner`), and
4. **Exposing industrial integration adapters** via a standard **Model Context Protocol (MCP)** JSON-RPC 2.0 server (`cegar-harness mcp-serve`), an atomic **Git Workspace Adapter** with automatic rollback (`GitWorkspaceAdapter`), a **LangGraph Middleware** (`CEGARHarnessMiddleware`), and a zero-dependency **Web Inspector UI** (`cegar-harness ui --port 8080`).

> 📄 **Full Paper / Technical Report (11 Pages, IEEE/arXiv format):** [`docs/CEGAR_Harness_Technical_Report_Iyed_MOHAMED.pdf`](docs/CEGAR_Harness_Technical_Report_Iyed_MOHAMED.pdf)

---

## 1. Problem Statement & Motivating Example

Long-horizon coding sessions rapidly accumulate verbose tool outputs (pytest stack traces, file dumps, static analysis logs). When the context approaches a token threshold, agent harnesses trigger **Context Compaction** (via observation masking or narrative LLM summarization). Because standard compaction is lossy with respect to exact falsifying inputs and assertion predicates, the agent frequently suffers from **post-compaction amnesia** and re-proposes a broken patch—or a syntactically distinct rewrite of the same logical defect—that was already refuted earlier in the session.

| Step | Standard Compaction (`OBSERVATION_MASKING` / `LOSSY_SUMMARY`) | `CEGAR-Harness` (`CEGAR_HARNESS_FULL`) |
| :--- | :--- | :--- |
| **Step 1–2 (Pre-Compaction)** | Agent proposes patch `p1` (`if item:` filter that accidentally drops valid `0` integers). Witness test `test_zero_is_not_dropped` fails (`AssertionError: [1, 2] != [0, 1, 2]`). | Same failure occurs. `CEGAR-Harness` extracts and records `CE-T26-01` (`contract_version="v1"`, `ast_hash`, `witness_test_code`, `failure_predicate`) in SQLite. |
| **Step 3–6 (Exploration)** | Agent inspects call sites and control flow (+450 tokens of tool observations). | Same exploration turns. |
| **Compaction Boundary** | Old tool outputs are masked or summarized into *"The agent encountered 1 test failure."* **Exact falsifying witness (`0` dropped) is lost.** | Verbose observations are pruned (**48.26% token compression**), while `CE-T26-01` predicate and AST fingerprint remain pinned in the compacted header. |
| **Post-Compaction Continuation** | Agent re-proposes `p1` (or a list-comprehension variant `[x for x in items if x]`), causing an **unblocked post-compaction regression** that wastes Oracle Turn 1. | If the agent proposes a syntactic variant `[x for x in items if x]`, `RegressionGate` replays `test_zero_is_not_dropped` in an isolated sandbox (`~19 ms`), returns `REGRESSION_DETECTED`, blocks the regression before full suite execution, and converges on `if x is not None`. |

---

## 2. System Architecture & Three-State Regression Gate

```text
cegar-harness/
├── pyproject.toml
├── Dockerfile
├── .github/workflows/ci.yml
├── docs/
│   └── CEGAR_Harness_Technical_Report_Iyed_MOHAMED.pdf  # 11-page IEEE/arXiv Technical Report
├── scripts/
│   ├── run_benchmark.sh               # Reproducible end-to-end test + benchmark pipeline
│   └── generate_technical_report.py   # Generates the 11-page PDF report from live JSON metrics
├── cegar_harness/
│   ├── __init__.py
│   ├── models.py                      # Schemas: GateStatus, CompactionStrategy, BugCategory, CounterexampleRecord
│   ├── ast_filter.py                  # Optional AST canonicalization pre-filter (_AlphaNormalizer)
│   ├── ledger.py                      # SQLite-backed Versioned Counterexample Ledger
│   ├── replay.py                      # IsolatedTestRunner: sandboxed subprocess execution & path confinement
│   ├── gate.py                        # 3-state RegressionGate (PASS, REGRESSION_DETECTED, INCONCLUSIVE)
│   ├── compactor.py                   # CompactionController implementing 5 context compaction strategies
│   ├── git_workspace.py               # GitWorkspaceAdapter: applies patches/diffs with atomic rollback on regression
│   ├── mcp_server.py                  # Standard MCP JSON-RPC 2.0 server over stdio (4 tools for Claude Code / Cursor)
│   ├── langgraph_adapter.py           # CEGARHarnessMiddleware & AgentGraphState for LangGraph workflows
│   ├── ui_server.py                   # Interactive Web Dashboard (`cegar-harness ui --port 8080`)
│   ├── telemetry.py                   # OpenTelemetry spans (`cegar.gate.evaluate`, `cegar.compaction.run`) + JSONL
│   ├── llm_provider.py                # LiveLLMClient for multi-turn Experiment B self-repair loop
│   ├── tasks.py                       # 30 deterministic Python code-repair tasks across 6 categories
│   ├── benchmark.py                   # Multi-turn Experiment A, 4-Way Ablation, Wilson CIs & Experiment B runner
│   └── cli.py                         # CLI: `bench`, `live-eval`, `inspect-ledger`, `mcp-serve`, `ui`
└── tests/
    ├── test_ast_filter.py
    ├── test_compactor.py
    ├── test_gate_and_replay.py
    ├── test_benchmark_integrity.py
    ├── test_mcp_and_git.py
    └── test_ui_server.py
```

### Three-State `RegressionGate` Semantics

A naive gatekeeper that blocks every patch failing a historical test will reject legitimate solutions whenever the task specification evolves (e.g., `v1` $\rightarrow$ `v2`). `RegressionGate.evaluate()` therefore implements a three-state decision machine:

- **`PASS`**: All applicable counterexample witnesses in the ledger pass against the candidate patch.
- **`REGRESSION_DETECTED`**: The candidate patch matches a refuted canonical AST fingerprint under the **same** `contract_version` (`triggered_by="ast_filter"`), or fails behavioral **Witness Replay** under the **same** `contract_version` (`triggered_by="witness_replay"`).
- **`INCONCLUSIVE`**: A stored witness fails, but `ce.contract_version != current_contract_version` (`triggered_by="contract_mismatch"`), or the isolated witness runner encounters a sandbox/timeout error (`triggered_by="replay_error"`). Rather than falsely blocking a valid patch after specification evolution, the harness flags the transition and defers to the active reference oracle.

---

## 3. Experimental Methodology: Multi-Turn Experiment A & Experiment B

To maintain strict scientific honesty, **CEGAR-Harness** separates deterministic multi-turn harness evaluation from live stochastic LLM continuation:

### Experiment A: Multi-Turn Controlled Replay Benchmark with Partial Witness Coverage
Evaluates 5 context compaction strategies and 4 Regression Gate ablation configurations across **30 executable Python code-repair tasks** spanning 6 bug categories (5 tasks per category) under a strict post-compaction reference oracle budget of `max_oracle_turns = 2`:
1. `1_boundary_conditions` (`T01`–`T05`): Off-by-one bounds, inclusive thresholds, empty batch edge cases (`T01` and `T03` include partial witness coverage faults).
2. `2_parsers_state_machines` (`T06`–`T10`): Quoted CSV delimiters, unclosed bracket stacks, INI `=` values, backslash escapes, protocol `RESET` transitions (`T08` and `T10` include partial witness coverage faults; `T07` includes a lossy-summary distractor).
3. `3_exception_handling` (`T11`–`T15`): `None` type safety, out-of-range `ValueError`, intermediate `None` in nested dict lookup (`T13` partial witness coverage), `try/finally` cleanup, IEEE-754 `NaN`/`Inf` rejection.
4. `4_multi_file_changes` (`T16`–`T20`): Cross-module token TTL units, schema/serializer email normalization, tuple return unpacking in API gateway (`T16`–`T18` multi-file lossy distractors), tax-exempt item filtering, cycle-safe BFS (`T20` has 2 chained partial witness coverage faults).
5. `5_feature_regressions` (`T21`–`T25`): **Contract evolution (`v1` $\rightarrow$ `v2`)** testing how the ledger and gate handle specification drift when an old `v1` witness conflicts with a valid `v2` implementation.
6. `6_syntactic_variants` (`T26`–`T30`): **Syntactically distinct implementations of the same logical bug** (`for` loop vs. list comprehension, `sorted(set)` vs. `.sort()`, `if val:` vs. `or`, etc.) demonstrating why AST hashing is not semantic equivalence (`T28` and `T29` include 1 partial witness coverage fault; `T30` includes 2 chained partial witness coverage faults).

### Experiment B: Multi-Turn Live Agent Self-Repair Loop (`max_turns = 3`)
Connects `LiveLLMClient` (`CEGAR_LLM_API_BASE`, `CEGAR_LLM_API_KEY`, `CEGAR_LLM_MODEL`) to an OpenAI-compatible or local Ollama endpoint across up to 3 post-compaction self-repair turns. Under `CEGAR_HARNESS_FULL`, whenever `RegressionGate` returns `REGRESSION_DETECTED`, the harness blocks the candidate before full suite execution, injects the exact `matched_ce_id` and `failure_predicate` diagnostic, and grants a self-repair turn. When no live endpoint is configured, Experiment B explicitly reports `status: "NOT_EXECUTED_NO_CONFIG"` without fabricating or simulating LLM completions.

---

## 4. Empirical Results (Measured on Host via `cegar-harness bench`)

All figures below are generated directly by executing `bash scripts/run_benchmark.sh` (see `results/benchmark_report.json`, `results/experiment_a_results.json`, `results/ablation_study.json`, and `results/benchmark_summary.md`).

### 4.1 Multi-Turn Context Compaction Strategies Comparison (30 Tasks, `max_oracle_turns = 2`)

| Strategy | Mean Tokens (Pre $\rightarrow$ Post) | Compression (%) | Witness Retention (%) | Gate Blocked | Unblocked Reg. (%) [95% Wilson CI] | 2nd-Round CEs | Turn-1 Resolved (%) | Final Resolved (%) [95% Wilson CI] | Mean Oracle Turns |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `FULL_HISTORY` | 666.8 $\rightarrow$ 666.8 | 0.00% | 100.0% | 0 | 16.67% (5/30) `[7.3, 33.6]` | 0 | 63.33% (19/30) | 86.67% (26/30) `[70.3, 94.7]` | 1.37 |
| `OBSERVATION_MASKING` | 666.8 $\rightarrow$ 404.9 | 39.33% | 0.0% | 0 | 100.00% (30/30) `[88.7, 100.0]` | 0 | 0.00% (0/30) | 70.00% (21/30) `[52.1, 83.3]` | 2.00 |
| `LOSSY_SUMMARY` | 666.8 $\rightarrow$ 312.7 | 53.04% | 0.0% | 0 | 100.00% (30/30) `[88.7, 100.0]` | 0 | 0.00% (0/30) | 56.67% (17/30) `[39.2, 72.6]` | 2.00 |
| `CEGAR_LEDGER_ONLY` | 666.8 $\rightarrow$ 344.6 | 48.26% | 100.0% | 0 | 16.67% (5/30) `[7.3, 33.6]` | 10 | 63.33% (19/30) | 86.67% (26/30) `[70.3, 94.7]` | 1.37 |
| **`CEGAR_HARNESS_FULL`** | **666.8 $\rightarrow$ 344.6** | **48.26%** | **100.0%** | **5** | **0.00% (0/30) `[0.0, 11.3]`** | **11** | **70.00% (21/30)** | **93.33% (28/30) `[78.7, 98.2]`** | **1.30** |

### 4.2 Regression Gate 4-Way Ablation Study (30 Tasks, 60 Candidate Evaluations)

Each ablation configuration evaluates both the post-compaction regression candidate (`c1`) and the valid solution candidate (`c2`) across all 30 tasks (60 gate evaluations per configuration):

| Ablation Config | AST Filter | Witness Replay | Contract Ver. | Precision (%) | Recall (%) | F1 (%) | Cat. 6 Syn. Recall (%) | False Block (%) | Inconclusive | Final Resolved (%) | Median / p95 Latency (ms) | Ledger / Replay Overhead (ms) |
| :--- | :---: | :---: | :---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `full_cegar_harness` | ON | ON | ON | 100.00% | 100.00% (30/30) | 100.00% | 100.0% (5/5) | 0.00% (0/30) | 5 | 100.00% (30/30) | 18.89 / 21.72 | 0.37 / 11.53 |
| `ast_filter_only` | ON | OFF | ON | 100.00% | 83.33% (25/30) | 90.91% | 0.0% (0/5) | 0.00% (0/30) | 0 | 83.33% (25/30) | 0.30 / 0.62 | 0.34 / 0.00 |
| `witness_replay_only` | OFF | ON | ON | 100.00% | 100.00% (30/30) | 100.00% | 100.0% (5/5) | 0.00% (0/30) | 5 | 100.00% (30/30) | 18.59 / 22.00 | 0.35 / 18.68 |
| `unversioned_ledger` | ON | ON | OFF | 85.71% | 100.00% (30/30) | 92.31% | 100.0% (5/5) | 16.67% (5/30) | 0 | 83.33% (25/30) | 17.64 / 20.70 | 0.29 / 10.60 |

### 4.3 Per-Category Multi-Turn Regression & Convergence Breakdown

| Category | Tasks | Obs. Masking Unblocked Reg. | Obs. Masking Resolved | CEGAR Ledger-Only Unblocked Reg. | CEGAR Ledger-Only Resolved | CEGAR Full Unblocked Reg. | CEGAR Full Turn-1 Res. | CEGAR Full Final Res. | 2nd-Round CEs | Inconclusive (Contract Drift) |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `1_boundary_conditions` | 5 | 5/5 | 3/5 | 0/5 | 5/5 | 0/5 | 3/5 | **5/5** | 2 | 0 |
| `2_parsers_state_machines` | 5 | 5/5 | 3/5 | 0/5 | 5/5 | 0/5 | 3/5 | **5/5** | 2 | 0 |
| `3_exception_handling` | 5 | 5/5 | 4/5 | 0/5 | 5/5 | 0/5 | 4/5 | **5/5** | 1 | 0 |
| `4_multi_file_changes` | 5 | 5/5 | 4/5 | 0/5 | 4/5 | 0/5 | 4/5 | **4/5** | 2 | 0 |
| `5_feature_regressions` | 5 | 5/5 | 5/5 | 0/5 | 5/5 | 0/5 | 5/5 | **5/5** | 0 | 5 |
| `6_syntactic_variants` | 5 | 5/5 | 2/5 | 5/5 | 2/5 | 0/5 | 2/5 | **4/5** | 4 | 0 |

---

## 5. Industrial Integration: MCP Server, Git Adapter, LangGraph & Web UI

### 5.1 Model Context Protocol (MCP) Server for Claude Code & Cursor (`cegar-harness mcp-serve`)

`cegar_harness/mcp_server.py` implements a standard JSON-RPC 2.0 MCP server over `stdio` exposing 4 tools (`cegar_evaluate_patch`, `cegar_record_witness`, `cegar_compact_trajectory`, `cegar_query_ledger`). Add it to your `.mcp.json` or Cursor MCP configuration:

```json
{
  "mcpServers": {
    "cegar-harness": {
      "command": "cegar-harness",
      "args": ["mcp-serve", "--db", "results/counterexamples.sqlite"]
    }
  }
}
```

### 5.2 Atomic Git Workspace Adapter (`GitWorkspaceAdapter`)

`cegar_harness/git_workspace.py` applies candidate patches or unified diffs to a local Git repository, runs the `RegressionGate`, and performs an automatic atomic rollback (`git checkout -- .`) if `REGRESSION_DETECTED`:

```python
from cegar_harness.git_workspace import GitWorkspaceAdapter
from cegar_harness.ledger import CounterexampleLedger

ledger = CounterexampleLedger("results/counterexamples.sqlite")
adapter = GitWorkspaceAdapter(repo_path=".", ledger=ledger)

tx = adapter.apply_candidate_with_gate(
    task_id="T26",
    candidate_files={"scores.py": "def keep_valid_scores(scores):\n    return [s for s in scores if s]\n"},
    contract_version="v1",
)
# If tx.decision.status == GateStatus.REGRESSION_DETECTED:
# tx.applied is False and tx.rolled_back is True (working tree automatically restored)
```

### 5.3 Interactive Web Inspector UI (`cegar-harness ui`)

Launch the local web dashboard to inspect side-by-side context compaction diffs across all 30 tasks, test custom Python patches live in the Regression Gate sandbox, and explore the 4-way ablation & OpenTelemetry spans:

```bash
cegar-harness ui --port 8080
# Open http://127.0.0.1:8080 in your browser
```

---

## 6. Related Work & Positioning

| Work / Framework | Primary Focus | Key Finding / Mechanism | How `CEGAR-Harness` Complements / Differs |
| :--- | :--- | :--- | :--- |
| **Compact-Bench** ([arXiv:2610.31710](https://arxiv.org/abs/2610.31710), [GitHub](https://github.com/cai-jianfeng/compact-bench), Oct 2026) | Benchmarking compaction damage in coding agents | Compares full-history continuation vs. compacted continuation from identical repository states; shows mechanical extraction preserves recurring details better than free-form LLM summaries. | `CEGAR-Harness` extends passive extraction with an **executable 3-state Regression Gate** that actively replays failing witness tests before admitting post-compaction candidate patches. |
| **ACON** (*Optimizing Context Compression for Long-horizon LLM Agents*, [arXiv:2510.00615](https://arxiv.org/abs/2510.00615), 2025) | Learning compression guidelines from trajectories | Optimizes compression prompts by contrasting successful and failed compressed trajectories. | Operates as a **zero-training deterministic middleware** using a SQLite witness ledger and isolated test replay rather than prompt optimization alone. |
| **The Complexity Trap** ([JetBrains Research](https://kairos.jetbrains.com/research/publications/complexity-trap), 2025) | Observation masking vs. LLM summarization | Demonstrates that simple observation masking often matches or outperforms expensive LLM trajectory summarization in software engineering agents. | Includes `OBSERVATION_MASKING` and `LOSSY_SUMMARY` as direct baselines and shows how pairing observation pruning with a **Pinned Counterexample Ledger** retains 100% of witness predicates at 48.26% compression. |
| **ExVerus** ([ICML 2026](https://proceedings.mlr.press/v306/yang26bt.html), 2026) | Counterexample-guided formal proof repair | Uses verifier counterexamples to guide iterative LLM repair of formal Rust/Verus proofs within a single verification loop. | Adapts counterexample retention to **multi-turn Python code-repair compaction boundaries** with explicit `contract_version` tracking (`INCONCLUSIVE` state) to prevent false blocks under requirement drift. |
| **SWE-bench** ([GitHub](https://github.com/SWE-bench/SWE-bench)) | Real-world repository issue resolution benchmark | Evaluates end-to-end patch resolution across real GitHub issues using Dockerized test harnesses. | Provides a lightweight, self-contained **30-task micro-benchmark** (`Experiment A`) specifically structured to isolate post-compaction regression mechanics, syntactic bug variants, partial witness coverage, and contract evolution in `< 20s`. |

---

## 7. Quickstart & Reproduction

```bash
# 1. Create virtual environment and install dependencies
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# 2. Run the full unit, MCP/Git/LangGraph, Web UI, and benchmark integrity test suite (11 tests)
pytest -v

# 3. Run the end-to-end benchmark script (Tests + Experiment A + Experiment B status)
bash scripts/run_benchmark.sh

# 4. Launch the interactive Web Inspector UI
cegar-harness ui --port 8080

# 5. Start the MCP JSON-RPC 2.0 server over stdio
cegar-harness mcp-serve --db results/counterexamples.sqlite

# 6. Inspect stored counterexamples in the SQLite ledger
cegar-harness inspect-ledger --db results/counterexamples.sqlite --task-id T26
```

### Running Experiment B Multi-Turn Self-Repair Loop with a Live LLM Endpoint (Optional)

```bash
export CEGAR_LLM_API_BASE="http://localhost:11434/v1"
export CEGAR_LLM_MODEL="qwen2.5-coder:7b"
export CEGAR_LLM_API_KEY="ollama"
cegar-harness live-eval --max-tasks 5
```

