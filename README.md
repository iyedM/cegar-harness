# CEGAR-Harness: Regression-Aware Context Compaction & Witness Replay for Coding Agents

[![CI](https://github.com/iyedM/cegar-harness/actions/workflows/ci.yml/badge.svg)](https://github.com/iyedM/cegar-harness/actions/workflows/ci.yml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

**CEGAR-Harness** is an open-source research middleware and empirical evaluation harness for autonomous coding agents. Inspired by Counterexample-Guided Abstraction Refinement (CEGAR), it mitigates **Post-Compaction Regression Loops (PCRL)**—where a coding agent re-introduces a previously refuted bug after context window compaction strips away earlier failure tracebacks—by:

1. **Recording reproducible failure witnesses** (*counterexamples*) in a persistent, contract-versioned SQLite ledger (`CounterexampleLedger`),
2. **Pinning active counterexample predicates** during context compaction (`CompactionController`), and
3. **Gating candidate code patches** through a three-state `RegressionGate` (`PASS`, `REGRESSION_DETECTED`, `INCONCLUSIVE`) backed by an optional syntactic AST canonicalization pre-filter and isolated behavioral **Witness Replay** (`IsolatedTestRunner`).

---

## 1. Problem Statement & Motivating Example

Long-horizon coding sessions rapidly accumulate verbose tool outputs (pytest stack traces, file dumps, static analysis logs). When the context approaches a token threshold, agent harnesses trigger **Context Compaction** (via observation masking or narrative LLM summarization). Because standard compaction is lossy with respect to exact falsifying inputs and assertion predicates, the agent frequently suffers from **post-compaction amnesia** and re-proposes a broken patch—or a syntactically distinct rewrite of the same logical defect—that was already refuted earlier in the session.

| Step | Standard Compaction (`OBSERVATION_MASKING` / `LOSSY_SUMMARY`) | `CEGAR-Harness` (`CEGAR_HARNESS_FULL`) |
| :--- | :--- | :--- |
| **Step 1–2 (Pre-Compaction)** | Agent proposes patch `p1` (`if item:` filter that accidentally drops valid `0` integers). Witness test `test_zero_retained` fails (`AssertionError: [1, 2] != [0, 1, 2]`). | Same failure occurs. `CEGAR-Harness` extracts and records `CE-T26-01` (`contract_version="v1"`, `ast_hash`, `witness_test_code`, `failure_predicate`) in SQLite. |
| **Step 3–6 (Exploration)** | Agent inspects call sites and control flow (+450 tokens of tool observations). | Same exploration turns. |
| **Compaction Boundary** | Old tool outputs are masked or summarized into *"The agent encountered 1 test failure."* **Exact falsifying witness (`0` dropped) is lost.** | Verbose observations are pruned (**48.26% token compression**), while `CE-T26-01` predicate and AST fingerprint remain pinned in the compacted header. |
| **Post-Compaction Continuation** | Agent re-proposes `p1` (or a list-comprehension variant `[x for x in items if x]`), causing an **unblocked post-compaction regression**. | If the agent proposes a syntactic variant `[x for x in items if x]`, `RegressionGate` replays `test_zero_retained` in an isolated sandbox (`~19 ms`), returns `REGRESSION_DETECTED`, blocks the regression before full suite execution, and resolves on `if x is not None`. |

---

## 2. System Architecture & Three-State Regression Gate

```text
cegar-harness/
├── pyproject.toml
├── Dockerfile
├── .github/workflows/ci.yml
├── scripts/
│   └── run_benchmark.sh
├── cegar_harness/
│   ├── __init__.py
│   ├── models.py          # Schemas: GateStatus, CompactionStrategy, BugCategory, CounterexampleRecord, TaskSpec
│   ├── ast_filter.py      # Optional AST canonicalization pre-filter (alpha-renaming + docstring/comment stripping)
│   ├── ledger.py          # SQLite-backed Versioned Counterexample Ledger
│   ├── replay.py          # IsolatedTestRunner: sandboxed subprocess execution with sys.path isolation & timeout
│   ├── gate.py            # 3-state RegressionGate (PASS, REGRESSION_DETECTED, INCONCLUSIVE) + latency breakdown
│   ├── compactor.py       # CompactionController implementing 5 context compaction strategies
│   ├── telemetry.py       # OpenTelemetry spans (`cegar.gate.evaluate`, `cegar.compaction.run`) + JSONL audit log
│   ├── llm_provider.py    # LiveLLMClient for Experiment B (OpenAI/LiteLLM/Ollama; explicit NOT_EXECUTED_NO_CONFIG)
│   ├── tasks.py           # 30 deterministic Python code-repair tasks across 6 categories (5 tasks/category)
│   ├── benchmark.py       # Experiment A (Controlled Replay + 4-way Ablation) & Experiment B runner + exporters
│   └── cli.py             # CLI: `cegar-harness bench`, `cegar-harness live-eval`, `cegar-harness inspect-ledger`
└── tests/
    ├── test_ast_filter.py
    ├── test_compactor.py
    ├── test_gate_and_replay.py
    └── test_benchmark_integrity.py
```

### Three-State `RegressionGate` Semantics

A naive gatekeeper that blocks every patch failing a historical test will reject legitimate solutions whenever the task specification evolves (e.g., `v1` $\rightarrow$ `v2`). `RegressionGate.evaluate()` therefore implements a three-state decision machine:

- **`PASS`**: All applicable counterexample witnesses in the ledger pass against the candidate patch.
- **`REGRESSION_DETECTED`**: The candidate patch matches a refuted canonical AST fingerprint under the **same** `contract_version` (`triggered_by="ast_filter"`), or fails behavioral **Witness Replay** under the **same** `contract_version` (`triggered_by="witness_replay"`).
- **`INCONCLUSIVE`**: A stored witness fails, but `ce.contract_version != current_contract_version` (`triggered_by="contract_mismatch"`), or the isolated witness runner encounters a sandbox/timeout error (`triggered_by="replay_error"`). Rather than falsely blocking a valid patch after specification evolution, the harness flags the transition and defers to the active reference oracle.

### Core Data Schema (`CounterexampleRecord`)

```python
@dataclass
class CounterexampleRecord:
    ce_id: str                  # e.g., "CE-T01-01"
    task_id: str                # e.g., "T01"
    target_file: str            # e.g., "pagination.py"
    target_symbol: str          # e.g., "slice_page"
    contract_version: str       # e.g., "v1"
    ast_hash: str               # SHA-256 of alpha-normalized AST
    witness_name: str           # e.g., "test_witness_last_item_boundary"
    witness_test_code: str      # Minimal isolated Python test function
    failure_predicate: str      # Extracted assertion/exception predicate
    discovered_at_step: int     # Trajectory turn index
    status: str = "ACTIVE"      # ACTIVE | RESOLVED | OBSOLETE
    provenance: str = "oracle_witness_failure"
```

---

## 3. Experimental Methodology: Experiment A vs. Experiment B

To maintain strict scientific honesty, **CEGAR-Harness** separates deterministic harness evaluation from live stochastic LLM continuation:

### Experiment A: Controlled Replay Benchmark (Deterministic, Always Executable)
Evaluates 5 context compaction strategies and 4 Regression Gate ablation configurations across **30 executable Python code-repair tasks** spanning 6 bug categories (5 tasks per category):
1. `1_boundary_conditions` (`T01`–`T05`): Off-by-one bounds, inclusive thresholds, empty batch edge cases.
2. `2_parsers_state_machines` (`T06`–`T10`): Quoted CSV delimiters, unclosed bracket stacks, INI `=` values, backslash escapes, protocol `RESET` transitions.
3. `3_exception_handling` (`T11`–`T15`): `None` type safety, out-of-range `ValueError`, intermediate `None` in nested dict lookup, `try/finally` cleanup, IEEE-754 `NaN`/`Inf` rejection.
4. `4_multi_file_changes` (`T16`–`T20`): Cross-module token TTL units, schema/serializer email normalization, tuple return unpacking in API gateway, tax-exempt item filtering, cycle-safe BFS.
5. `5_feature_regressions` (`T21`–`T25`): **Contract evolution (`v1` $\rightarrow$ `v2`)** testing how the ledger and gate handle specification drift when an old `v1` witness conflicts with a valid `v2` implementation.
6. `6_syntactic_variants` (`T26`–`T30`): **Syntactically distinct implementations of the same logical bug** (`for` loop vs. list comprehension, `sorted(set)` vs. `.sort()`, `if val:` vs. `or`, etc.) demonstrating why AST hashing is not semantic equivalence.

### Experiment B: Live LLM Agent Continuation (Optional, Config-Dependent)
Connects `LiveLLMClient` (`CEGAR_LLM_API_BASE`, `CEGAR_LLM_API_KEY`, `CEGAR_LLM_MODEL`) to an OpenAI-compatible or local Ollama endpoint to generate live post-compaction patches. When no endpoint is configured, Experiment B explicitly reports `status: "NOT_EXECUTED_NO_CONFIG"` and `executed: false` without ever fabricating or simulating LLM responses.

---

## 4. Empirical Results (Measured on Host via `cegar-harness bench`)

All figures below are generated directly by executing `bash scripts/run_benchmark.sh` (see `results/benchmark_report.json`, `results/experiment_a_results.json`, `results/ablation_study.json`, and `results/benchmark_summary.md`).

### 4.1 Context Compaction Strategies Comparison (30 Tasks)

| Strategy | Mean Tokens Before | Mean Tokens After | Compression (%) | Witness Retention (%) | Gate Blocked | Unblocked Regressions (%) | False Block (%) | Resolution Rate (%) |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `FULL_HISTORY` | 666.8 | 666.8 | 0.00% | 100.0% | 0 | 16.67% (5/30) | 0.00% | 83.33% (25/30) |
| `OBSERVATION_MASKING` | 666.8 | 404.9 | 39.33% | 0.0% | 0 | 100.00% (30/30) | 0.00% | 0.00% (0/30) |
| `LOSSY_SUMMARY` | 666.8 | 312.7 | 53.04% | 0.0% | 0 | 100.00% (30/30) | 0.00% | 0.00% (0/30) |
| `CEGAR_LEDGER_ONLY` | 666.8 | 344.6 | 48.26% | 100.0% | 0 | 16.67% (5/30) | 0.00% | 83.33% (25/30) |
| `CEGAR_HARNESS_FULL` | 666.8 | 344.6 | 48.26% | 100.0% | 5 | 0.00% (0/30) | 0.00% | 100.00% (30/30) |

### 4.2 Regression Gate 4-Way Ablation Study (30 Tasks, 60 Candidate Evaluations)

Each ablation configuration evaluates both the post-compaction regression candidate (`c1`) and the valid solution candidate (`c2`) across all 30 tasks (60 gate evaluations per configuration):

| Ablation Config | AST Filter | Witness Replay | Contract Ver. | Precision (%) | Recall (%) | F1 (%) | Cat. 6 Syn. Recall (%) | False Block (%) | Inconclusive | Final Resolved (%) | Median / p95 Latency (ms) | Ledger / Replay Overhead (ms) |
| :--- | :---: | :---: | :---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `full_cegar_harness` | ON | ON | ON | 100.00% | 100.00% (30/30) | 100.00% | 100.0% (5/5) | 0.00% (0/30) | 5 | 100.00% (30/30) | 19.07 / 21.82 | 0.36 / 11.59 |
| `ast_filter_only` | ON | OFF | ON | 100.00% | 83.33% (25/30) | 90.91% | 0.0% (0/5) | 0.00% (0/30) | 0 | 83.33% (25/30) | 0.30 / 0.65 | 0.34 / 0.00 |
| `witness_replay_only` | OFF | ON | ON | 100.00% | 100.00% (30/30) | 100.00% | 100.0% (5/5) | 0.00% (0/30) | 5 | 100.00% (30/30) | 19.93 / 22.87 | 0.41 / 19.61 |
| `unversioned_ledger` | ON | ON | OFF | 85.71% | 100.00% (30/30) | 92.31% | 100.0% (5/5) | 16.67% (5/30) | 0 | 83.33% (25/30) | 18.75 / 21.42 | 0.36 / 11.43 |

### 4.3 Per-Category Regression Breakdown

| Category | Tasks | Obs. Masking Unblocked Reg. | CEGAR Ledger-Only Unblocked Reg. | CEGAR Full Unblocked Reg. | CEGAR Full Resolved | Inconclusive (Contract Drift) |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: |
| `1_boundary_conditions` | 5 | 5/5 | 0/5 | 0/5 | 5/5 | 0 |
| `2_parsers_state_machines` | 5 | 5/5 | 0/5 | 0/5 | 5/5 | 0 |
| `3_exception_handling` | 5 | 5/5 | 0/5 | 0/5 | 5/5 | 0 |
| `4_multi_file_changes` | 5 | 5/5 | 0/5 | 0/5 | 5/5 | 0 |
| `5_feature_regressions` | 5 | 5/5 | 0/5 | 0/5 | 5/5 | 5 |
| `6_syntactic_variants` | 5 | 5/5 | 5/5 | 0/5 | 5/5 | 0 |

---

## 5. Related Work & Positioning

**CEGAR-Harness** builds upon recent research in context compression, agent evaluation benchmarks, and counterexample-guided program repair. Rather than claiming to be the first context compaction study or the first application of CEGAR to LLMs, it targets a specific engineering and empirical gap: **persistent, contract-versioned witness replay across compaction boundaries**.

| Work / Framework | Primary Focus | Key Finding / Mechanism | How `CEGAR-Harness` Complements / Differs |
| :--- | :--- | :--- | :--- |
| **Compact-Bench** ([arXiv:2610.31710](https://arxiv.org/abs/2610.31710), [GitHub](https://github.com/cai-jianfeng/compact-bench), Oct 2026) | Benchmarking compaction damage in coding agents | Compares full-history continuation vs. compacted continuation from identical repository states; shows mechanical extraction preserves recurring details better than free-form LLM summaries. | `CEGAR-Harness` extends passive extraction with an **executable 3-state Regression Gate** that actively replays failing witness tests before admitting post-compaction candidate patches. |
| **ACON** (*Optimizing Context Compression for Long-horizon LLM Agents*, [arXiv:2510.00615](https://arxiv.org/abs/2510.00615), 2025) | Learning compression guidelines from trajectories | Optimizes compression prompts by contrasting successful and failed compressed trajectories. | Operates as a **zero-training deterministic middleware** using a SQLite witness ledger and isolated test replay rather than prompt optimization alone. |
| **The Complexity Trap** ([JetBrains Research](https://kairos.jetbrains.com/research/publications/complexity-trap), 2025) | Observation masking vs. LLM summarization | Demonstrates that simple observation masking often matches or outperforms expensive LLM trajectory summarization in software engineering agents. | Includes `OBSERVATION_MASKING` and `LOSSY_SUMMARY` as direct baselines and shows how pairing observation pruning with a **Pinned Counterexample Ledger** retains 100% of witness predicates at 48.26% compression. |
| **ExVerus** ([ICML 2026](https://proceedings.mlr.press/v306/yang26bt.html), 2026) | Counterexample-guided formal proof repair | Uses verifier counterexamples to guide iterative LLM repair of formal Rust/Verus proofs within a single verification loop. | Adapts counterexample retention to **multi-turn Python code-repair compaction boundaries** with explicit `contract_version` tracking (`INCONCLUSIVE` state) to prevent false blocks under requirement drift. |
| **SWE-bench** ([GitHub](https://github.com/SWE-bench/SWE-bench)) | Real-world repository issue resolution benchmark | Evaluates end-to-end patch resolution across real GitHub issues using Dockerized test harnesses. | Provides a lightweight, self-contained **30-task micro-benchmark** (`Experiment A`) specifically structured to isolate post-compaction regression mechanics, syntactic bug variants, and contract evolution in `< 15s`. |

---

## 6. Key Scientific Findings, Limitations & Threats to Validity

1. **Why AST Canonicalization is Only an Optimization Pre-Filter (Not Semantic Equivalence):**
   - In `ast_filter_only`, canonical AST hashing (`_AlphaNormalizer`) catches 25/25 alpha-renamed duplicates with `0.34 ms` mean ledger/AST overhead (`0.30 ms` median, `0.65 ms` p95), but achieves **0.0% (0/5) recall on Category 6 (`6_syntactic_variants`)** because syntactically distinct rewrites (e.g., replacing a `for` loop with a list comprehension that preserves the same falsy-zero bug) produce different AST hashes.
   - Behavioral **Witness Replay** (`witness_replay_only` and `full_cegar_harness`) executes the stored failing test in an isolated sandbox and achieves **100.0% (5/5) recall on Category 6**. Combining the AST pre-filter with Witness Replay (`full_cegar_harness`) preserves `100.0%` precision and `100.0%` recall (`F1 = 100.0%`) while reducing mean replay overhead from `19.61 ms` (`witness_replay_only`) to `11.59 ms` (~41% reduction in mean subprocess replay time).
2. **Why Contract Versioning & the `INCONCLUSIVE` State Are Necessary:**
   - When requirements evolve between compaction boundaries (`Category 5`, `v1` $\rightarrow$ `v2`), an unversioned ledger (`unversioned_ledger`) replays stale `v1` witnesses against valid `v2` patches and **falsely blocks 100% (5/5) of evolved-contract tasks** (`16.67%` overall False Block Rate, dropping Gate Precision to `85.71%`).
   - Tracking `contract_version` and emitting `GateStatus.INCONCLUSIVE` (`triggered_by="contract_mismatch"`) eliminates these false blocks (`0.00%` False Block Rate, `100.00%` Gate Precision) while recording the contract transition in OpenTelemetry and JSONL audit logs.
3. **Limitations & Threats to Validity:**
   - **Controlled Replay vs. Stochastic Sampling:** Experiment A uses deterministic pre-recorded candidate trajectories conditioned on whether the witness predicate survives compaction. While this guarantees exact reproducibility and isolates gate mechanics in ablation testing, real LLM continuation rates vary by model family, prompt formatting, and temperature (supported via Experiment B).
   - **Witness Quality & Granularity:** Witness replay is only as selective as the extracted witness assertion. Overly brittle witnesses tied to internal implementation details can cause false blocks if internal helper signatures change without bumping `contract_version`.
   - **Subprocess Startup Overhead:** Each isolated witness execution incurs `~19–22 ms` (median `19.07 ms`, p95 `21.82 ms`) of Python subprocess startup overhead. While negligible compared to multi-second LLM inference calls, scaling to hundreds of witnesses per task requires indexing by `target_file` and `target_symbol`.

---

## 7. Quickstart & Reproduction

```bash
# 1. Create virtual environment and install dependencies
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# 2. Run the full unit and benchmark integrity test suite
pytest -v

# 3. Run the end-to-end benchmark script (Tests + Experiment A + Experiment B status)
bash scripts/run_benchmark.sh

# 4. Inspect stored counterexamples in the SQLite ledger
cegar-harness inspect-ledger --db results/counterexamples.sqlite --task-id T26
```

### Running Experiment B with a Live LLM Endpoint (Optional)

```bash
export CEGAR_LLM_API_BASE="http://localhost:11434/v1"
export CEGAR_LLM_MODEL="qwen2.5-coder:7b"
export CEGAR_LLM_API_KEY="ollama"
cegar-harness live-eval --max-tasks 5
```

### Generated Artifacts in `results/`

| File | Description |
| :--- | :--- |
| `results/benchmark_report.json` | Complete raw JSON output for Experiment A (strategies, ablations, per-task details) and Experiment B status |
| `results/experiment_a_results.json` | Experiment A controlled replay and ablation results |
| `results/ablation_study.json` | Detailed 4-way RegressionGate ablation metrics (Precision, Recall, F1, Median/p95 latency, Ledger/Replay overhead) |
| `results/strategy_metrics.csv` / `results/experiment_a_summary.csv` | Tabular CSV comparison of the 5 context compaction strategies |
| `results/ablation_metrics.csv` | Tabular CSV comparison of the 4 RegressionGate ablation configurations |
| `results/category_breakdown.csv` | Per-category regression and resolution breakdown across the 6 bug categories |
| `results/benchmark_summary.md` | Auto-generated Markdown report tables |
| `results/telemetry_events.jsonl` | Structured JSONL audit log of all `compaction` and `gate_evaluation` events |
| `results/counterexamples.sqlite` | Persistent SQLite Counterexample Ledger populated during the benchmark run |
