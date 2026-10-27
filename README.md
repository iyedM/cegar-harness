# CEGAR-Harness: Regression-Aware Context Compaction & Witness Replay for Coding Agents

**CEGAR-Harness** is an open-source research middleware and evaluation harness for autonomous coding agents. Inspired by Counterexample-Guided Abstraction Refinement (CEGAR), it prevents coding agents from re-introducing previously refuted bugs after context compaction by:

1. **Recording reproducible failure witnesses** (*counterexamples*) in a persistent, contract-versioned SQLite ledger (`CounterexampleLedger`),
2. **Pinning active counterexample predicates** during context compaction (`CompactionController`), and
3. **Gating candidate code patches** through a three-state `RegressionGate` (`PASS`, `REGRESSION_DETECTED`, `INCONCLUSIVE`) backed by an optional syntactic AST pre-filter and isolated behavioral **Witness Replay** (`IsolatedTestRunner`).

---

## Architecture Overview

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
│   ├── gate.py            # 3-state RegressionGate (PASS, REGRESSION_DETECTED, INCONCLUSIVE) + ablation flags
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

---

## Experimental Methodology: Experiment A vs. Experiment B

To maintain strict scientific honesty, **CEGAR-Harness** separates deterministic harness evaluation from live stochastic LLM continuation:

### Experiment A: Controlled Replay Benchmark (Deterministic, Always Executable)
Evaluates the 5 context compaction strategies and 4 Regression Gate ablation configurations across **30 executable Python code-repair tasks** spanning 6 bug categories (5 tasks per category):
1. `1_boundary_conditions` (`T01`–`T05`): Off-by-one bounds, inclusive thresholds, empty batch edge cases.
2. `2_parsers_state_machines` (`T06`–`T10`): Quoted CSV delimiters, unclosed bracket stacks, INI `=` values, backslash escapes, protocol `RESET` transitions.
3. `3_exception_handling` (`T11`–`T15`): `None` type safety, out-of-range `ValueError`, intermediate `None` in nested dict lookup, `try/finally` cleanup, IEEE-754 `NaN`/`Inf` rejection.
4. `4_multi_file_changes` (`T16`–`T20`): Cross-module token TTL units, schema/serializer email normalization, tuple return unpacking in API gateway, tax-exempt item filtering, cycle-safe BFS.
5. `5_feature_regressions` (`T21`–`T25`): **Contract evolution (`v1` $\rightarrow$ `v2`)** testing how the ledger and gate handle specification drift when an old `v1` witness conflicts with a valid `v2` implementation.
6. `6_syntactic_variants` (`T26`–`T30`): **Syntactically distinct implementations of the same logical bug** (`for` loop vs. list comprehension, `sorted(set)` vs. `.sort()`, `if val:` vs. `or`, etc.) demonstrating why AST hashing is not semantic equivalence.

### Experiment B: Live LLM Agent Continuation (Optional, Config-Dependent)
Connects `LiveLLMClient` (`CEGAR_LLM_API_BASE`, `CEGAR_LLM_API_KEY`, `CEGAR_LLM_MODEL`) to an OpenAI-compatible or local Ollama endpoint to generate live post-compaction patches. When no endpoint is configured, Experiment B explicitly reports `status: "NOT_EXECUTED_NO_CONFIG"` and `executed: false` without ever fabricating or simulating LLM responses.

---

## Empirical Results (Measured on Host via `cegar-harness bench`)

All figures below are generated directly by executing `python -m cegar_harness.cli bench --output-dir results` (see `results/benchmark_report.json` and `results/benchmark_summary.md`).

### 1. Context Compaction Strategies Comparison (30 Tasks)

| Strategy | Mean Tokens Before | Mean Tokens After | Compression (%) | Witness Retention (%) | Gate Blocked | Unblocked Regressions (%) | False Block (%) | Resolution Rate (%) |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `FULL_HISTORY` | 666.8 | 666.8 | 0.00% | 100.0% | 0 | 16.67% (5/30) | 0.00% | 83.33% (25/30) |
| `OBSERVATION_MASKING` | 666.8 | 404.9 | 39.33% | 0.0% | 0 | 100.00% (30/30) | 0.00% | 0.00% (0/30) |
| `LOSSY_SUMMARY` | 666.8 | 312.7 | 53.04% | 0.0% | 0 | 100.00% (30/30) | 0.00% | 0.00% (0/30) |
| `CEGAR_LEDGER_ONLY` | 666.8 | 344.6 | 48.26% | 100.0% | 0 | 16.67% (5/30) | 0.00% | 83.33% (25/30) |
| `CEGAR_HARNESS_FULL` | 666.8 | 344.6 | 48.26% | 100.0% | 5 | 0.00% (0/30) | 0.00% | 100.00% (30/30) |

### 2. Regression Gate 4-Way Ablation Study (30 Tasks, 60 Candidate Evaluations)

Each ablation configuration evaluates both the post-compaction regression candidate (`c1`) and the valid solution candidate (`c2`) across all 30 tasks (60 gate evaluations per configuration):

| Ablation Config | AST Filter | Witness Replay | Contract Ver. | Regression Recall (%) | Cat. 6 Syntactic Recall (%) | False Block Rate (%) | Inconclusive | Final Resolved (%) | Mean Gate Latency (ms) |
| :--- | :---: | :---: | :---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `full_cegar_harness` | ON | ON | ON | 100.00% (30/30) | 100.0% (5/5) | 0.00% (0/30) | 5 | 100.00% (30/30) | 13.74 |
| `ast_filter_only` | ON | OFF | ON | 83.33% (25/30) | 0.0% (0/5) | 0.00% (0/30) | 0 | 83.33% (25/30) | 0.38 |
| `witness_replay_only` | OFF | ON | ON | 100.00% (30/30) | 100.0% (5/5) | 0.00% (0/30) | 5 | 100.00% (30/30) | 22.09 |
| `unversioned_ledger` | ON | ON | OFF | 100.00% (30/30) | 100.0% (5/5) | 16.67% (5/30) | 0 | 83.33% (25/30) | 13.05 |

### 3. Per-Category Regression Breakdown

| Category | Tasks | Obs. Masking Unblocked Reg. | CEGAR Ledger-Only Unblocked Reg. | CEGAR Full Unblocked Reg. | CEGAR Full Resolved | Inconclusive (Contract Drift) |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: |
| `1_boundary_conditions` | 5 | 5/5 | 0/5 | 0/5 | 5/5 | 0 |
| `2_parsers_state_machines` | 5 | 5/5 | 0/5 | 0/5 | 5/5 | 0 |
| `3_exception_handling` | 5 | 5/5 | 0/5 | 0/5 | 5/5 | 0 |
| `4_multi_file_changes` | 5 | 5/5 | 0/5 | 0/5 | 5/5 | 0 |
| `5_feature_regressions` | 5 | 5/5 | 0/5 | 0/5 | 5/5 | 5 |
| `6_syntactic_variants` | 5 | 5/5 | 5/5 | 0/5 | 5/5 | 0 |

---

## Key Scientific Findings & Limitations

1. **Why AST Canonicalization is Only an Optimization Pre-Filter (Not Semantic Equivalence):**
   - In `ast_filter_only`, canonical AST hashing (`_AlphaNormalizer`) catches 25/25 alpha-renamed duplicates in `0.38 ms`, but achieves **0.0% (0/5) recall on Category 6 (`6_syntactic_variants`)** because syntactically distinct rewrites (e.g., replacing a `for` loop with a list comprehension that preserves the same falsy-zero bug) produce different AST hashes.
   - Behavioral **Witness Replay** (`witness_replay_only` and `full_cegar_harness`) executes the stored failing test in an isolated sandbox and achieves **100.0% (5/5) recall on Category 6**. Combining the AST pre-filter with Witness Replay (`full_cegar_harness`) preserves 100% recall while lowering mean gate latency from `22.09 ms` to `13.74 ms` (~38% latency reduction).
2. **Why Contract Versioning & the `INCONCLUSIVE` State Are Necessary:**
   - When requirements evolve between compaction boundaries (`Category 5`, `v1` $\rightarrow$ `v2`), an unversioned ledger (`unversioned_ledger`) replays stale `v1` witnesses against valid `v2` patches and **falsely blocks 100% (5/5) of evolved-contract tasks** (`16.67%` overall False Block Rate).
   - Tracking `contract_version` and emitting `GateStatus.INCONCLUSIVE` (`triggered_by="contract_mismatch"`) eliminates these false blocks (`0.00%` False Block Rate) while flagging the contract transition in telemetry.
3. **Threats to Validity:**
   - **Controlled Replay vs. Stochastic Sampling:** Experiment A uses deterministic pre-recorded candidate trajectories conditioned on whether the witness predicate survives compaction. While this guarantees exact reproducibility and isolates gate mechanics in ablation testing, real LLM continuation rates vary by model family and temperature (supported via Experiment B).
   - **Witness Quality Dependence:** Witness replay is only as selective as the extracted witness assertion. Overly brittle witnesses tied to internal implementation details can cause false blocks if internal APIs change without bumping `contract_version`.
   - **Subprocess Replay Overhead:** Each isolated witness execution incurs ~20 ms of Python interpreter startup overhead. While negligible compared to multi-second LLM inference, large witness suites require target-file/symbol indexing (`target_file`, `target_symbol`) to keep replay sub-100ms.

---

## Quickstart & Reproduction

```bash
# 1. Install in virtual environment
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# 2. Run the full test suite
pytest -v

# 3. Run the end-to-end benchmark script (Tests + Experiment A + Experiment B status)
bash scripts/run_benchmark.sh

# 4. Inspect stored counterexamples in the SQLite ledger
cegar-harness inspect-ledger --db results/counterexamples.sqlite --task-id T26
```

### Running Experiment B with a Live LLM (Optional)

```bash
export CEGAR_LLM_API_BASE="http://localhost:11434/v1"
export CEGAR_LLM_MODEL="qwen2.5-coder:7b"
export CEGAR_LLM_API_KEY="ollama"
cegar-harness live-eval --max-tasks 5
```
