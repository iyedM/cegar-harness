# CEGAR-Harness Empirical Benchmark Report

## 1. Experiment A: Context Compaction Strategies (30 Tasks)

| Strategy | Mean Tokens Before | Mean Tokens After | Compression (%) | Witness Retention (%) | Gate Blocked | Unblocked Regressions (%) | False Block (%) | Resolution Rate (%) |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `FULL_HISTORY` | 666.8 | 666.8 | 0.00% | 100.0% | 0 | 16.67% (5/30) | 0.00% | 83.33% (25/30) |
| `OBSERVATION_MASKING` | 666.8 | 404.9 | 39.33% | 0.0% | 0 | 100.00% (30/30) | 0.00% | 0.00% (0/30) |
| `LOSSY_SUMMARY` | 666.8 | 312.7 | 53.04% | 0.0% | 0 | 100.00% (30/30) | 0.00% | 0.00% (0/30) |
| `CEGAR_LEDGER_ONLY` | 666.8 | 344.6 | 48.26% | 100.0% | 0 | 16.67% (5/30) | 0.00% | 83.33% (25/30) |
| `CEGAR_HARNESS_FULL` | 666.8 | 344.6 | 48.26% | 100.0% | 5 | 0.00% (0/30) | 0.00% | 100.00% (30/30) |

## 2. Experiment A: Regression Gate Ablation Study (30 Tasks, 60 Candidate Evaluations)

| Ablation Config | AST Filter | Witness Replay | Contract Ver. | Regression Recall (%) | Cat. 6 Syntactic Recall (%) | False Block Rate (%) | Inconclusive | Final Resolved (%) | Mean Gate Latency (ms) |
| :--- | :---: | :---: | :---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `full_cegar_harness` | ON | ON | ON | 100.00% (30/30) | 100.0% (5/5) | 0.00% (0/30) | 5 | 100.00% (30/30) | 13.74 |
| `ast_filter_only` | ON | OFF | ON | 83.33% (25/30) | 0.0% (0/5) | 0.00% (0/30) | 0 | 83.33% (25/30) | 0.38 |
| `witness_replay_only` | OFF | ON | ON | 100.00% (30/30) | 100.0% (5/5) | 0.00% (0/30) | 5 | 100.00% (30/30) | 22.09 |
| `unversioned_ledger` | ON | ON | OFF | 100.00% (30/30) | 100.0% (5/5) | 16.67% (5/30) | 0 | 83.33% (25/30) | 13.05 |

## 3. Experiment A: Per-Category Regression Breakdown

| Category | Tasks | Obs. Masking Unblocked Reg. | CEGAR Ledger-Only Unblocked Reg. | CEGAR Full Unblocked Reg. | CEGAR Full Resolved | Inconclusive (Contract Drift) |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: |
| `1_boundary_conditions` | 5 | 5/5 | 0/5 | 0/5 | 5/5 | 0 |
| `2_parsers_state_machines` | 5 | 5/5 | 0/5 | 0/5 | 5/5 | 0 |
| `3_exception_handling` | 5 | 5/5 | 0/5 | 0/5 | 5/5 | 0 |
| `4_multi_file_changes` | 5 | 5/5 | 0/5 | 0/5 | 5/5 | 0 |
| `5_feature_regressions` | 5 | 5/5 | 0/5 | 0/5 | 5/5 | 5 |
| `6_syntactic_variants` | 5 | 5/5 | 5/5 | 0/5 | 5/5 | 0 |

## 4. Experiment B: Live LLM Agent Continuation

- **Status:** `NOT_EXECUTED_NO_CONFIG`
- **Executed:** `False`
- **Model:** `none`
- **Note:** Live LLM experiment not executed: CEGAR_LLM_API_BASE and CEGAR_LLM_MODEL environment variables are not configured.
