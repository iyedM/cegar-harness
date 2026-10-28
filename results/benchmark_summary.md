# CEGAR-Harness Empirical Benchmark Report

## 1. Experiment A: Multi-Turn Context Compaction Strategies (30 Tasks, Max 2 Oracle Turns)

| Strategy | Tokens (Before -> After) | Comp. (%) | Witness Retention (%) | Gate Blocked | Unblocked Reg. (%) [95% CI] | 2nd-Round Witnesses | Turn-1 Resolved (%) | Final Resolved (%) [95% CI] | Mean Oracle Turns |
| :--- | :---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `FULL_HISTORY` | 666.8 -> 666.8 | 0.00% | 100.0% | 0 | 16.67% [7.3, 33.6] | 0 | 63.33% (19/30) | 86.67% (26/30) [70.3, 94.7] | 1.37 |
| `OBSERVATION_MASKING` | 666.8 -> 404.9 | 39.33% | 0.0% | 0 | 100.00% [88.7, 100.0] | 0 | 0.00% (0/30) | 70.00% (21/30) [52.1, 83.3] | 2.00 |
| `LOSSY_SUMMARY` | 666.8 -> 312.7 | 53.04% | 0.0% | 0 | 100.00% [88.7, 100.0] | 0 | 0.00% (0/30) | 56.67% (17/30) [39.2, 72.6] | 2.00 |
| `CEGAR_LEDGER_ONLY` | 666.8 -> 344.6 | 48.26% | 100.0% | 0 | 16.67% [7.3, 33.6] | 10 | 63.33% (19/30) | 86.67% (26/30) [70.3, 94.7] | 1.37 |
| `CEGAR_HARNESS_FULL` | 666.8 -> 344.6 | 48.26% | 100.0% | 5 | 0.00% [0.0, 11.3] | 11 | 70.00% (21/30) | 93.33% (28/30) [78.7, 98.2] | 1.30 |

## 2. Experiment A: Regression Gate Ablation Study (30 Tasks, 60 Candidate Evaluations)

| Ablation Config | AST Filter | Witness Replay | Contract Ver. | Precision (%) | Recall (%) | F1 (%) | Cat. 6 Syn. Recall (%) | False Block (%) | Inconclusive | Final Resolved (%) | Median / p95 Latency (ms) |
| :--- | :---: | :---: | :---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `full_cegar_harness` | ON | ON | ON | 100.00% | 100.00% (30/30) | 100.00% | 100.0% (5/5) | 0.00% (0/30) | 5 | 100.00% (30/30) | 18.89 / 21.72 |
| `ast_filter_only` | ON | OFF | ON | 100.00% | 83.33% (25/30) | 90.91% | 0.0% (0/5) | 0.00% (0/30) | 0 | 83.33% (25/30) | 0.30 / 0.62 |
| `witness_replay_only` | OFF | ON | ON | 100.00% | 100.00% (30/30) | 100.00% | 100.0% (5/5) | 0.00% (0/30) | 5 | 100.00% (30/30) | 18.59 / 22.00 |
| `unversioned_ledger` | ON | ON | OFF | 85.71% | 100.00% (30/30) | 92.31% | 100.0% (5/5) | 16.67% (5/30) | 0 | 83.33% (25/30) | 17.64 / 20.70 |

## 3. Experiment A: Per-Category Regression & Convergence Breakdown

| Category | Tasks | Obs. Masking Unblocked Reg. | Obs. Masking Resolved | CEGAR Ledger-Only Unblocked Reg. | CEGAR Ledger-Only Resolved | CEGAR Full Unblocked Reg. | CEGAR Full Turn-1 Resolved | CEGAR Full Final Resolved | 2nd-Round Witnesses | Inconclusive |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `1_boundary_conditions` | 5 | 5/5 | 3/5 | 0/5 | 5/5 | 0/5 | 3/5 | 5/5 | 2 | 0 |
| `2_parsers_state_machines` | 5 | 5/5 | 3/5 | 0/5 | 5/5 | 0/5 | 3/5 | 5/5 | 2 | 0 |
| `3_exception_handling` | 5 | 5/5 | 4/5 | 0/5 | 5/5 | 0/5 | 4/5 | 5/5 | 1 | 0 |
| `4_multi_file_changes` | 5 | 5/5 | 4/5 | 0/5 | 4/5 | 0/5 | 4/5 | 4/5 | 2 | 0 |
| `5_feature_regressions` | 5 | 5/5 | 5/5 | 0/5 | 5/5 | 0/5 | 5/5 | 5/5 | 0 | 5 |
| `6_syntactic_variants` | 5 | 5/5 | 2/5 | 5/5 | 2/5 | 0/5 | 2/5 | 4/5 | 4 | 0 |

## 4. Experiment B: Multi-Turn Live LLM Agent Repair Loop

- **Status:** `NOT_EXECUTED_NO_CONFIG`
- **Executed:** `False`
- **Model:** `none`
- **Max Post-Compaction Turns:** `3`
- **Note:** Live LLM experiment not executed: CEGAR_LLM_API_BASE and CEGAR_LLM_MODEL environment variables are not configured.
