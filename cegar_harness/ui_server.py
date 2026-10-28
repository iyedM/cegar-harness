"""Interactive Web Dashboard ('CEGAR Trajectory & Compaction Inspector UI') served via `cegar-harness ui`."""

from __future__ import annotations

import json
import urllib.parse
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional

from cegar_harness.ast_filter import compute_canonical_ast_hash
from cegar_harness.benchmark import _build_pre_compaction_turns, run_experiment_a
from cegar_harness.compactor import CompactionController
from cegar_harness.gate import RegressionGate
from cegar_harness.ledger import CounterexampleLedger
from cegar_harness.models import CompactionStrategy, CounterexampleRecord
from cegar_harness.replay import IsolatedTestRunner
from cegar_harness.tasks import get_all_tasks, get_tasks_by_id


class CEGARInspectorApp:
    """Backend state and API handler for the CEGAR Trajectory & Compaction Inspector UI."""

    def __init__(self, results_dir: str | Path = "results") -> None:
        self.results_dir = Path(results_dir)
        self.results_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.results_dir / "counterexamples.sqlite"
        self.report_path = self.results_dir / "benchmark_report.json"
        self.jsonl_path = self.results_dir / "telemetry_events.jsonl"

        if not self.report_path.exists() or not self.db_path.exists():
            run_experiment_a(output_dir=self.results_dir)

        self.tasks = get_all_tasks()
        self.tasks_by_id = get_tasks_by_id()
        self.runner = IsolatedTestRunner(timeout_seconds=5.0)
        self.compactor = CompactionController(sliding_window_turns=2)

    def get_overview_payload(self) -> Dict[str, Any]:
        report = json.loads(self.report_path.read_text(encoding="utf-8"))
        events: List[Dict[str, Any]] = []
        if self.jsonl_path.exists():
            lines = self.jsonl_path.read_text(encoding="utf-8").splitlines()
            for ln in lines[-80:]:
                if ln.strip():
                    events.append(json.loads(ln))

        task_summaries = []
        for t in self.tasks:
            candidates_map = {
                "pre_compaction": {
                    "patch_id": t.pre_compaction_failed_patch.patch_id,
                    "description": t.pre_compaction_failed_patch.description,
                    "contract_version": t.pre_compaction_failed_patch.contract_version,
                    "files": t.pre_compaction_failed_patch.files,
                },
                "c1_regression": {
                    "patch_id": t.post_compaction_candidates[0].patch_id,
                    "description": t.post_compaction_candidates[0].description,
                    "contract_version": t.post_compaction_candidates[0].contract_version,
                    "files": t.post_compaction_candidates[0].files,
                },
                "c2_valid_fix": {
                    "patch_id": t.post_compaction_candidates[1].patch_id,
                    "description": t.post_compaction_candidates[1].description,
                    "contract_version": t.post_compaction_candidates[1].contract_version,
                    "files": t.post_compaction_candidates[1].files,
                },
            }
            if t.partial_coverage_candidates:
                pc = t.partial_coverage_candidates[0]
                candidates_map["c_partial"] = {
                    "patch_id": pc.patch_id,
                    "description": pc.description,
                    "contract_version": pc.contract_version,
                    "files": pc.files,
                }

            task_summaries.append(
                {
                    "task_id": t.task_id,
                    "category": t.category.value,
                    "title": t.title,
                    "specification": t.specification,
                    "target_file": t.target_file,
                    "target_symbol": t.target_symbol,
                    "contract_version_initial": t.contract_version_initial,
                    "contract_version_post_compaction": t.contract_version_post_compaction,
                    "witness_name": t.witness_name,
                    "witness_test_code": t.witness_test_code,
                    "reference_test_code": t.reference_test_code,
                    "candidates": candidates_map,
                }
            )

        return {
            "report": report,
            "tasks": task_summaries,
            "recent_telemetry": events,
        }

    def get_compaction_comparison(self, task_id: str) -> Dict[str, Any]:
        if task_id not in self.tasks_by_id:
            raise ValueError(f"Unknown task_id: {task_id}")
        task = self.tasks_by_id[task_id]

        ledger = CounterexampleLedger(self.db_path)
        try:
            records = ledger.get_by_task(task_id, include_resolved=True)
            primary_pred = (
                records[0].failure_predicate
                if records
                else "ASSERTION_FAILED: witness check failed"
            )
            turns = _build_pre_compaction_turns(task, primary_pred)

            compactions: Dict[str, Any] = {}
            for strat in CompactionStrategy:
                res = self.compactor.compact(
                    task_id=task.task_id,
                    specification=task.specification,
                    contract_version=task.contract_version_initial,
                    turns=turns,
                    strategy=strat,
                    ledger=ledger,
                )
                compactions[strat.value] = {
                    "strategy": strat.value,
                    "rendered_context": res.rendered_context,
                    "tokens_before": res.tokens_before,
                    "tokens_after": res.tokens_after,
                    "compression_ratio_pct": round(res.compression_ratio * 100.0, 2),
                    "witness_predicate_retained": res.witness_predicate_retained,
                    "pinned_counterexample_count": res.pinned_counterexample_count,
                }

            return {
                "task_id": task.task_id,
                "title": task.title,
                "category": task.category.value,
                "specification": task.specification,
                "ledger_records": [asdict(r) for r in records],
                "compactions": compactions,
            }
        finally:
            ledger.close()

    def evaluate_live_patch(
        self,
        task_id: str,
        files: Dict[str, str],
        contract_version: str = "v1",
        enable_ast_filter: bool = True,
        enable_witness_replay: bool = True,
        enforce_contract_version: bool = True,
    ) -> Dict[str, Any]:
        if task_id not in self.tasks_by_id:
            raise ValueError(f"Unknown task_id: {task_id}")
        task = self.tasks_by_id[task_id]

        ledger = CounterexampleLedger(":memory:")
        try:
            # Seed with the initial pre-compaction witness for clean deterministic sandbox testing
            db_ledger = CounterexampleLedger(self.db_path)
            try:
                for ce in db_ledger.get_by_task(task_id, include_resolved=True):
                    if ce.ce_id.endswith("-01"):
                        ledger.record(ce)
            finally:
                db_ledger.close()

            gate = RegressionGate(
                ledger=ledger,
                runner=self.runner,
                enable_ast_filter=enable_ast_filter,
                enable_witness_replay=enable_witness_replay,
                enforce_contract_version=enforce_contract_version,
            )
            gate_res = gate.evaluate(
                task_id=task_id,
                candidate_files=files,
                current_contract_version=contract_version,
            )
            oracle_res = self.runner.run_test_code(files, task.reference_test_code)
            return {
                "task_id": task_id,
                "contract_version": contract_version,
                "gate": {
                    "status": gate_res.status.value,
                    "triggered_by": gate_res.triggered_by,
                    "matched_ce_id": gate_res.matched_ce_id,
                    "reason": gate_res.reason,
                    "latency_ms": round(gate_res.latency_ms, 3),
                    "ledger_lookup_ms": round(gate_res.ledger_lookup_ms, 3),
                    "replay_latency_ms": round(gate_res.replay_latency_ms, 3),
                    "witnesses_checked": gate_res.witnesses_checked,
                    "ast_hash": gate_res.ast_hash,
                },
                "reference_oracle": {
                    "passed": oracle_res.passed,
                    "failure_predicate": oracle_res.failure_predicate,
                    "duration_ms": round(oracle_res.duration_ms, 3),
                },
            }
        finally:
            ledger.close()


_DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>CEGAR-Harness | Trajectory & Compaction Inspector</title>
  <style>
    :root {
      --bg: #0b0f19;
      --panel: #131b2e;
      --border: #23304d;
      --text: #e2e8f0;
      --muted: #94a3b8;
      --accent: #38bdf8;
      --pass: #10b981;
      --block: #f43f5e;
      --inconc: #f59e0b;
      --mono: "JetBrains Mono", "Fira Code", monospace;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      background: var(--bg);
      color: var(--text);
      line-height: 1.5;
    }
    header {
      padding: 16px 28px;
      border-bottom: 1px solid var(--border);
      background: #0f1626;
      display: flex;
      justify-content: space-between;
      align-items: center;
    }
    header h1 { margin: 0; font-size: 18px; font-weight: 700; letter-spacing: -0.02em; }
    header span.sub { color: var(--muted); font-size: 13px; margin-left: 10px; }
    nav.tabs {
      display: flex;
      gap: 8px;
      padding: 12px 28px;
      background: #0f1626;
      border-bottom: 1px solid var(--border);
    }
    nav.tabs button {
      background: transparent;
      color: var(--muted);
      border: 1px solid transparent;
      padding: 8px 16px;
      border-radius: 6px;
      cursor: pointer;
      font-weight: 600;
      font-size: 13px;
    }
    nav.tabs button.active {
      background: var(--panel);
      color: var(--accent);
      border-color: var(--border);
    }
    main { padding: 24px 28px; max-width: 1480px; margin: 0 auto; }
    .tab-pane { display: none; }
    .tab-pane.active { display: block; }
    .card {
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 18px;
      margin-bottom: 20px;
    }
    .grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 18px; }
    select, input, button.btn {
      background: #0b0f19;
      color: var(--text);
      border: 1px solid var(--border);
      padding: 8px 12px;
      border-radius: 6px;
      font-size: 13px;
    }
    button.btn-primary {
      background: #0284c7;
      border-color: #38bdf8;
      color: #fff;
      font-weight: 600;
      cursor: pointer;
    }
    pre, textarea {
      width: 100%;
      background: #070a12;
      color: #cbd5e1;
      border: 1px solid var(--border);
      border-radius: 6px;
      padding: 12px;
      font-family: var(--mono);
      font-size: 12.5px;
      overflow-x: auto;
      white-space: pre-wrap;
    }
    textarea { min-height: 220px; resize: vertical; }
    .badge {
      display: inline-block;
      padding: 3px 9px;
      border-radius: 999px;
      font-size: 11.5px;
      font-weight: 700;
    }
    .badge-pass { background: rgba(16,185,129,0.18); color: var(--pass); border: 1px solid var(--pass); }
    .badge-block { background: rgba(244,63,94,0.18); color: var(--block); border: 1px solid var(--block); }
    .badge-inconc { background: rgba(245,158,11,0.18); color: var(--inconc); border: 1px solid var(--inconc); }
    table { width: 100%; border-collapse: collapse; font-size: 13px; }
    th, td { padding: 10px 12px; border-bottom: 1px solid var(--border); text-align: left; }
    th { color: var(--muted); font-weight: 600; background: #0e1525; }
    .controls { display: flex; gap: 12px; align-items: center; flex-wrap: wrap; margin-bottom: 14px; }
  </style>
</head>
<body>
  <header>
    <div>
      <h1>CEGAR-Harness <span class="sub">Regression-Aware Context Compaction & Witness Replay Inspector</span></h1>
    </div>
    <div id="header-stats" style="font-size:13px;color:var(--muted);">Loading benchmark artifacts...</div>
  </header>

  <nav class="tabs">
    <button class="active" onclick="switchTab('compaction', this)">1. Side-by-Side Compaction Diff Viewer</button>
    <button onclick="switchTab('sandbox', this)">2. Live Regression Gate & Witness Replay Sandbox</button>
    <button onclick="switchTab('benchmark', this)">3. Benchmark, 4-Way Ablation & Telemetry Explorer</button>
  </nav>

  <main>
    <!-- TAB 1: COMPACTION DIFF VIEWER -->
    <section id="tab-compaction" class="tab-pane active">
      <div class="card">
        <div class="controls">
          <label>Task:</label>
          <select id="comp-task-select" onchange="loadCompactionComparison()"></select>
          <label>Left Strategy:</label>
          <select id="comp-left-strat" onchange="renderCompactionPanes()">
            <option value="OBSERVATION_MASKING">OBSERVATION_MASKING</option>
            <option value="LOSSY_SUMMARY" selected>LOSSY_SUMMARY</option>
            <option value="FULL_HISTORY">FULL_HISTORY</option>
          </select>
          <label>Right Strategy:</label>
          <select id="comp-right-strat" onchange="renderCompactionPanes()">
            <option value="CEGAR_HARNESS_FULL" selected>CEGAR_HARNESS_FULL</option>
            <option value="CEGAR_LEDGER_ONLY">CEGAR_LEDGER_ONLY</option>
            <option value="FULL_HISTORY">FULL_HISTORY</option>
          </select>
        </div>
        <div id="comp-task-meta" style="font-size:13px;color:var(--muted);margin-bottom:12px;"></div>
        <div class="grid-2">
          <div>
            <div id="comp-left-header" style="margin-bottom:8px;font-weight:600;"></div>
            <pre id="comp-left-pre"></pre>
          </div>
          <div>
            <div id="comp-right-header" style="margin-bottom:8px;font-weight:600;"></div>
            <pre id="comp-right-pre"></pre>
          </div>
        </div>
      </div>
    </section>

    <!-- TAB 2: LIVE REGRESSION GATE SANDBOX -->
    <section id="tab-sandbox" class="tab-pane">
      <div class="card">
        <div class="controls">
          <label>Task:</label>
          <select id="sb-task-select" onchange="onSandboxTaskChange()"></select>
          <label>Preset Candidate:</label>
          <select id="sb-preset-select" onchange="loadSandboxPreset()"></select>
          <label>Contract Version:</label>
          <select id="sb-contract-select">
            <option value="v1">v1</option>
            <option value="v2">v2</option>
          </select>
          <label><input type="checkbox" id="sb-ast-on" checked /> AST Filter</label>
          <label><input type="checkbox" id="sb-replay-on" checked /> Witness Replay</label>
          <label><input type="checkbox" id="sb-ver-on" checked /> Enforce Contract Ver.</label>
          <button class="btn btn-primary" onclick="runLiveGate()">Run Regression Gate</button>
        </div>
        <div class="grid-2">
          <div>
            <div style="font-weight:600;margin-bottom:6px;">Candidate Patch Code (<span id="sb-file-label"></span>)</div>
            <textarea id="sb-code-editor"></textarea>
            <div style="font-weight:600;margin:10px 0 6px;">Stored Pinned Witness Test (`witness_test_code`)</div>
            <pre id="sb-witness-code"></pre>
          </div>
          <div>
            <div style="font-weight:600;margin-bottom:6px;">Live 3-State Gate Verdict & Telemetry</div>
            <div id="sb-verdict-box" class="card" style="background:#070a12;min-height:280px;">
              Click <b>Run Regression Gate</b> to execute canonical AST hashing and isolated subprocess Witness Replay.
            </div>
          </div>
        </div>
      </div>
    </section>

    <!-- TAB 3: BENCHMARK, ABLATION & TELEMETRY EXPLORER -->
    <section id="tab-benchmark" class="tab-pane">
      <div class="card">
        <h3 style="margin-top:0;">1. Multi-Turn Context Compaction Strategies (30 Tasks, 95% Wilson CIs)</h3>
        <table id="tbl-strategies"></table>
      </div>
      <div class="card">
        <h3 style="margin-top:0;">2. RegressionGate 4-Way Ablation Study (60 Evaluations across 30 Tasks)</h3>
        <table id="tbl-ablations"></table>
      </div>
      <div class="card">
        <h3 style="margin-top:0;">3. Per-Category Regression & Multi-Turn Convergence Breakdown</h3>
        <table id="tbl-categories"></table>
      </div>
    </section>
  </main>

  <script>
    let OVERVIEW = null;
    let CURRENT_COMPACTION = null;

    function escapeHtml(str) {
      if (str === null || str === undefined) return '';
      return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
    }

    function switchTab(name, btn) {
      document.querySelectorAll('.tab-pane').forEach(el => el.classList.remove('active'));
      document.querySelectorAll('nav.tabs button').forEach(el => el.classList.remove('active'));
      document.getElementById('tab-' + name).classList.add('active');
      btn.classList.add('active');
    }

    async function initDashboard() {
      const resp = await fetch('/api/overview');
      OVERVIEW = await resp.json();
      const expA = OVERVIEW.report.experiment_a_controlled_replay;
      document.getElementById('header-stats').textContent =
        `30 Tasks | 6 Categories | Max Oracle Turns: ${expA.max_oracle_turns}`;

      const compSelect = document.getElementById('comp-task-select');
      const sbSelect = document.getElementById('sb-task-select');
      OVERVIEW.tasks.forEach(t => {
        const opt1 = new Option(`${t.task_id} (${t.category}) — ${t.title}`, t.task_id);
        const opt2 = new Option(`${t.task_id} (${t.category}) — ${t.title}`, t.task_id);
        compSelect.add(opt1);
        sbSelect.add(opt2);
      });
      compSelect.value = 'T26';
      sbSelect.value = 'T26';

      await loadCompactionComparison();
      onSandboxTaskChange();
      renderBenchmarkTables(expA);
    }

    async function loadCompactionComparison() {
      const taskId = document.getElementById('comp-task-select').value;
      const resp = await fetch(`/api/compaction?task_id=${encodeURIComponent(taskId)}`);
      CURRENT_COMPACTION = await resp.json();
      document.getElementById('comp-task-meta').innerHTML =
        `<b>Specification:</b> ${escapeHtml(CURRENT_COMPACTION.specification)} | ` +
        `<b>Ledger Witnesses for ${escapeHtml(taskId)}:</b> ${escapeHtml(CURRENT_COMPACTION.ledger_records.length)}`;
      renderCompactionPanes();
    }

    function renderCompactionPanes() {
      if (!CURRENT_COMPACTION) return;
      const leftKey = document.getElementById('comp-left-strat').value;
      const rightKey = document.getElementById('comp-right-strat').value;
      const left = CURRENT_COMPACTION.compactions[leftKey];
      const right = CURRENT_COMPACTION.compactions[rightKey];

      const fmtHeader = (c) => {
        const badge = c.witness_predicate_retained
          ? '<span class="badge badge-pass">WITNESS RETAINED</span>'
          : '<span class="badge badge-block">WITNESS LOST</span>';
        return `${escapeHtml(c.strategy)} — ${escapeHtml(c.tokens_before)} → ${escapeHtml(c.tokens_after)} tokens (${escapeHtml(c.compression_ratio_pct)}% saved) ${badge}`;
      };
      document.getElementById('comp-left-header').innerHTML = fmtHeader(left);
      document.getElementById('comp-right-header').innerHTML = fmtHeader(right);
      document.getElementById('comp-left-pre').textContent = left.rendered_context;
      document.getElementById('comp-right-pre').textContent = right.rendered_context;
    }

    function onSandboxTaskChange() {
      const taskId = document.getElementById('sb-task-select').value;
      const task = OVERVIEW.tasks.find(t => t.task_id === taskId);
      document.getElementById('sb-file-label').textContent = task.target_file;
      document.getElementById('sb-witness-code').textContent = task.witness_test_code;

      const presetSelect = document.getElementById('sb-preset-select');
      presetSelect.innerHTML = '';
      Object.entries(task.candidates).forEach(([key, cand]) => {
        presetSelect.add(new Option(`${key}: ${cand.patch_id} — ${cand.description}`, key));
      });
      presetSelect.value = 'c1_regression';
      loadSandboxPreset();
    }

    function loadSandboxPreset() {
      const taskId = document.getElementById('sb-task-select').value;
      const task = OVERVIEW.tasks.find(t => t.task_id === taskId);
      const key = document.getElementById('sb-preset-select').value;
      const cand = task.candidates[key];
      document.getElementById('sb-contract-select').value = cand.contract_version;
      document.getElementById('sb-code-editor').value = cand.files[task.target_file] || Object.values(cand.files)[0];
    }

    async function runLiveGate() {
      const taskId = document.getElementById('sb-task-select').value;
      const task = OVERVIEW.tasks.find(t => t.task_id === taskId);
      const key = document.getElementById('sb-preset-select').value;
      const baseFiles = Object.assign({}, task.candidates[key].files);
      baseFiles[task.target_file] = document.getElementById('sb-code-editor').value;

      const payload = {
        task_id: taskId,
        contract_version: document.getElementById('sb-contract-select').value,
        files: baseFiles,
        enable_ast_filter: document.getElementById('sb-ast-on').checked,
        enable_witness_replay: document.getElementById('sb-replay-on').checked,
        enforce_contract_version: document.getElementById('sb-ver-on').checked,
      };

      const resp = await fetch('/api/evaluate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const res = await resp.json();
      const g = res.gate;
      let badgeClass = 'badge-pass';
      if (g.status === 'REGRESSION_DETECTED') badgeClass = 'badge-block';
      else if (g.status === 'INCONCLUSIVE') badgeClass = 'badge-inconc';

      const oracleBadge = res.reference_oracle.passed
        ? '<span class="badge badge-pass">PASSED</span>'
        : `<span class="badge badge-block">FAILED (${escapeHtml(res.reference_oracle.failure_predicate)})</span>`;

      document.getElementById('sb-verdict-box').innerHTML = `
        <div style="margin-bottom:12px;">
          <b>Gate Status:</b> <span class="badge ${badgeClass}">${escapeHtml(g.status)}</span>
          &nbsp;|&nbsp; <b>Triggered By:</b> <code>${escapeHtml(g.triggered_by)}</code>
          &nbsp;|&nbsp; <b>Matched CE:</b> <code>${escapeHtml(g.matched_ce_id || 'None')}</code>
        </div>
        <div style="margin-bottom:10px;"><b>Diagnostic Reason:</b> ${escapeHtml(g.reason)}</div>
        <div style="margin-bottom:10px;">
          <b>Total Gate Latency:</b> <code>${escapeHtml(g.latency_ms)} ms</code>
          (Ledger/AST Lookup: <code>${escapeHtml(g.ledger_lookup_ms)} ms</code>, Isolated Witness Replay: <code>${escapeHtml(g.replay_latency_ms)} ms</code>)
        </div>
        <div style="margin-bottom:10px;"><b>Canonical AST SHA-256:</b> <code>${escapeHtml(g.ast_hash.slice(0, 24))}...</code></div>
        <hr style="border-color:var(--border);margin:14px 0;" />
        <div><b>Full Reference Oracle Suite Check:</b> ${oracleBadge} (<code>${escapeHtml(res.reference_oracle.duration_ms)} ms</code>)</div>
      `;
    }

    function renderBenchmarkTables(expA) {
      const sTbl = document.getElementById('tbl-strategies');
      sTbl.innerHTML = `
        <tr>
          <th>Strategy</th><th>Tokens (Pre → Post)</th><th>Comp. (%)</th><th>Witness Retained</th>
          <th>Gate Blocked</th><th>Unblocked Reg. [95% CI]</th><th>2nd-Round CEs</th>
          <th>Turn-1 Resolved</th><th>Final Resolved [95% CI]</th><th>Mean Oracle Turns</th>
        </tr>
      ` + expA.strategies.map(s => `
        <tr>
          <td><code>${escapeHtml(s.strategy)}</code></td>
          <td>${escapeHtml(s.mean_tokens_before)} → ${escapeHtml(s.mean_tokens_after)}</td>
          <td>${escapeHtml(s.mean_compression_ratio_pct)}%</td>
          <td>${escapeHtml(s.witness_retention_rate_pct)}%</td>
          <td>${escapeHtml(s.regressions_blocked_by_gate)}</td>
          <td>${escapeHtml(s.unblocked_regression_rate_pct)}% [${escapeHtml(s.regression_ci95_low_pct)}, ${escapeHtml(s.regression_ci95_high_pct)}]</td>
          <td>${escapeHtml(s.secondary_witnesses_synthesized)}</td>
          <td>${escapeHtml(s.turn1_resolution_rate_pct)}% (${escapeHtml(s.turn1_resolved)}/${escapeHtml(s.tasks_total)})</td>
          <td><b>${escapeHtml(s.resolution_rate_pct)}%</b> (${escapeHtml(s.tasks_resolved)}/${escapeHtml(s.tasks_total)}) [${escapeHtml(s.resolution_ci95_low_pct)}, ${escapeHtml(s.resolution_ci95_high_pct)}]</td>
          <td>${escapeHtml(s.mean_oracle_turns_to_convergence)}</td>
        </tr>
      `).join('');

      const aTbl = document.getElementById('tbl-ablations');
      aTbl.innerHTML = `
        <tr>
          <th>Ablation Config</th><th>AST Filter</th><th>Witness Replay</th><th>Contract Ver.</th>
          <th>Precision</th><th>Recall</th><th>F1</th><th>Cat. 6 Syn. Recall</th>
          <th>False Block Rate</th><th>Inconclusive</th><th>Med / p95 Latency (ms)</th>
        </tr>
      ` + expA.ablation_study.map(a => `
        <tr>
          <td><code>${escapeHtml(a.config_id)}</code></td>
          <td>${a.enable_ast_filter ? 'ON' : 'OFF'}</td>
          <td>${a.enable_witness_replay ? 'ON' : 'OFF'}</td>
          <td>${a.enforce_contract_version ? 'ON' : 'OFF'}</td>
          <td>${escapeHtml(a.gate_precision_pct)}%</td>
          <td>${escapeHtml(a.regression_recall_pct)}%</td>
          <td><b>${escapeHtml(a.gate_f1_pct)}%</b></td>
          <td>${escapeHtml(a.cat6_recall_pct)}%</td>
          <td>${escapeHtml(a.false_block_rate_pct)}%</td>
          <td>${escapeHtml(a.inconclusive_on_evolved_contract)}</td>
          <td>${escapeHtml(a.median_gate_latency_ms)} / ${escapeHtml(a.p95_gate_latency_ms)}</td>
        </tr>
      `).join('');

      const cTbl = document.getElementById('tbl-categories');
      cTbl.innerHTML = `
        <tr>
          <th>Category</th><th>Tasks</th><th>Obs. Masking Resolved</th>
          <th>CEGAR Ledger-Only Resolved</th><th>CEGAR Full Turn-1 Resolved</th>
          <th>CEGAR Full Final Resolved</th><th>2nd-Round Witnesses</th><th>Inconclusive</th>
        </tr>
      ` + expA.category_breakdown.map(c => `
        <tr>
          <td><code>${escapeHtml(c.category)}</code></td>
          <td>${escapeHtml(c.tasks_count)}</td>
          <td>${escapeHtml(c.obs_masking_resolved)}/${escapeHtml(c.tasks_count)}</td>
          <td>${escapeHtml(c.cegar_ledger_only_resolved)}/${escapeHtml(c.tasks_count)}</td>
          <td>${escapeHtml(c.cegar_full_turn1_resolved)}/${escapeHtml(c.tasks_count)}</td>
          <td><b>${escapeHtml(c.cegar_full_resolved)}/${escapeHtml(c.tasks_count)}</b></td>
          <td>${escapeHtml(c.cegar_full_secondary_witnesses)}</td>
          <td>${escapeHtml(c.cegar_full_inconclusive_gates)}</td>
        </tr>
      `).join('');
    }

    initDashboard();
  </script>
</body>
</html>
"""

MAX_POST_BODY_BYTES = 1_048_576


def make_ui_handler(app: CEGARInspectorApp) -> type[BaseHTTPRequestHandler]:
    """Creates a request handler class bound to `app`."""

    class _Handler(BaseHTTPRequestHandler):
        def _send_security_headers(self) -> None:
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; img-src 'self' data:;",
            )

        def do_GET(self) -> None:  # noqa: N802
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path == "/" or parsed.path == "/index.html":
                body = _DASHBOARD_HTML.encode("utf-8")
                self.send_response(200)
                self._send_security_headers()
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return

            if parsed.path == "/api/overview":
                self._send_json(200, app.get_overview_payload())
                return

            if parsed.path == "/api/compaction":
                qs = urllib.parse.parse_qs(parsed.query)
                task_id = (qs.get("task_id") or ["T01"])[0]
                try:
                    self._send_json(200, app.get_compaction_comparison(task_id))
                except Exception as exc:
                    self._send_json(400, {"error": str(exc)})
                return

            self._send_json(404, {"error": f"Not found: {parsed.path}"})

        def do_POST(self) -> None:  # noqa: N802
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path == "/api/evaluate":
                raw_len = self.headers.get("Content-Length")
                if raw_len is None:
                    self._send_json(400, {"error": "Missing Content-Length header"})
                    return
                try:
                    length = int(raw_len)
                except ValueError:
                    self._send_json(400, {"error": "Invalid Content-Length header"})
                    return
                if length <= 0:
                    self._send_json(400, {"error": "Content-Length must be positive"})
                    return
                if length > MAX_POST_BODY_BYTES:
                    self.close_connection = True
                    self._send_json(
                        413,
                        {"error": f"Payload Too Large: exceeds {MAX_POST_BODY_BYTES} bytes"},
                    )
                    return

                try:
                    raw = self.rfile.read(length).decode("utf-8")
                    payload = json.loads(raw)
                    if not isinstance(payload, dict):
                        raise ValueError("JSON payload must be an object")
                    raw_files = payload.get("files")
                    if not isinstance(raw_files, dict) or not raw_files:
                        raise ValueError("'files' must be a non-empty dictionary")
                    res = app.evaluate_live_patch(
                        task_id=str(payload["task_id"]),
                        files={str(k): str(v) for k, v in raw_files.items()},
                        contract_version=str(payload.get("contract_version", "v1")),
                        enable_ast_filter=bool(payload.get("enable_ast_filter", True)),
                        enable_witness_replay=bool(payload.get("enable_witness_replay", True)),
                        enforce_contract_version=bool(payload.get("enforce_contract_version", True)),
                    )
                    self._send_json(200, res)
                except Exception as exc:
                    self._send_json(400, {"error": str(exc)})
                return

            self._send_json(404, {"error": f"Not found: {parsed.path}"})

        def _send_json(self, status: int, data: Dict[str, Any]) -> None:
            body = json.dumps(data).encode("utf-8")
            self.send_response(status)
            self._send_security_headers()
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:  # noqa: A002
            return

    return _Handler


def create_ui_server(
    host: str = "127.0.0.1",
    port: int = 8080,
    results_dir: str | Path = "results",
) -> ThreadingHTTPServer:
    """Instantiates a ThreadingHTTPServer serving the CEGAR Inspector UI."""
    app = CEGARInspectorApp(results_dir=results_dir)
    handler_cls = make_ui_handler(app)
    return ThreadingHTTPServer((host, port), handler_cls)
