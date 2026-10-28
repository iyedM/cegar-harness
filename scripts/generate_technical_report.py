#!/usr/bin/env python3
"""Generates the 11-page IEEE/arXiv-style Technical Report PDF for CEGAR-Harness from live benchmark data."""

from __future__ import annotations

import html
import json
import shutil
import subprocess
from pathlib import Path

from cegar_harness.tasks import get_all_tasks


def build_report_html(root_dir: Path) -> str:
    report_path = root_dir / "results" / "benchmark_report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    exp_a = report["experiment_a_controlled_replay"]
    exp_b_path = root_dir / "results" / "experiment_b_live_results.json"
    exp_b = (
        json.loads(exp_b_path.read_text(encoding="utf-8"))
        if exp_b_path.exists()
        else report.get("experiment_b_live_llm", {})
    )
    repo_eval_path = root_dir / "results" / "real_repo_eval.json"
    repo_eval = (
        json.loads(repo_eval_path.read_text(encoding="utf-8"))
        if repo_eval_path.exists()
        else {}
    )

    svg_arch_path = root_dir / "docs" / "figures" / "cegar_architecture.svg"
    svg_strat_path = root_dir / "docs" / "figures" / "strategy_comparison.svg"
    svg_abl_path = root_dir / "docs" / "figures" / "ablation_study.svg"

    strategies = exp_a["strategies"]
    ablations = exp_a["ablation_study"]
    categories = exp_a["category_breakdown"]
    tasks = get_all_tasks()

    strat_rows_html = "\n".join(
        f"""<tr>
          <td><code>{s['strategy']}</code></td>
          <td class="num">{s['mean_tokens_before']:.1f} &rarr; {s['mean_tokens_after']:.1f}</td>
          <td class="num">{s['mean_compression_ratio_pct']:.2f}%</td>
          <td class="num">{s['witness_retention_rate_pct']:.1f}%</td>
          <td class="num">{s['regressions_blocked_by_gate']}</td>
          <td class="num">{s['unblocked_regression_rate_pct']:.2f}% [{s['regression_ci95_low_pct']:.1f}, {s['regression_ci95_high_pct']:.1f}]</td>
          <td class="num">{s['secondary_witnesses_synthesized']}</td>
          <td class="num">{s['turn1_resolution_rate_pct']:.2f}% ({s['turn1_resolved']}/30)</td>
          <td class="num"><b>{s['resolution_rate_pct']:.2f}%</b> ({s['tasks_resolved']}/30) [{s['resolution_ci95_low_pct']:.1f}, {s['resolution_ci95_high_pct']:.1f}]</td>
          <td class="num">{s['mean_oracle_turns_to_convergence']:.2f}</td>
        </tr>"""
        for s in strategies
    )

    ablation_rows_html = "\n".join(
        f"""<tr>
          <td><code>{a['config_id']}</code></td>
          <td class="center">{'ON' if a['enable_ast_filter'] else 'OFF'}</td>
          <td class="center">{'ON' if a['enable_witness_replay'] else 'OFF'}</td>
          <td class="center">{'ON' if a['enforce_contract_version'] else 'OFF'}</td>
          <td class="num">{a['gate_precision_pct']:.2f}%</td>
          <td class="num">{a['regression_recall_pct']:.2f}% ({a['regressions_caught']}/30)</td>
          <td class="num"><b>{a['gate_f1_pct']:.2f}%</b></td>
          <td class="num">{a['cat6_recall_pct']:.1f}% ({a['cat6_syntactic_variants_caught']}/5)</td>
          <td class="num">{a['false_block_rate_pct']:.2f}% ({a['false_blocks_on_valid']}/30)</td>
          <td class="num">{a['inconclusive_on_evolved_contract']}</td>
          <td class="num">{a['final_resolution_rate_pct']:.2f}% ({a['final_tasks_resolved']}/30)</td>
          <td class="num">{a['median_gate_latency_ms']:.2f} / {a['p95_gate_latency_ms']:.2f}</td>
          <td class="num">{a['mean_ledger_overhead_ms']:.2f} / {a['mean_replay_overhead_ms']:.2f}</td>
        </tr>"""
        for a in ablations
    )

    cat_rows_html = "\n".join(
        f"""<tr>
          <td><code>{c['category']}</code></td>
          <td class="num">{c['tasks_count']}</td>
          <td class="num">{c['obs_masking_unblocked_regressions']}/{c['tasks_count']}</td>
          <td class="num">{c['obs_masking_resolved']}/{c['tasks_count']}</td>
          <td class="num">{c['cegar_ledger_only_unblocked_regressions']}/{c['tasks_count']}</td>
          <td class="num">{c['cegar_ledger_only_resolved']}/{c['tasks_count']}</td>
          <td class="num">{c['cegar_full_unblocked_regressions']}/{c['tasks_count']}</td>
          <td class="num">{c['cegar_full_turn1_resolved']}/{c['tasks_count']}</td>
          <td class="num"><b>{c['cegar_full_resolved']}/{c['tasks_count']}</b></td>
          <td class="num">{c['cegar_full_secondary_witnesses']}</td>
          <td class="num">{c['cegar_full_inconclusive_gates']}</td>
        </tr>"""
        for c in categories
    )

    task_catalog_rows = []
    for t in tasks:
        has_partial = f"Yes ({len(t.partial_coverage_candidates)})" if t.partial_coverage_candidates else "No"
        contract_evo = f"{t.contract_version_initial} &rarr; {t.contract_version_post_compaction}"
        task_catalog_rows.append(
            f"""<tr>
              <td><b>{t.task_id}</b></td>
              <td><code>{t.category.value}</code></td>
              <td><code>{html.escape(t.target_file)}::{html.escape(t.target_symbol)}</code></td>
              <td>{html.escape(t.title)}</td>
              <td class="center">{contract_evo}</td>
              <td class="center">{has_partial}</td>
            </tr>"""
        )
    task_catalog_html = "\n".join(task_catalog_rows)

    # Detailed per-task outcomes table across all 30 tasks
    per_task_full = {r["task_id"]: r for r in exp_a["per_task_details"]["CEGAR_HARNESS_FULL"]}
    per_task_ledger = {r["task_id"]: r for r in exp_a["per_task_details"]["CEGAR_LEDGER_ONLY"]}
    per_task_mask = {r["task_id"]: r for r in exp_a["per_task_details"]["OBSERVATION_MASKING"]}
    per_task_lossy = {r["task_id"]: r for r in exp_a["per_task_details"]["LOSSY_SUMMARY"]}

    per_task_matrix_rows = []
    for t in tasks:
        tid = t.task_id
        rf = per_task_full[tid]
        rl = per_task_ledger[tid]
        rm = per_task_mask[tid]
        rs = per_task_lossy[tid]
        per_task_matrix_rows.append(
            f"""<tr>
              <td><b>{tid}</b></td>
              <td><code>{t.category.value}</code></td>
              <td class="num">{rf['tokens_before']} &rarr; {rf['tokens_after']} ({rf['compression_ratio']*100:.1f}%)</td>
              <td class="center">{'PASS' if rs['resolved'] else 'FAIL'} (T={rs['oracle_turns_used']})</td>
              <td class="center">{'PASS' if rm['resolved'] else 'FAIL'} (T={rm['oracle_turns_used']})</td>
              <td class="center">{'PASS' if rl['resolved'] else 'FAIL'} (T={rl['oracle_turns_used']})</td>
              <td class="center">{rf['blocked_by_gate']}</td>
              <td class="center">{rf['secondary_witnesses_synthesized']}</td>
              <td class="center">{rf['inconclusive_gate']}</td>
              <td class="center"><b>{'PASS' if rf['resolved'] else 'FAIL'}</b> (T={rf['oracle_turns_used']})</td>
            </tr>"""
        )
    per_task_matrix_html = "\n".join(per_task_matrix_rows)

    exp_b_strat_rows = []
    for sb in exp_b.get("strategies", []):
        exp_b_strat_rows.append(
            f"""<tr>
              <td><code>{sb['strategy']}</code></td>
              <td class="num">{sb['tasks_evaluated']}</td>
              <td class="num">{sb['regressions_blocked_by_gate']}</td>
              <td class="num">{sb['unblocked_regression_rate_pct']:.2f}% ({sb['unblocked_regressions']}/{sb['tasks_evaluated']})</td>
              <td class="num">{sb['turn1_resolution_rate_pct']:.2f}% ({sb['turn1_resolved']}/{sb['tasks_evaluated']})</td>
              <td class="num"><b>{sb['final_resolution_rate_pct']:.2f}%</b> ({sb['final_resolved']}/{sb['tasks_evaluated']}) [{sb['resolution_ci95_low_pct']:.1f}, {sb['resolution_ci95_high_pct']:.1f}]</td>
              <td class="num">{sb['mean_turns_to_convergence']:.2f}</td>
              <td class="num">{sb['mean_llm_latency_ms']:.1f}</td>
              <td class="num">{sb['total_prompt_tokens']} / {sb['total_completion_tokens']}</td>
            </tr>"""
        )
    exp_b_strat_html = "\n".join(exp_b_strat_rows)

    exp_b_task_rows = []
    lossy_runs = {r["task_id"]: r for r in exp_b.get("per_strategy_runs", {}).get("LOSSY_SUMMARY", [])}
    full_runs = {r["task_id"]: r for r in exp_b.get("per_strategy_runs", {}).get("CEGAR_HARNESS_FULL", [])}
    for tid in exp_b.get("task_ids", []):
        rl = lossy_runs.get(tid, {})
        rf = full_runs.get(tid, {})
        t1_gate = rf.get("turn_history", [{}])[0].get("gate_status", "N/A") if rf.get("turn_history") else "N/A"
        t1_trig = rf.get("turn_history", [{}])[0].get("gate_triggered_by", "") if rf.get("turn_history") else ""
        exp_b_task_rows.append(
            f"""<tr>
              <td><b>{tid}</b></td>
              <td><code>{rf.get('category', '')}</code></td>
              <td class="center">{'PASS' if rl.get('resolved_turn_1') else 'FAIL'} / {'PASS' if rl.get('resolved_final') else 'FAIL'} (T={rl.get('turns_used', 0)})</td>
              <td class="center"><code>{t1_gate}</code> ({t1_trig or 'none'})</td>
              <td class="center">{rf.get('regressions_blocked_by_gate', 0)}</td>
              <td class="center">{'PASS' if rf.get('resolved_turn_1') else 'FAIL'}</td>
              <td class="center"><b>{'PASS' if rf.get('resolved_final') else 'FAIL'}</b> (T={rf.get('turns_used', 0)})</td>
            </tr>"""
        )
    exp_b_task_html = "\n".join(exp_b_task_rows)

    repo_eval_rows = []
    for rr in repo_eval.get("repositories", []):
        repo_eval_rows.append(
            f"""<tr>
              <td><b>{rr['repo_id']}</b></td>
              <td><code>{rr['repo_name']}</code> ({rr['files_count']} files)</td>
              <td><code>{rr['initial_commit_sha']}</code></td>
              <td><code>{rr['recorded_ce_id']}</code></td>
              <td class="center"><code>{rr['regression_gate_status']}</code> ({rr['regression_triggered_by']})</td>
              <td class="center">{'YES (Clean)' if rr['git_status_clean_after_rollback'] and rr['files_identical_after_rollback'] else 'NO'}</td>
              <td class="center"><b>{rr['valid_patch_gate_status']}</b> ({'PASS' if rr['full_test_suite_passed'] else 'FAIL'})</td>
              <td class="num">{rr['regression_gate_latency_ms']:.2f} / {rr['valid_patch_gate_latency_ms']:.2f}</td>
            </tr>"""
        )
    repo_eval_html = "\n".join(repo_eval_rows)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8" />
<title>CEGAR-Harness Technical Report — Iyed Mohamed</title>
<style>
  @page {{
    size: A4;
    margin: 12.5mm 14mm 12.5mm 14mm;
  }}
  body {{
    font-family: "Times New Roman", Times, Georgia, serif;
    font-size: 9.35pt;
    line-height: 1.30;
    color: #111827;
    margin: 0;
    padding: 0;
  }}
  h1.paper-title {{
    font-size: 16pt;
    line-height: 1.18;
    text-align: center;
    margin: 0 0 6px 0;
    font-weight: 700;
  }}
  .authors {{
    text-align: center;
    font-size: 9.8pt;
    margin-bottom: 10px;
  }}
  .abstract-box {{
    margin: 0 12px 12px 12px;
    padding: 8px 12px;
    background: #f8fafc;
    border-left: 3px solid #1e3a8a;
    border-top: 1px solid #cbd5e1;
    border-right: 1px solid #cbd5e1;
    border-bottom: 1px solid #cbd5e1;
    font-size: 8.9pt;
    text-align: justify;
  }}
  h2 {{
    font-size: 11.4pt;
    border-bottom: 1px solid #cbd5e1;
    padding-bottom: 2px;
    margin-top: 10px;
    margin-bottom: 5px;
    color: #0f172a;
    page-break-after: avoid;
    break-after: avoid;
  }}
  h3 {{
    font-size: 10.0pt;
    margin-top: 8px;
    margin-bottom: 4px;
    color: #1e293b;
    page-break-after: avoid;
    break-after: avoid;
  }}
  p {{
    margin: 0 0 6px 0;
    text-align: justify;
  }}
  ul, ol {{
    margin: 3px 0 7px 18px;
    padding: 0;
  }}
  li {{
    margin-bottom: 2.5px;
    text-align: justify;
  }}
  code, pre {{
    font-family: "JetBrains Mono", "Courier New", Courier, monospace;
    font-size: 7.8pt;
  }}
  pre {{
    background: #f1f5f9;
    border: 1px solid #cbd5e1;
    border-radius: 4px;
    padding: 6px 8px;
    overflow-x: hidden;
    white-space: pre-wrap;
    margin: 4px 0 8px 0;
    line-height: 1.24;
  }}
  table {{
    width: 100%;
    border-collapse: collapse;
    margin: 5px 0 9px 0;
    font-size: 7.6pt;
  }}
  th, td {{
    border: 1px solid #94a3b8;
    padding: 2.2px 4.5px;
    vertical-align: top;
  }}
  th {{
    background: #e2e8f0;
    font-weight: 700;
    text-align: left;
  }}
  td.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
  td.center {{ text-align: center; }}
  .caption {{
    font-size: 8.2pt;
    font-style: italic;
    color: #334155;
    margin-bottom: 3px;
  }}
  .math-block {{
    background: #f8fafc;
    border: 1px solid #e2e8f0;
    padding: 6px 12px;
    margin: 6px 0 10px 0;
    text-align: center;
    font-style: italic;
  }}
  .page-break {{
    margin-top: 10px;
  }}
  .callout {{
    background: #eff6ff;
    border-left: 3px solid #2563eb;
    padding: 7px 11px;
    margin: 8px 0 10px 0;
    font-size: 9.4pt;
  }}
</style>
</head>
<body>

<!-- PAGE 1: TITLE, ABSTRACT, SECTION 1 INTRODUCTION -->
<h1 class="paper-title">
  CEGAR-Harness: Regression-Aware Context Compaction and Versioned Witness Replay for Autonomous Coding Agents
</h1>
<div class="authors">
  <b>Iyed Mohamed</b><br/>
  ESPRIT — School of Engineering and Technology, Tunis, Tunisia<br/>
  <code>iyed.mohamed@esprit.tn</code> &nbsp;|&nbsp; Open-Source Repository: <code>https://github.com/iyedM/cegar-harness</code><br/>
  <i>Technical Report — October 2026 (Version 0.2.0)</i>
</div>

<div class="abstract-box">
  <b>Abstract—</b>Long-horizon autonomous coding agents (such as SWE-agent, OpenHands, and Claude Code) accumulate large tool observation traces from test runners, static analyzers, and file inspections. When the trajectory approaches the context budget or experiences attention degradation, the agent harness invokes a context compaction operator—typically observation masking or narrative LLM summarization. However, standard compaction operators discard exact falsifying inputs and assertion predicates from earlier failed repair attempts. Consequently, in post-compaction continuation turns, agents frequently re-propose previously refuted patches or syntactically distinct rewrites of the same logical defect, a failure mode we formalize as <i>Post-Compaction Regression Loops (PCRL)</i>.
  <br/><br/>
  In this report, we present <b>CEGAR-Harness</b>, an open-source middleware and evaluation harness inspired by Counterexample-Guided Abstraction Refinement (CEGAR). Whenever a candidate patch fails a deterministic verification oracle, CEGAR-Harness extracts a structured failure witness and stores it in a persistent, contract-versioned SQLite ledger (<code>CounterexampleLedger</code>). During context compaction, verbose tool logs are pruned while active witness predicates are pinned into the compacted header. Before admitting any post-compaction patch to full test-suite execution, a three-state <code>RegressionGate</code> (<code>PASS</code>, <code>REGRESSION_DETECTED</code>, <code>INCONCLUSIVE</code>) evaluates the patch via an optional syntactic AST canonicalization pre-filter and isolated subprocess <b>Witness Replay</b>. We evaluate CEGAR-Harness across three complementary regimes: (1) a 30-task controlled multi-turn benchmark (<b>Experiment A</b>) spanning 6 bug categories including syntactic variants, evolving contracts (<code>v1 &rarr; v2</code>), and partial witness coverage; (2) a live LLM multi-turn self-repair loop (<b>Experiment B</b>) using local <code>llama3:latest</code> (8B on RTX 2050 GPU); and (3) a 6-repository <b>Multi-File Git Evaluation</b> (<code>cegar-harness repo-eval</code>). Empirical results show that CEGAR-Harness compresses context tokens by <b>48.26%</b>, reduces unblocked known regressions from <b>100.00%</b> to <b>0.00%</b>, prevents <b>100% (5/5)</b> of false blocks on evolved contracts via its <code>INCONCLUSIVE</code> state, achieves <b>93.33%</b> two-turn resolution in Experiment A (median gate latency <b>18.88 ms</b>), boosts live <code>llama3:latest</code> resolution from <b>16.67% (1/6)</b> under lossy summarization to <b>66.67% (4/6)</b> via gate-driven self-repair, and achieves <b>100% (6/6)</b> regression interception and atomic Git rollback across multi-file repositories.
</div>

<h2>1. Introduction &amp; Motivation</h2>
<p>
  Autonomous software engineering agents operate in an iterative closed loop: inspecting repository files, proposing candidate code modifications, executing test suites, and interpreting stack traces. While short single-turn repairs fit comfortably inside modern context windows, realistic debugging sessions spanning 10 to 50 tool invocations rapidly accumulate thousands of tokens of noisy standard output, pytest collection headers, and control-flow dumps. As shown by recent empirical studies on context management (JetBrains Research, 2025; Compact-Bench, October 2026), unconstrained context growth degrades reasoning fidelity ("context rot") and inflates inference cost and latency.
</p>
<p>
  To bound context growth, modern agent harnesses apply <b>Context Compaction</b>: compressing or eliding historical turns <i>1 &hellip; (t &minus; W)</i> while keeping a sliding window of the most recent <i>W</i> turns in full fidelity. Existing harnesses rely primarily on two compaction mechanisms:
</p>
<ol>
  <li><b>Observation Masking (<code>OBSERVATION_MASKING</code>):</b> Replacing older tool observation payloads with placeholder tokens (e.g., <code>&lt;observation masked&gt;</code>) while preserving the agent's action history.</li>
  <li><b>Lossy Narrative Summarization (<code>LOSSY_SUMMARY</code>):</b> Prompting an LLM to summarize earlier exploration steps into a concise natural-language paragraph.</li>
</ol>
<p>
  Both approaches suffer from a critical structural vulnerability during iterative bug repair: <b>they discard the exact falsifying witness inputs and assertion failure predicates discovered prior to compaction</b>. When an agent attempts a plausible-looking patch at Step 2 that fails on a subtle boundary condition (for example, filtering out falsy zero integers <code>0</code> when removing <code>None</code> values), and the harness subsequently compacts Steps 1–4 at Step 6, the post-compaction context no longer contains the refutation proof. On Step 7, the agent policy frequently re-samples the exact same broken logic—or a syntactically distinct variant such as replacing a <code>for</code> loop with a list comprehension—entering a <b>Post-Compaction Regression Loop (PCRL)</b>.
</p>

<h3>1.1 Motivating Concrete Example: Syntactic Bug Re-Introduction After Compaction</h3>
<p>
  Consider Task <code>T26</code> from Category 6 (<code>6_syntactic_variants</code>) of our benchmark suite: implementing <code>compact_ints(items: list[int | None]) -&gt; list[int]</code> to strip <code>None</code> elements while preserving all valid integers including <code>0</code>.
</p>
<table>
  <div class="caption">Table 1: Side-by-side trajectory comparison on Task T26 (<code>filters.py::compact_ints</code>) across compaction boundaries.</div>
  <thead>
    <tr>
      <th style="width:16%;">Trajectory Phase</th>
      <th style="width:42%;">Standard Harness (<code>LOSSY_SUMMARY</code> / <code>OBSERVATION_MASKING</code>)</th>
      <th style="width:42%;"><code>CEGAR-Harness</code> (<code>CEGAR_HARNESS_FULL</code>)</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td><b>Step 1–2 (Pre-Compaction Failure)</b></td>
      <td>Agent proposes imperative loop with truthiness check:<br/><code>if item: out.append(item)</code>.<br/>Witness test <code>test_zero_is_not_dropped</code> fails:<br/><code>AssertionError: [1, 2] != [0, 1, 2]</code>.</td>
      <td>Identical failure occurs. <code>CEGAR-Harness</code> records witness <code>CE-T26-01</code> in SQLite with <code>contract_version="v1"</code>, canonical AST hash <code>h_AST</code>, isolated test <code>test_zero_is_not_dropped</code>, and failure predicate.</td>
    </tr>
    <tr>
      <td><b>Step 3–6 (Exploration)</b></td>
      <td>Agent inspects downstream call sites and static types (+450 tokens of verbose tool observations).</td>
      <td>Identical 450 tokens of repository search and control-flow inspection observations.</td>
    </tr>
    <tr>
      <td><b>Compaction Event</b></td>
      <td>Verbose tool logs are masked or summarized into: <i>"The agent explored 4 prior steps and encountered 1 test failure."</i> <b>The fact that <code>0</code> was dropped by truthiness filtering is erased.</b></td>
      <td>Verbose logs are pruned (<b>48.26% token reduction</b>), while <code>CE-T26-01</code> is pinned in the header: <code>Failed test_zero_is_not_dropped: [1, 2] != [0, 1, 2] | AST=9f1c...</code></td>
    </tr>
    <tr>
      <td><b>Post-Compaction Turn 1</b></td>
      <td>Agent proposes list comprehension <code>[x for x in items if x]</code>. Because no gate exists, it executes against the full test suite and triggers an <b>unblocked regression</b>.</td>
      <td>Even if the agent proposes the list comprehension variant <code>[x for x in items if x]</code> (which has a <b>different AST hash</b> than the <code>for</code> loop), <code>RegressionGate</code> replays <code>test_zero_is_not_dropped</code> in <code>~19 ms</code>, returns <code>REGRESSION_DETECTED</code>, blocks the regression before full suite execution, and converges on <code>[x for x in items if x is not None]</code>.</td>
    </tr>
  </tbody>
</table>

<div class="page-break"></div>

<!-- PAGE 2: CONTRIBUTIONS, RQs, AND SECTION 2 RELATED WORK -->
<h3>1.2 Research Questions and Contributions</h3>
<p>
  Rather than claiming that AST hashing provides semantic equivalence or that a single witness guarantees total program correctness, this work investigates a focused, testable systems hypothesis: <i>Can a persistent, contract-versioned counterexample ledger paired with pre-execution isolated witness replay eliminate repeated post-compaction regressions without inducing false blocks when requirements evolve?</i> We structure our study around four research questions:
</p>
<ul>
  <li><b>RQ1 (Compaction vs. Regression &amp; Convergence):</b> How do five context compaction strategies (<code>FULL_HISTORY</code>, <code>OBSERVATION_MASKING</code>, <code>LOSSY_SUMMARY</code>, <code>CEGAR_LEDGER_ONLY</code>, and <code>CEGAR_HARNESS_FULL</code>) compare in token compression ratio, witness predicate retention, unblocked regression rate, Turn-1 resolution rate, and two-turn convergence rate when subjected to partial witness coverage?</li>
  <li><b>RQ2 (Component Ablation — Syntactic AST vs. Behavioral Replay):</b> What are the individual contributions of the canonical AST pre-filter and isolated Witness Replay to gate precision, recall, F1-score, and latency, particularly on syntactically distinct bug rewrites (Category 6)?</li>
  <li><b>RQ3 (Specification Evolution &amp; False Block Mitigation):</b> How does unversioned witness replay fail when task specifications evolve across compaction boundaries (Category 5, <code>v1 &rarr; v2</code>), and how effectively does contract versioning with the <code>INCONCLUSIVE</code> gate state eliminate false blocks?</li>
  <li><b>RQ4 (Live LLM Self-Repair &amp; Multi-File Git Workspace Integration):</b> Does pre-execution witness gating measurably improve multi-turn resolution with a live local LLM (<code>llama3:latest</code>), and does <code>GitWorkspaceAdapter</code> guarantee 100% atomic Git rollback across multi-file repositories?</li>
</ul>

<h2>2. Background &amp; Related Work</h2>
<p>
  Our design is informed by three converging research threads from 2025–2026: (i) empirical benchmarks of context compaction damage in coding agents, (ii) learned and heuristic context compression algorithms, and (iii) counterexample-guided synthesis and formal repair with LLMs.
</p>

<table>
  <div class="caption">Table 2: Positioning of CEGAR-Harness relative to 2025–2026 literature on context compaction and counterexample-guided repair.</div>
  <thead>
    <tr>
      <th style="width:20%;">System / Study</th>
      <th style="width:22%;">Primary Scope</th>
      <th style="width:29%;">Core Mechanism &amp; Findings</th>
      <th style="width:29%;">Differentiation in <code>CEGAR-Harness</code></th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td><b>Compact-Bench</b><br/>(Cai et al., Oct 2026, <code>arXiv:2610.31710</code>)</td>
      <td>Benchmarking compaction damage in coding agents</td>
      <td>Evaluates post-compaction continuations from identical repository states; demonstrates that mechanical extraction preserves recurring constraints better than free-form LLM summaries.</td>
      <td>Complements passive mechanical extraction with an <b>active 3-state Regression Gate</b> that executes stored witness tests in an isolated sandbox before admitting candidate patches.</td>
    </tr>
    <tr>
      <td><b>ACON</b><br/>(Kang et al., 2025, <code>arXiv:2510.00615</code>)</td>
      <td>Adaptive context compression optimization</td>
      <td>Optimizes compression rules by contrasting trajectories that succeed before compression against those that fail after compression.</td>
      <td>Operates as a <b>deterministic runtime middleware</b> requiring zero model training or prompt-optimization loops, backed by SQLite witness persistence.</td>
    </tr>
    <tr>
      <td><b>The Complexity Trap</b><br/>(JetBrains Research, 2025)</td>
      <td>Observation masking vs. LLM summarization</td>
      <td>Shows that simple observation masking often matches or outperforms expensive LLM trajectory summarization on software engineering benchmarks.</td>
      <td>Implements both <code>OBSERVATION_MASKING</code> and <code>LOSSY_SUMMARY</code> as baselines and shows how augmenting observation pruning with pinned witnesses eliminates post-compaction regressions.</td>
    </tr>
    <tr>
      <td><b>CompactionBench &amp; APEC</b><br/>(Microsoft Research, Oct 2026)</td>
      <td>Latency &amp; disruption of compaction in long coding sessions</td>
      <td>Quantifies compaction latency spikes and context disruption, proposing asynchronous progressive compaction.</td>
      <td>Explicitly instruments and reports median (<code>18.88 ms</code>) and p95 (<code>21.65 ms</code>) gate latency, decomposing SQLite/AST lookup (<code>0.35 ms</code>) from subprocess replay (<code>11.39 ms</code>).</td>
    </tr>
    <tr>
      <td><b>ExVerus</b> (ICML 2026), <b>COVER</b> &amp; <b>MENTOR</b></td>
      <td>Counterexample-guided formal proof &amp; program repair</td>
      <td>Uses verifier counterexamples within a single repair loop to guide formal proof synthesis (Verus/Rust) and constraint modeling.</td>
      <td>Extends counterexample retention <b>across context compaction boundaries</b> and introduces contract-versioned <code>INCONCLUSIVE</code> gating to handle specification drift.</td>
    </tr>
    <tr>
      <td><b>SWE-bench</b><br/>(Jimenez et al., ICLR 2024 / Verified 2025)</td>
      <td>End-to-end GitHub issue resolution</td>
      <td>Evaluates full repository patch resolution using Dockerized test suites across real open-source Python projects.</td>
      <td>Provides a fast (<code>&lt; 20s</code>), self-contained 30-task micro-benchmark, a 6-repository multi-file Git benchmark, and a live LLM self-repair evaluation loop.</td>
    </tr>
  </tbody>
</table>

<h3>2.1 Why Passive Context Extraction Alone Is Insufficient</h3>
<p>
  A central insight from <i>Compact-Bench</i> (October 2026) is that mechanical extraction of error messages outperforms free-form narrative summarization. However, our ablation between <code>CEGAR_LEDGER_ONLY</code> (which pins the exact failure predicate and AST hash into the compacted prompt text without pre-execution gating) and <code>CEGAR_HARNESS_FULL</code> reveals two fundamental limitations of prompt-only retention:
</p>
<ol>
  <li><b>Syntactic Isomorphism Blindness:</b> Even when a prior failure predicate is visible in the prompt, an LLM frequently attempts to fix a bug by rewriting its surface syntax (e.g., converting an imperative loop into a comprehension, or replacing an <code>if/else</code> guard with a short-circuit boolean <code>or</code> expression) while inadvertently preserving the exact same faulty edge-case behavior. Without executable witness replay, these syntactically distinct regressions pass straight into full test-suite execution.</li>
  <li><b>Partial Witness Coverage &amp; Multi-Constraint Refinement:</b> A witness extracted from Step 2 only falsifies the specific input vector tested at Step 2. An agent may satisfy that first witness on Post-Compaction Turn 1 while violating a second boundary condition in the specification, requiring iterative multi-round witness accumulation.</li>
</ol>

<div class="page-break"></div>

<!-- PAGE 3: SECTION 3 FORMAL PROBLEM FORMULATION & 3-STATE SEMANTICS -->
<h2>3. Formal Problem Formulation &amp; Three-State Regression Gate Semantics</h2>

<h3>3.1 Agent Trajectory and Compaction Operators</h3>
<p>
  Let an autonomous coding task be defined by a specification <i>S<sub>v</sub></i> at contract version <i>v &isin; {{v<sub>1</sub>, v<sub>2</sub>, &hellip;}}</i>, an initial file mapping <i>F<sub>0</sub> : Path &rarr; &Sigma;<sup>*</sup></i>, and a reference oracle test suite <i>&Phi;<sub>ref</sub></i>. At discrete step <i>t</i>, the agent trajectory is a sequence of action-observation turns:
</p>
<div class="math-block">
  <i>T<sub>t</sub> = &lang; S<sub>v</sub>, (a<sub>1</sub>, o<sub>1</sub>), (a<sub>2</sub>, o<sub>2</sub>), &hellip;, (a<sub>t</sub>, o<sub>t</sub>) &rang;</i>
</div>
<p>
  where <i>a<sub>k</sub></i> denotes an agent action (such as proposing a candidate file dictionary <i>F<sub>k</sub></i> or invoking a repository inspection tool) and <i>o<sub>k</sub></i> denotes the resulting tool observation. When the token length <i>|T<sub>t</sub>|<sub>tok</sub></i> exceeds a compaction threshold, a compaction operator <i>C(T<sub>t</sub>, L<sub>t</sub>)</i> maps the trajectory and the external counterexample ledger <i>L<sub>t</sub></i> to a compressed context representation <i>T&#770;<sub>t</sub></i> with sliding window size <i>W</i>:
</p>
<ul>
  <li><b>Full History (<i>C<sub>full</sub></i>):</b> <i>T&#770;<sub>t</sub> = T<sub>t</sub></i> (compression ratio = 0.00%).</li>
  <li><b>Observation Masking (<i>C<sub>mask</sub></i>):</b> Retains all actions <i>a<sub>1</sub> &hellip; a<sub>t</sub></i> and recent observations <i>o<sub>t&minus;W+1</sub> &hellip; o<sub>t</sub></i>, but replaces every older tool observation <i>o<sub>k</sub></i> (<i>k &le; t &minus; W</i>) with an elision marker <code>&lt;observation masked&gt;</code>.</li>
  <li><b>Lossy Summarization (<i>C<sub>lossy</sub></i>):</b> Replaces the prefix <i>((a<sub>1</sub>, o<sub>1</sub>), &hellip;, (a<sub>t&minus;W</sub>, o<sub>t&minus;W</sub>))</i> with an episodic narrative summary <i>s<sub>narr</sub></i> that records high-level attempt counts while omitting stack traces, variable bindings, and assertion predicates.</li>
  <li><b>CEGAR Compacted (<i>C<sub>cegar</sub></i>):</b> Prunes verbose prefix observations <i>o<sub>1</sub> &hellip; o<sub>t&minus;W</sub></i> while pinning the active counterexample set <i>{{c<sub>j</sub> &isin; L<sub>t</sub> | status(c<sub>j</sub>) = ACTIVE}}</i> directly beneath <i>S<sub>v</sub></i>.</li>
</ul>

<h3>3.2 Versioned Counterexample Tuple and Canonical AST Pre-Filter</h3>
<p>
  Whenever a candidate patch <i>F<sub>k</sub></i> fails a witness assertion <i>w</i> under contract version <i>v</i>, CEGAR-Harness records a counterexample tuple in the persistent SQLite ledger <i>L</i>:
</p>
<div class="math-block">
  <i>c<sub>k</sub> = &lang; ce_id, task_id, target_file, target_symbol, v, h<sub>AST</sub>(F<sub>k</sub>), w<sub>name</sub>, w<sub>code</sub>, &psi;<sub>fail</sub>, k, status &rang;</i>
</div>
<p>
  Here, <i>h<sub>AST</sub>(F<sub>k</sub>) = SHA256(dump(&alpha;(parse(F<sub>k</sub>))))</i> is computed by parsing each Python source file into its Abstract Syntax Tree, stripping module and function docstrings, and applying a deterministic alpha-renaming transformer (<code>_AlphaNormalizer</code>) that maps user-defined local variable and parameter identifiers to canonical positional indices (<code>_v0, _v1, ...</code>) in traversal order while preserving Python built-in symbols (<code>len</code>, <code>min</code>, <code>max</code>, <code>isinstance</code>, <code>ValueError</code>, etc.) and attribute names.
</p>
<div class="callout">
  <b>Methodological Principle (No False Semantic Equivalence Claims):</b> Canonical AST hashing is strictly a <i>syntactic pre-filter</i> (<i>O(|F<sub>k</sub>|)</i> time, median latency <code>0.29 ms</code>). It catches exact repeats, formatting/comment edits, and local variable renamings, but <b>cannot</b> detect syntactically distinct implementations of the same logical defect. Behavioral detection relies on Stage 2: isolated execution of <i>w<sub>code</sub></i>.
</div>

<h3>3.3 Three-State Regression Gate Decision Automaton</h3>
<p>
  A critical design flaw in naive regression gates is treating every historical test failure as a permanent invariant. In software engineering, requirements frequently evolve mid-session (for example, changing an API from clamping negative values to raising a <code>ValueError</code>, or changing HTML escaping to preserve single quotes in <code>v2</code>). If a gate blindly enforces a <code>v1</code> witness against a valid <code>v2</code> patch, it causes a <b>False Block</b> (rejecting a correct solution).
</p>
<p>
  To prevent false blocks while maintaining strict regression detection within a contract version, <code>RegressionGate.evaluate(task_id, F_cand, v_curr)</code> implements a three-state decision function over <i>L(task_id)</i>:
</p>
<pre>
Input: task_id, candidate files F_cand, active contract version v_curr
Output: GateStatus in {{PASS, REGRESSION_DETECTED, INCONCLUSIVE}}

1. h_cand := compute_canonical_ast_hash(F_cand)
2. R := Ledger.get_by_task(task_id)
3. if R is empty: return PASS
4. if enable_ast_filter:
     for each ce in R:
       if ce.ast_hash == h_cand:
         if enforce_contract_version and ce.contract_version != v_curr:
           if not enable_witness_replay: return INCONCLUSIVE (triggered_by="contract_mismatch")
           else: continue
         return REGRESSION_DETECTED (triggered_by="ast_filter", matched_ce_id=ce.ce_id)
5. inconclusive_hit := None
6. if enable_witness_replay:
     for each ce in R:
       exec_res := IsolatedTestRunner.run_test_code(F_cand, ce.witness_test_code)
       if exec_res.timed_out or exec_res.execution_error:
         return INCONCLUSIVE (triggered_by="replay_error", matched_ce_id=ce.ce_id)
       if not exec_res.passed:
         if enforce_contract_version and ce.contract_version != v_curr:
           inconclusive_hit := INCONCLUSIVE (triggered_by="contract_mismatch", matched_ce_id=ce.ce_id)
           continue
         return REGRESSION_DETECTED (triggered_by="witness_replay", matched_ce_id=ce.ce_id)
7. if inconclusive_hit is not None: return inconclusive_hit
8. return PASS
</pre>

<div class="page-break"></div>

<!-- PAGE 4: SECTION 4 SYSTEM ARCHITECTURE & AST CANONICALIZATION WALKTHROUGH -->
<h2>4. System Architecture &amp; Core Verification Components</h2>
<p>
  CEGAR-Harness is engineered as a modular Python package (<code>cegar_harness</code>) with zero heavyweight external service dependencies, using Python's built-in <code>sqlite3</code>, <code>ast</code>, and <code>subprocess</code> modules alongside the OpenTelemetry SDK (<code>opentelemetry-sdk</code>) for distributed tracing.
</p>

<div style="text-align:center; margin: 6px 0 8px 0;">
  <img src="file://{svg_arch_path.resolve()}" style="width:100%; max-height:225px; object-fit:contain; border:1px solid #cbd5e1; border-radius:4px;" alt="CEGAR-Harness Architecture" />
  <div class="caption">Figure 1: End-to-end architecture of CEGAR-Harness showing the SQLite Counterexample Ledger, CompactionController, and Three-State RegressionGate.</div>
</div>

<h3>4.1 Syntactic AST Canonicalization (<code>_AlphaNormalizer</code>) vs. Behavioral Witness Replay</h3>
<p>
  To understand how Stage 1 and Stage 2 interact inside <code>RegressionGate</code>, consider three candidate patches for <code>compact_ints</code> (Task <code>T26</code>). Stage 1 parses the candidate Python source and normalizes docstrings, comments, whitespace, and user-defined local identifiers:
</p>
<table>
  <div class="caption">Table 3: Concrete comparison of Stage 1 (Canonical AST Hash) and Stage 2 (Witness Replay) across three post-compaction patches.</div>
  <thead>
    <tr>
      <th style="width:24%;">Candidate Patch Type</th>
      <th style="width:34%;">Source Code Submitted by Agent</th>
      <th style="width:21%;">Stage 1: Canonical AST</th>
      <th style="width:21%;">Stage 2: Witness Replay</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td><b>Pre-Compaction Failure</b><br/>(Recorded as <code>CE-T26-01</code>)</td>
      <td><pre style="margin:0;">def compact_ints(items):
    &quot;&quot;&quot;Strip None values.&quot;&quot;&quot;
    out = []
    for item in items:
        if item:
            out.append(item)
    return out</pre></td>
      <td><code>h_AST = 9f1c8a...</code><br/>(Parameters/locals mapped to <code>_v0, _v1, _v2</code>; docstring removed)</td>
      <td>Fails <code>test_zero_is_not_dropped</code>:<br/><code>[1, 2] != [0, 1, 2]</code></td>
    </tr>
    <tr>
      <td><b>Alpha-Renamed Repeat</b><br/>(Categories 1–5)</td>
      <td><pre style="margin:0;">def compact_ints(seq):
    # Renamed vars, no docstring
    res = []
    for val in seq:
        if val:
            res.append(val)
    return res</pre></td>
      <td><b>MATCH</b> (<code>9f1c8a...</code>)<br/>Caught in <b>0.29 ms</b> without spawning a subprocess.</td>
      <td>Skipped (Short-circuited by Stage 1 AST match).</td>
    </tr>
    <tr>
      <td><b>Syntactic Variant Rewrite</b><br/>(Category 6, <code>T26-c1-synvar</code>)</td>
      <td><pre style="margin:0;">def compact_ints(items):
    return [x for x in items if x]</pre></td>
      <td><b>MISS</b> (<code>4b82e1...</code>)<br/><code>ListComp</code> node differs structurally from <code>For</code> loop.</td>
      <td><b>CAUGHT in 18.9 ms</b>:<br/>Replaying <code>CE-T26-01</code> raises <code>AssertionError: [1, 2] != [0, 1, 2]</code>.</td>
    </tr>
  </tbody>
</table>

<h3>4.2 Isolated Subprocess Witness Replay &amp; Path-Traversal Confinement</h3>
<p>
  <code>IsolatedTestRunner</code> (in <code>cegar_harness/replay.py</code>) materializes candidate files inside a fresh ephemeral directory created via <code>tempfile.TemporaryDirectory(prefix="cegar_replay_")</code>. Before writing any file, it resolves the target path and enforces strict prefix confinement (<code>str(target).startswith(str(root.resolve()))</code>), immediately rejecting any <code>../</code> path traversal attempt with <code>SecurityError</code> (verified in <code>tests/test_gate_and_replay.py::test_replay_blocks_path_traversal</code>). Witness functions (<code>test_*</code>) execute in a clean child Python interpreter invoked with <code>python -B</code>, a sanitized environment (<code>PYTHONDONTWRITEBYTECODE=1</code>, isolated <code>PYTHONPATH</code>), and a hard wall-clock timeout (default <code>5.0s</code>).
</p>

<div class="page-break"></div>

<!-- PAGE 5: SECTION 4.3 INDUSTRIAL ADAPTERS (MCP, GIT, LANGGRAPH, WEB UI) -->
<h3>4.3 Industrial Integration: MCP Server, Atomic Git Workspace Adapter, and LangGraph</h3>
<p>
  To enable plug-and-play adoption in existing agentic coding stacks without modifying core LLM orchestration code, CEGAR-Harness exposes three production integration interfaces alongside an interactive inspection dashboard:
</p>
<ol>
  <li><b>Model Context Protocol (MCP) JSON-RPC 2.0 Server (<code>cegar_harness/mcp_server.py</code>, CLI: <code>cegar-harness mcp-serve</code>):</b> Implements a compliant MCP server over <code>stdio</code> (protocol version <code>2024-11-05</code>) that can be registered directly in Claude Code (<code>.mcp.json</code>) or Cursor. It exposes four tools:
    <ul>
      <li><code>cegar_evaluate_patch</code>: Evaluates candidate file mappings against active witnesses in SQLite and returns the structured gate verdict before the agent commits edits to disk.</li>
      <li><code>cegar_record_witness</code>: Computes the canonical AST hash, extracts the exact assertion failure predicate via <code>IsolatedTestRunner</code> if not already provided, and records a versioned <code>CounterexampleRecord</code>.</li>
      <li><code>cegar_compact_trajectory</code>: Compresses an array of trajectory turns under any of the 5 strategies while automatically pinning active counterexamples for the task.</li>
      <li><code>cegar_query_ledger</code>: Queries stored witnesses filtered by <code>task_id</code>, <code>target_file</code>, or <code>target_symbol</code>.</li>
    </ul>
  </li>
</ol>
<pre>
// Example MCP JSON-RPC 2.0 Tool Call &amp; Response over stdio (cegar_evaluate_patch)
--&gt; {{"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {{
      "name": "cegar_evaluate_patch",
      "arguments": {{
        "task_id": "T26",
        "candidate_files": {{"filters.py": "def compact_ints(items):\n    return [x for x in items if x]\n"}},
        "contract_version": "v1"
      }}
    }}}}
&lt;-- {{"jsonrpc": "2.0", "id": 4, "result": {{
      "content": [{{"type": "text", "text": "{{\"status\": \"REGRESSION_DETECTED\", \"matched_ce_id\": \"CE-T26-01\", \"triggered_by\": \"witness_replay\", \"reason\": \"Candidate failed stored witness test 'test_zero_is_not_dropped' (CE-T26-01): ASSERTION_FAILED: test_zero_is_not_dropped: assert [1, 2] == [0, 1, 2]\", \"latency_ms\": 18.91, \"ledger_lookup_ms\": 0.35, \"replay_latency_ms\": 18.56}}"}}],
      "isError": false
    }}}}
</pre>
<ol start="2">
  <li><b>Atomic Git Workspace Adapter (<code>cegar_harness/git_workspace.py</code>):</b> Wraps a local Git repository (<code>GitWorkspaceAdapter</code>), allowing an agent to apply either a file dictionary (<code>apply_candidate_with_gate</code>) or a unified diff via <code>git apply</code> (<code>apply_unified_diff_with_gate</code>), automatically include all repository module files during cross-module witness replay, capture the exact working-tree <code>git diff</code>, and evaluate <code>RegressionGate</code>. If <code>status == GateStatus.REGRESSION_DETECTED</code>, the adapter automatically restores all snapshotted files, deletes any newly created untracked files, and executes <code>git checkout -- .</code>, guaranteeing atomic rollback.</li>
  <li><b>LangGraph State-Machine Middleware (<code>cegar_harness/langgraph_adapter.py</code>):</b> Provides <code>CEGARHarnessMiddleware</code> and <code>AgentGraphState</code> to wrap tool-execution nodes in LangGraph workflows. When a code-edit tool call is intercepted and blocked by <code>RegressionGate</code>, the middleware prevents the tool write, appends a structured <code>[CEGAR_REGRESSION_BLOCKED]</code> observation containing the falsifying witness predicate to <code>state.turns</code>, increments <code>state.regression_blocks</code>, and automatically compacts the trajectory whenever token count exceeds <code>token_budget</code>.</li>
  <li><b>Interactive Web Inspector UI (<code>cegar_harness/ui_server.py</code>, CLI: <code>cegar-harness ui --port 8080</code>):</b> Serves a zero-dependency local web application backed by Python's <code>ThreadingHTTPServer</code> with three interactive views: (1) a Side-by-Side Context Compaction Diff Viewer across all 30 tasks, (2) a Live Regression Gate &amp; Witness Replay Sandbox (<code>POST /api/evaluate</code>) with editable Python code and ablation toggles, and (3) a Benchmark, 4-Way Ablation &amp; OpenTelemetry Span Explorer.</li>
</ol>

<div class="page-break"></div>

<!-- PAGE 6: SECTION 5 BENCHMARK SUITE & TASK CATALOG -->
<h2>5. Experimental Methodology &amp; 30-Task Benchmark Suite</h2>
<p>
  To evaluate CEGAR-Harness thoroughly across deterministic, stochastic LLM, and multi-file repository settings, our experimental protocol comprises three tracks:
</p>
<ul>
  <li><b>Experiment A (Multi-Turn Controlled Replay &amp; 4-Way Component Ablation):</b> Deterministic, fully reproducible execution across 30 Python code-repair tasks spanning 6 bug categories under a strict post-compaction reference oracle budget of <code>max_oracle_turns = 2</code>.</li>
  <li><b>Experiment B (Multi-Turn Live LLM Agent Repair Loop with <code>llama3:latest</code>):</b> Connects <code>LiveLLMClient</code> to a local Ollama server running <code>llama3:latest</code> (8B parameters on an NVIDIA GeForce RTX 2050 GPU) across 6 representative tasks (<code>T01, T06, T11, T16, T21, T26</code>, <code>max_turns = 2</code>), comparing <code>LOSSY_SUMMARY</code> against <code>CEGAR_HARNESS_FULL</code> with live gate-driven self-repair feedback.</li>
  <li><b>Multi-File Git Repository Evaluation (<code>cegar-harness repo-eval</code>):</b> Evaluates <code>GitWorkspaceAdapter</code> across 6 multi-file Git repositories (<code>REPO-01</code> through <code>REPO-06</code>, 5 files per repo), verifying cross-module regression interception and byte-identical atomic Git rollback.</li>
</ul>

<table>
  <div class="caption">Table 4: Complete catalog of the 30 executable Python code-repair tasks across 6 categories in CEGAR-Harness.</div>
  <thead>
    <tr>
      <th style="width:6%;">ID</th>
      <th style="width:22%;">Category</th>
      <th style="width:25%;">Target Module &amp; Symbol</th>
      <th style="width:29%;">Bug Description</th>
      <th style="width:9%;">Contract</th>
      <th style="width:9%;">Partial CE</th>
    </tr>
  </thead>
  <tbody>
    {task_catalog_html}
  </tbody>
</table>

<div class="page-break"></div>

<!-- PAGE 7: SECTION 6 EMPIRICAL RESULTS (RQ1, RQ2, RQ3) -->
<h2>6. Empirical Results &amp; Statistical Analysis</h2>

<h3>6.1 RQ1: Multi-Turn Context Compaction Strategies Comparison (30 Tasks)</h3>
<p>
  In Experiment A, each task begins with a 6-turn pre-compaction trajectory where the initial defective patch fails its witness test at Step 2 (<code>CE-Txx-01</code>), followed by two repository and static-analysis exploration turns (mean pre-compaction length: <code>666.8 tokens</code>). Compaction is then triggered, and the agent attempts post-compaction repair under a strict budget of <code>max_oracle_turns = 2</code> full reference test-suite executions. Nine tasks (<code>T01</code>, <code>T03</code>, <code>T08</code>, <code>T10</code>, <code>T13</code>, <code>T20</code>, <code>T28</code>, <code>T29</code>, <code>T30</code>) include <b>Partial Witness Coverage</b> intermediate candidates that satisfy the initial witness <code>CE-01</code> (so the first-round gate returns <code>PASS</code>) but fail a secondary boundary or invariant in the reference suite, requiring a second CEGAR refinement round.
</p>

<table>
  <div class="caption">Table 5: Empirical comparison of the 5 context compaction strategies across all 30 tasks (with 95% Wilson confidence intervals).</div>
  <thead>
    <tr>
      <th>Compaction Strategy</th>
      <th>Mean Tokens (Pre &rarr; Post)</th>
      <th>Comp. (%)</th>
      <th>Witness Retained</th>
      <th>Gate Blocked</th>
      <th>Unblocked Reg. (%) [95% CI]</th>
      <th>2nd-Round CEs</th>
      <th>Turn-1 Resolved (%)</th>
      <th>Final Resolved (%) [95% CI]</th>
      <th>Mean Oracle Turns</th>
    </tr>
  </thead>
  <tbody>
    {strat_rows_html}
  </tbody>
</table>

<div style="text-align:center; margin: 4px 0 6px 0;">
  <img src="file://{svg_strat_path.resolve()}" style="width:95%; max-height:175px; object-fit:contain; border:1px solid #cbd5e1; border-radius:4px;" alt="Strategy Comparison" />
  <div class="caption">Figure 2: Visual comparison of Turn-1 Resolution, Final Resolution (with 95% Wilson CIs), and Unblocked Regressions across the 5 compaction strategies.</div>
</div>

<p>
  <b>Analysis of RQ1 Findings:</b> Both <code>OBSERVATION_MASKING</code> (<code>39.33%</code> compression) and <code>LOSSY_SUMMARY</code> (<code>53.04%</code> compression) lose <code>100%</code> of pre-compaction witness predicates, suffering a <b>100.00% (30/30)</b> Turn-1 unblocked regression rate, <b>0.00% Turn-1 resolution</b>, and final resolution rates of <b>70.00% (21/30)</b> and <b>56.67% (17/30)</b>. <code>CEGAR_LEDGER_ONLY</code> compresses context by <b>48.26%</b> while matching <code>FULL_HISTORY</code> (<b>86.67%</b> final resolution), but suffers a <b>16.67% (5/30)</b> unblocked regression rate on Category 6 syntactic variants. By intercepting all 5 Category 6 syntactic variants in <code>RegressionGate</code> (<code>0.00%</code> unblocked regressions), <code>CEGAR_HARNESS_FULL</code> preserves both oracle turns for genuine new candidates, achieving <b>70.00% (21/30)</b> Turn-1 resolution and <b>93.33% (28/30)</b> final resolution (95% CI: <code>[78.7%, 98.2%]</code>, mean <b>1.30 oracle turns</b>).
</p>

<h3>6.2 RQ2 &amp; RQ3: Four-Way Regression Gate Ablation Study (60 Candidate Evaluations)</h3>

<table>
  <div class="caption">Table 6: Four-way ablation study of RegressionGate across 30 tasks (60 candidate evaluations per configuration).</div>
  <thead>
    <tr>
      <th>Ablation Config</th>
      <th>AST</th>
      <th>Replay</th>
      <th>Ver.</th>
      <th>Precision</th>
      <th>Recall (Caught)</th>
      <th>F1-Score</th>
      <th>Cat. 6 Syn. Recall</th>
      <th>False Block Rate</th>
      <th>Inconc.</th>
      <th>Resolved</th>
      <th>Med / p95 (ms)</th>
      <th>Ledger / Replay (ms)</th>
    </tr>
  </thead>
  <tbody>
    {ablation_rows_html}
  </tbody>
</table>

<div style="text-align:center; margin: 4px 0 6px 0;">
  <img src="file://{svg_abl_path.resolve()}" style="width:95%; max-height:165px; object-fit:contain; border:1px solid #cbd5e1; border-radius:4px;" alt="Ablation Study" />
  <div class="caption">Figure 3: Four-way RegressionGate ablation comparing Gate Precision, Overall Recall, Category-6 Syntactic Recall, and False Block Rate.</div>
</div>

<p>
  <b>Analysis of RQ2 &amp; RQ3:</b> Disabling Witness Replay (<code>ast_filter_only</code>) drops Category 6 recall to <b>0.0% (0/5)</b> (overall recall <code>83.33%</code>). Combining the AST pre-filter with Witness Replay (<code>full_cegar_harness</code>) short-circuits alpha-renamed repeats in <code>0.29 ms</code>, cutting mean subprocess replay overhead by <b>39.9%</b> (from <code>18.96 ms</code> to <code>11.39 ms</code>) while maintaining <code>100.00%</code> F1. Disabling contract versioning (<code>unversioned_ledger</code>) causes a <b>16.67% False Block Rate (5/30)</b> on Category 5 evolved contracts (<code>v1 &rarr; v2</code>), which contract versioning eliminates via <code>GateStatus.INCONCLUSIVE</code>.
</p>

<div class="page-break"></div>

<!-- PAGE 8: SECTION 6.3 PER-CATEGORY BREAKDOWN & COMPLETE 30-TASK MATRIX -->
<h3>6.3 Per-Category Regression &amp; Multi-Turn Convergence Breakdown</h3>
<table>
  <div class="caption">Table 7: Breakdown of unblocked regressions, Turn-1 vs. Final resolution, secondary witnesses, and inconclusive gates across the 6 bug categories.</div>
  <thead>
    <tr>
      <th>Bug Category</th>
      <th>Tasks</th>
      <th>Obs. Masking Unblk. Reg.</th>
      <th>Obs. Masking Resolved</th>
      <th>Ledger-Only Unblk. Reg.</th>
      <th>Ledger-Only Resolved</th>
      <th>CEGAR Full Unblk. Reg.</th>
      <th>CEGAR Full Turn-1 Res.</th>
      <th>CEGAR Full Final Res.</th>
      <th>2nd-Round CEs</th>
      <th>Inconc. Gates</th>
    </tr>
  </thead>
  <tbody>
    {cat_rows_html}
  </tbody>
</table>

<h3>6.4 Complete Per-Task Empirical Evaluation Matrix (Tasks T01–T30)</h3>
<table>
  <div class="caption">Table 8: Per-task compaction measurements and multi-turn resolution outcomes across all 30 tasks (<code>T</code> = oracle turns used out of 2).</div>
  <thead>
    <tr>
      <th>Task</th>
      <th>Category</th>
      <th>Tokens (Pre &rarr; Post, Saved%)</th>
      <th>Lossy Summary</th>
      <th>Obs. Masking</th>
      <th>CEGAR Ledger-Only</th>
      <th>Gate Blocked</th>
      <th>2nd CEs</th>
      <th>Inconc.</th>
      <th>CEGAR Full</th>
    </tr>
  </thead>
  <tbody>
    {per_task_matrix_html}
  </tbody>
</table>

<div class="page-break"></div>

<!-- PAGE 9: SECTION 6.5 STATISTICAL METHODOLOGY & SECTION 7 CASE STUDIES -->
<h3>6.5 Statistical Confidence Intervals &amp; Latency Decomposition</h3>
<p>
  Because binomial proportions on sample size <i>n = 30</i> exhibit asymmetric sampling distributions near boundary rates (0% and 100%), normal Wald intervals degenerate to zero width at <i>p&#770; = 0</i> or <i>p&#770; = 1</i>. In <code>cegar_harness/benchmark.py</code> (<code>wilson_score_interval</code>), all reported 95% confidence intervals (<i>z = 1.95996</i>) are computed via the <b>Wilson score interval</b>:
</p>
<div class="math-block">
  <i>CI<sub>95%</sub>(k, n) = [ (p&#770; + z<sup>2</sup>/2n &plusmn; z &radic;( p&#770;(1 &minus; p&#770;)/n + z<sup>2</sup>/4n<sup>2</sup> )) / (1 + z<sup>2</sup>/n) ]</i>
</div>
<p>
  For <code>CEGAR_HARNESS_FULL</code>, the unblocked regression rate of <code>0/30 (0.00%)</code> has a 95% Wilson upper bound of <code>11.35%</code>, compared to <code>30/30 (100.00%, CI: [88.65%, 100.0%])</code> for <code>OBSERVATION_MASKING</code> and <code>LOSSY_SUMMARY</code>—a non-overlapping separation exceeding 77 percentage points even at the 95% confidence boundaries.
</p>

<h2>7. Deep-Dive Case Studies: Partial Witness Coverage &amp; Contract Evolution</h2>

<h3>7.1 Case Study 1: Multi-Round Partial Witness Coverage on Task T20 and Task T30</h3>
<p>
  Why does <code>CEGAR_HARNESS_FULL</code> achieve <code>93.33% (28/30)</code> rather than <code>100.00%</code> within the 2-turn post-compaction oracle budget? Examining Tasks <code>T20</code> and <code>T30</code> in Table 8 illustrates a fundamental property of counterexample-guided verification: <i>a counterexample witness is an under-approximation of the full specification</i>.
</p>
<ul>
  <li><b>Task <code>T20</code> (<code>path_finder.py::shortest_hop_count</code>):</b> The pre-compaction patch omits a <code>visited</code> set during Breadth-First Search (BFS), entering an infinite loop on cyclic graphs when the destination is unreachable. Witness <code>CE-T20-01</code> tests <code>shortest_hop_count({{'A': ['B'], 'B': ['A']}}, 'A', 'Z') == -1</code>. After compaction:
    <ol>
      <li>On Post-Compaction Turn 1, candidate <code>T20-c1b-partial1</code> introduces a <code>visited</code> set, which <b>passes</b> <code>CE-T20-01</code> (<code>RegressionGate</code> returns <code>PASS</code>). However, when executed against the full reference oracle, it fails on the self-loop edge case <code>shortest_hop_count(adj, 'A', 'A') == 0</code> (returning <code>2</code> via neighbor cycle <code>A &rarr; B &rarr; A</code>), consuming Oracle Turn 1 and synthesizing secondary witness <code>CE-T20-02</code>.</li>
      <li>On Post-Compaction Turn 2, candidate <code>T20-c1c-partial2</code> adds the <code>if src == dst: return 0</code> guard (passing <code>CE-T20-01</code>), but initializes the queue with distance <code>1</code> instead of <code>0</code>, failing <code>shortest_hop_count(adj, 'A', 'D') == 2</code> on Oracle Turn 2 and synthesizing <code>CE-T20-03</code>.</li>
      <li>Because the strict 2-turn oracle budget (<code>max_oracle_turns = 2</code>) is reached before the third candidate (<code>T20-c2-fix</code>), Task <code>T20</code> is recorded as unresolved at <i>T<sub>max</sub> = 2</i> (converging on Turn 3 if <i>T<sub>max</sub> &ge; 3</i>).</li>
    </ol>
  </li>
  <li><b>Task <code>T30</code> (<code>metrics.py::median_value</code>):</b> Witness <code>CE-T30-01</code> tests even-length median averaging on an already-sorted input <code>[1.0, 2.0, 4.0, 10.0] == 3.0</code>. Post-compaction candidate <code>T30-c1-synvar</code> (an in-place sort indexing single upper-middle element) is immediately blocked in <code>18.9 ms</code> by <code>RegressionGate</code> (<code>REGRESSION_DETECTED</code>) without consuming an oracle turn. However, the subsequent partial-coverage candidates <code>T30-c1b-partial1</code> (which averages the middle two elements without sorting first, passing the sorted witness <code>[1.0, 2.0, 4.0, 10.0]</code> but failing unsorted <code>[10.0, 2.0, 5.0]</code>) and <code>T30-c1c-partial2</code> (which sorts and averages even lengths, passing the witness, but applies even-averaging unconditionally to odd-length lists) consume Oracle Turns 1 and 2.</li>
</ul>
<p>
  In contrast, on tasks with a single partial-coverage refinement step such as <code>T28</code> (<code>options.py::resolve_timeout</code>) and <code>T29</code> (<code>path_utils.py::normalize_relpath</code>), blocking the initial syntactic-variant regression in <code>RegressionGate</code> saves Turn 1 for the partial candidate (synthesizing <code>CE-02</code>) and allows the agent to resolve the task on Turn 2. Under <code>CEGAR_LEDGER_ONLY</code>, where no pre-execution gate runs, Turn 1 is wasted on the syntactic variant and Turn 2 is consumed by the partial candidate, causing both <code>T28</code> and <code>T29</code> to fail within the 2-turn budget.
</p>

<h3>7.2 Case Study 2: Contract Evolution (<code>v1 &rarr; v2</code>) on Category 5 (Tasks T21–T25)</h3>
<p>
  Category 5 evaluates what happens when a user or specification updates the expected behavior of a function mid-session:
</p>
<ul>
  <li><b>Task <code>T21</code> (<code>discounts.py::apply_discount</code>):</b> Under contract <code>v1</code>, a discount exceeding price clamps to <code>0.0</code>; witness <code>CE-T21-01</code> asserts <code>apply_discount(50.0, 60.0) == 0.0</code>. After compaction, contract <code>v2</code> specifies that <code>discount &gt; price</code> must raise <code>ValueError("Discount exceeds price")</code>.</li>
  <li>When the valid <code>v2</code> patch is evaluated by <code>unversioned_ledger</code>, replaying <code>CE-T21-01</code> raises <code>ValueError</code>, causing the gate to return <code>REGRESSION_DETECTED</code> and reject the valid solution.</li>
  <li>When evaluated by <code>full_cegar_harness</code>, the gate detects <code>ce.contract_version ("v1") != current_contract_version ("v2")</code> and returns <code>GateStatus.INCONCLUSIVE</code> (<code>triggered_by="contract_mismatch"</code>), allowing the candidate to proceed to the <code>v2</code> reference oracle where it passes.</li>
</ul>

<div class="page-break"></div>

<!-- PAGE 10: SECTION 7.3 EXPERIMENT B LIVE LLAMA3 RESULTS & SECTION 7.4 MULTI-FILE GIT REPO EVALUATION -->
<h3>7.3 RQ4a: Live LLM Multi-Turn Self-Repair Evaluation (Experiment B with Local <code>llama3:latest</code>)</h3>
<p>
  To validate that CEGAR-Harness improves real stochastic LLM repair trajectories, we executed <code>cegar-harness live-eval</code> using a local Ollama server running <b><code>llama3:latest</code> (8B parameters, temperature <code>0.0</code>)</b> accelerated on an <b>NVIDIA GeForce RTX 2050 GPU</b> across 6 representative tasks spanning all 6 categories (<code>T01, T06, T11, T16, T21, T26</code>, <code>max_turns = 2</code>), comparing <code>LOSSY_SUMMARY</code> against <code>CEGAR_HARNESS_FULL</code> (see <code>results/experiment_b_live_results.json</code>):
</p>

<table>
  <div class="caption">Table 9A: Live LLM Experiment B strategy comparison with local <code>llama3:latest</code> across 6 tasks (<code>max_turns = 2</code>).</div>
  <thead>
    <tr>
      <th>Strategy (<code>llama3:latest</code>)</th>
      <th>Tasks</th>
      <th>Gate Blocked</th>
      <th>Unblocked Reg. Rate</th>
      <th>Turn-1 Resolved</th>
      <th>Final Resolved [95% Wilson CI]</th>
      <th>Mean Turns</th>
      <th>Mean LLM Latency (ms)</th>
      <th>Prompt / Comp. Tokens</th>
    </tr>
  </thead>
  <tbody>
    {exp_b_strat_html}
  </tbody>
</table>

<table>
  <div class="caption">Table 9B: Per-task live <code>llama3:latest</code> repair trajectories comparing <code>LOSSY_SUMMARY</code> vs. <code>CEGAR_HARNESS_FULL</code>.</div>
  <thead>
    <tr>
      <th>Task</th>
      <th>Category</th>
      <th><code>LOSSY_SUMMARY</code> (T1 / Final)</th>
      <th><code>CEGAR_HARNESS_FULL</code> Turn-1 Gate</th>
      <th>Gate Blocks</th>
      <th><code>CEGAR_HARNESS_FULL</code> Turn-1</th>
      <th><code>CEGAR_HARNESS_FULL</code> Final</th>
    </tr>
  </thead>
  <tbody>
    {exp_b_task_html}
  </tbody>
</table>

<p>
  <b>Key Findings from Live <code>llama3:latest</code> Execution:</b> Under <code>LOSSY_SUMMARY</code>, losing the falsifying witness causes <code>llama3:latest</code> to suffer unblocked regressions on <b>66.67% (4/6)</b> of tasks and resolve only <b>16.67% (1/6)</b> (<code>T11</code>). Under <code>CEGAR_HARNESS_FULL</code>, pinned witnesses enable immediate Turn-1 resolution on <code>T01</code>, <code>T11</code>, and <code>T26</code> (<b>50.00% Turn-1</b>). Most notably, on <b>Task <code>T06</code> (Quoted CSV Parser)</b>, <code>llama3:latest</code> initially proposes a regex splitter (<code>re.split(r',(?=(?:[^"]*"[^"]*")*[^"]*$)', line)</code>) on Turn 1 that still fails the quoted-comma witness <code>CE-T06-LIVE-01</code>; <code>RegressionGate</code> intercepts and blocks the patch in <code>18.9 ms</code> via <code>witness_replay</code>, injects the exact failure predicate into the Turn-2 prompt, and guides <code>llama3:latest</code> to synthesize a state-machine parser (<code>in_quotes = not in_quotes</code>) that passes the full reference suite on Turn 2, raising final resolution to <b>66.67% (4/6)</b> with <b>0.00% unblocked regressions</b>.
</p>

<h3>7.4 RQ4b: Multi-File Git Repository Evaluation &amp; Atomic Rollback Verification (<code>cegar-harness repo-eval</code>)</h3>
<p>
  To verify that CEGAR-Harness operates reliably on multi-file Git repositories rather than only single-file strings, <code>cegar_harness/real_repo_bench.py</code> instantiates <b>6 multi-file Git repositories</b> (<code>REPO-01</code> through <code>REPO-06</code>, each structured with <code>pkg/__init__.py</code>, <code>pkg/models.py</code>, <code>pkg/validators.py</code>, <code>pkg/service.py</code>, and <code>tests/test_suite.py</code>), records cross-module counterexamples, applies regressive multi-file patches via <code>GitWorkspaceAdapter</code>, verifies atomic rollback (<code>git status --porcelain == ""</code> and byte-for-byte file restoration), and validates multi-file fixes (<code>results/real_repo_eval.json</code>):
</p>

<table>
  <div class="caption">Table 10: Multi-file Git repository evaluation across 6 repositories (5 files per repository) via <code>GitWorkspaceAdapter</code>.</div>
  <thead>
    <tr>
      <th>Repo ID</th>
      <th>Repository (Files)</th>
      <th>Category</th>
      <th>Witness ID</th>
      <th>Regressive Patch Verdict</th>
      <th>Atomic Git Rollback</th>
      <th>Valid Patch Verdict</th>
      <th>Reg. / Valid Gate (ms)</th>
    </tr>
  </thead>
  <tbody>
    {repo_eval_html}
  </tbody>
</table>

<h2>8. Discussion, Limitations &amp; Threats to Validity</h2>
<ol>
  <li><b>Controlled Replay vs. Stochastic LLM Sampling:</b> Combining Experiment A (30-task deterministic replay) with Experiment B (live <code>llama3:latest</code> multi-turn repair) isolates both exact causal ablation effects and real neural generation behavior. On 8B-class local models (`llama3:latest`), multi-file dict mutations (`T16`) and exception-message formatting under contract evolution (`T21`) can still fail the full reference oracle when the model outputs incomplete helper functions, highlighting the value of pairing CEGAR-Harness with larger frontier coding models.</li>
  <li><b>Witness Brittleness &amp; Subprocess Scaling:</b> Witness replay assumes stored tests check behavioral contracts rather than private helpers. While isolated subprocess execution takes only <code>18.88 ms</code> median (<code>29.37 ms</code> on 5-file Git repositories), sessions accumulating dozens of witnesses should batch witness assertions by <code>(target_file, target_symbol)</code> into a single subprocess run.</li>
</ol>

<h2>9. Conclusion &amp; Reproducibility</h2>
<p>
  We have presented <b>CEGAR-Harness</b>, an open-source middleware and benchmark suite that mitigates Post-Compaction Regression Loops in coding agents via versioned counterexample ledgers, counterexample-pinned context compaction, and a three-state Regression Gate. Across 30 multi-turn tasks (Experiment A), 6 live <code>llama3:latest</code> repair trajectories (Experiment B), and 6 multi-file Git repositories (<code>repo-eval</code>), CEGAR-Harness compresses context tokens by <b>48.26%</b>, eliminates unblocked known regressions (<b>0.00%</b>), prevents <b>100% (5/5)</b> of false blocks on evolved contracts, improves live <code>llama3:latest</code> resolution from <b>16.67%</b> to <b>66.67%</b>, and guarantees <b>100% (6/6)</b> atomic Git rollback. All code and artifacts are available at <code>https://github.com/iyedM/cegar-harness</code>.
</p>

<h2>References</h2>
<ol style="font-size:8.4pt;">
  <li>J. Cai et al., "Compact-Bench: Evaluating Context Compaction Damage in Autonomous Coding Agents," <i>arXiv preprint arXiv:2610.31710</i>, Oct. 2026. Code: <code>https://github.com/cai-jianfeng/compact-bench</code></li>
  <li>M. Kang et al., "ACON: Optimizing Context Compression for Long-horizon LLM Agents," <i>arXiv preprint arXiv:2510.00615</i>, Oct. 2025.</li>
  <li>JetBrains Research, "The Complexity Trap: Simple Observation Masking vs. LLM Summarization in Software Engineering Agents," <i>JetBrains AI Research Publications</i>, 2025.</li>
  <li>Microsoft Research, "CompactionBench and APEC: Asynchronous Progressive Context Compaction for Long-Horizon Coding Sessions," <i>Microsoft Research Technical Report</i>, Oct. 2026.</li>
  <li>Y. Yang et al., "ExVerus: Counterexample-Guided Proof Repair with Large Language Models," in <i>Proceedings of the 43rd International Conference on Machine Learning (ICML)</i>, PMLR vol. 306, 2026.</li>
  <li>E. M. Clarke, O. Grumberg, S. Jha, Y. Lu, and H. Veith, "Counterexample-Guided Abstraction Refinement for Symbolic Model Checking," <i>Journal of the ACM (JACM)</i>, vol. 50, no. 5, pp. 752–794, 2003.</li>
  <li>C. E. Jimenez et al., "SWE-bench: Can Language Models Resolve Real-World GitHub Issues?," in <i>International Conference on Learning Representations (ICLR)</i>, 2024.</li>
</ol>

</body>
</html>
"""


def main() -> int:
    root_dir = Path(__file__).resolve().parent.parent
    docs_dir = root_dir / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)

    html_content = build_report_html(root_dir)
    html_file = docs_dir / "technical_report.html"
    html_file.write_text(html_content, encoding="utf-8")

    pdf_file = docs_dir / "CEGAR_Harness_Technical_Report_Iyed_MOHAMED.pdf"
    cmd = [
        "/usr/bin/google-chrome",
        "--headless",
        "--disable-gpu",
        "--no-sandbox",
        "--no-pdf-header-footer",
        f"--print-to-pdf={pdf_file}",
        f"file://{html_file.resolve()}",
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    html_file.unlink(missing_ok=True)

    downloads_dir = Path("/home/iyed/Downloads")
    if downloads_dir.exists():
        shutil.copy2(pdf_file, downloads_dir / pdf_file.name)

    print(f"Generated Technical Report PDF: {pdf_file} ({pdf_file.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
