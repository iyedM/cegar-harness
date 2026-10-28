#!/usr/bin/env python3
"""Generates publication-grade vector SVG figures in `docs/figures/` from live benchmark JSON data."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List


def generate_architecture_svg(out_path: Path) -> None:
    """Generates `docs/figures/cegar_architecture.svg`."""
    svg = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 980 390" width="100%" height="100%" font-family="Inter, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif">
  <defs>
    <linearGradient id="bgGrad" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="#f8fafc"/>
      <stop offset="100%" stop-color="#f1f5f9"/>
    </linearGradient>
    <marker id="arrowBlue" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
      <path d="M 0 1 L 10 5 L 0 9 z" fill="#1e40af"/>
    </marker>
    <marker id="arrowRed" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
      <path d="M 0 1 L 10 5 L 0 9 z" fill="#b91c1c"/>
    </marker>
    <marker id="arrowGreen" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
      <path d="M 0 1 L 10 5 L 0 9 z" fill="#15803d"/>
    </marker>
    <marker id="arrowAmber" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
      <path d="M 0 1 L 10 5 L 0 9 z" fill="#b45309"/>
    </marker>
  </defs>

  <rect width="980" height="390" rx="10" fill="url(#bgGrad)" stroke="#cbd5e1" stroke-width="1.5"/>
  <text x="490" y="28" text-anchor="middle" font-size="15" font-weight="700" fill="#0f172a">
    CEGAR-Harness Architecture: Counterexample-Pinned Compaction &amp; Three-State Regression Gate
  </text>

  <!-- Box 1: Agent Trajectory -->
  <rect x="24" y="54" width="185" height="125" rx="8" fill="#ffffff" stroke="#3b82f6" stroke-width="2"/>
  <rect x="24" y="54" width="185" height="28" rx="8" fill="#eff6ff"/>
  <text x="116" y="73" text-anchor="middle" font-size="11.5" font-weight="700" fill="#1e3a8a">1. Pre-Compaction Turns</text>
  <text x="36" y="98" font-size="10" fill="#334155">• Step 1: Defective Patch F₁</text>
  <text x="36" y="116" font-size="10" fill="#b91c1c" font-weight="600">• Step 2: Witness Fails (CE-01)</text>
  <text x="36" y="134" font-size="10" fill="#334155">• Step 3–6: Tool Logs (+667 tok)</text>
  <text x="36" y="152" font-size="9.5" fill="#64748b" font-style="italic">Context budget reached → Compact</text>

  <!-- Arrow 1 -> 2 -->
  <line x1="209" y1="116" x2="248" y2="116" stroke="#1e40af" stroke-width="2" marker-end="url(#arrowBlue)"/>

  <!-- Box 2: CompactionController -->
  <rect x="252" y="54" width="210" height="125" rx="8" fill="#ffffff" stroke="#2563eb" stroke-width="2"/>
  <rect x="252" y="54" width="210" height="28" rx="8" fill="#dbeafe"/>
  <text x="357" y="73" text-anchor="middle" font-size="11.5" font-weight="700" fill="#1e3a8a">2. CompactionController</text>
  <text x="264" y="98" font-size="10" fill="#0f172a" font-weight="600">Prunes verbose logs (-48.26% tok)</text>
  <text x="264" y="116" font-size="10" fill="#15803d" font-weight="600">Pins Active Witness Predicates:</text>
  <text x="264" y="133" font-size="9.2" font-family="monospace" fill="#1e293b">CE-T26-01 | contract=v1</text>
  <text x="264" y="148" font-size="9.2" font-family="monospace" fill="#b91c1c">assert [1,2] == [0,1,2]</text>
  <text x="264" y="166" font-size="9.2" fill="#475569">100% Witness Retention Rate</text>

  <!-- Box 3: Versioned SQLite Ledger (Bottom Left/Center) -->
  <rect x="130" y="226" width="332" height="136" rx="8" fill="#ffffff" stroke="#0f766e" stroke-width="2"/>
  <rect x="130" y="226" width="332" height="28" rx="8" fill="#ccfbf1"/>
  <text x="296" y="245" text-anchor="middle" font-size="11.5" font-weight="700" fill="#115e59">
    Versioned CounterexampleLedger (SQLite)
  </text>
  <text x="144" y="269" font-size="9.5" font-family="monospace" fill="#0f172a">• ce_id: "CE-T26-01"   • contract_version: "v1"</text>
  <text x="144" y="286" font-size="9.5" font-family="monospace" fill="#0f172a">• ast_hash: SHA256(α-normalized AST)</text>
  <text x="144" y="303" font-size="9.5" font-family="monospace" fill="#0f172a">• witness_test_code: def test_zero_retained()...</text>
  <text x="144" y="320" font-size="9.5" font-family="monospace" fill="#0f172a">• failure_predicate: "ASSERTION_FAILED: ..."</text>
  <text x="144" y="342" font-size="9.5" fill="#0f766e" font-weight="600">Persists across Compaction, MCP, Git &amp; LangGraph</text>

  <!-- Arrows connecting Ledger -->
  <path d="M 116 179 L 116 294 L 126 294" fill="none" stroke="#b91c1c" stroke-width="1.8" stroke-dasharray="4,3" marker-end="url(#arrowRed)"/>
  <text x="40" y="220" font-size="9" fill="#b91c1c" font-weight="600">Records CE-01</text>
  <line x1="357" y1="226" x2="357" y2="183" stroke="#1e40af" stroke-width="1.8" marker-end="url(#arrowBlue)"/>

  <!-- Arrow 2 -> Candidate Patch -> 3-State Gate -->
  <line x1="462" y1="116" x2="508" y2="116" stroke="#1e40af" stroke-width="2" marker-end="url(#arrowBlue)"/>

  <!-- Box 4: Three-State RegressionGate -->
  <rect x="512" y="54" width="256" height="225" rx="8" fill="#ffffff" stroke="#4f46e5" stroke-width="2.2"/>
  <rect x="512" y="54" width="256" height="28" rx="8" fill="#e0e7ff"/>
  <text x="640" y="73" text-anchor="middle" font-size="11.5" font-weight="700" fill="#312e81">
    3. Pre-Execution RegressionGate
  </text>

  <!-- Stage 1 sub-box -->
  <rect x="526" y="92" width="228" height="72" rx="6" fill="#f8fafc" stroke="#94a3b8" stroke-width="1.2"/>
  <text x="536" y="109" font-size="10.2" font-weight="700" fill="#1e293b">Stage 1: Canonical AST Pre-Filter</text>
  <text x="536" y="125" font-size="9.3" fill="#334155">• Strips docstrings &amp; α-renames locals</text>
  <text x="536" y="140" fill="#0f766e" font-size="9.3" font-weight="600">• Median lookup: 0.30 ms (O(|F|))</text>
  <text x="536" y="155" fill="#64748b" font-size="9">Short-circuits exact/renamed repeats</text>

  <!-- Stage 2 sub-box -->
  <rect x="526" y="176" width="228" height="88" rx="6" fill="#f8fafc" stroke="#94a3b8" stroke-width="1.2"/>
  <text x="536" y="193" font-size="10.2" font-weight="700" fill="#1e293b">Stage 2: Isolated Witness Replay</text>
  <text x="536" y="209" font-size="9.3" fill="#334155">• Sandboxed subprocess (timeout=5s)</text>
  <text x="536" y="224" font-size="9.3" fill="#b91c1c" font-weight="600">• Catches 100% (5/5) Cat. 6 syntactic</text>
  <text x="536" y="238" font-size="9.3" fill="#b91c1c" font-weight="600">  bug variants missed by AST hash</text>
  <text x="536" y="254" font-size="9.3" fill="#0f766e" font-weight="600">• Median gate latency: 18.71 ms</text>

  <!-- Ledger -> Gate arrow -->
  <path d="M 462 294 L 640 294 L 640 282" fill="none" stroke="#1e40af" stroke-width="1.8" marker-end="url(#arrowBlue)"/>

  <!-- 3 Verdicts on the Right -->
  <!-- PASS -->
  <line x1="768" y1="98" x2="806" y2="98" stroke="#15803d" stroke-width="2" marker-end="url(#arrowGreen)"/>
  <rect x="810" y="64" width="150" height="68" rx="7" fill="#f0fdf4" stroke="#16a34a" stroke-width="1.8"/>
  <text x="885" y="84" text-anchor="middle" font-size="11" font-weight="700" fill="#15803d">PASS</text>
  <text x="885" y="100" text-anchor="middle" font-size="9.2" fill="#166534">All active witnesses pass</text>
  <text x="885" y="115" text-anchor="middle" font-size="9.2" font-weight="600" fill="#14532d">→ Proceed to Oracle</text>

  <!-- REGRESSION_DETECTED -->
  <line x1="768" y1="176" x2="806" y2="176" stroke="#b91c1c" stroke-width="2" marker-end="url(#arrowRed)"/>
  <rect x="810" y="142" width="150" height="74" rx="7" fill="#fef2f2" stroke="#dc2626" stroke-width="1.8"/>
  <text x="885" y="160" text-anchor="middle" font-size="9.8" font-weight="700" fill="#b91c1c">REGRESSION_DETECTED</text>
  <text x="885" y="176" text-anchor="middle" font-size="9" fill="#991b1b">Same contract v; fails CE</text>
  <text x="885" y="191" text-anchor="middle" font-size="9" font-weight="600" fill="#7f1d1d">→ Atomic Git Rollback</text>
  <text x="885" y="205" text-anchor="middle" font-size="9" font-weight="600" fill="#7f1d1d">&amp; Self-Repair Turn</text>

  <!-- INCONCLUSIVE -->
  <line x1="768" y1="252" x2="806" y2="252" stroke="#b45309" stroke-width="2" marker-end="url(#arrowAmber)"/>
  <rect x="810" y="226" width="150" height="72" rx="7" fill="#fffbeb" stroke="#d97706" stroke-width="1.8"/>
  <text x="885" y="245" text-anchor="middle" font-size="10.5" font-weight="700" fill="#b45309">INCONCLUSIVE</text>
  <text x="885" y="261" text-anchor="middle" font-size="9" fill="#92400e">Contract evolved (v1 → v2)</text>
  <text x="885" y="276" text-anchor="middle" font-size="9" font-weight="600" fill="#78350f">→ 0% False Blocks (5/5)</text>
  <text x="885" y="290" text-anchor="middle" font-size="9" fill="#78350f">Defer to v2 Oracle</text>

  <!-- Telemetry Footer Bar -->
  <rect x="512" y="314" width="448" height="48" rx="7" fill="#f8fafc" stroke="#64748b" stroke-width="1.4"/>
  <text x="736" y="334" text-anchor="middle" font-size="10.2" font-weight="700" fill="#1e293b">
    OpenTelemetry Spans (cegar.gate.evaluate, cegar.compaction.run) &amp; MCP / Git / LangGraph Adapters
  </text>
  <text x="736" y="351" text-anchor="middle" font-size="9.2" fill="#475569">
    Audited in results/telemetry_events.jsonl • Interactive Web UI: cegar-harness ui --port 8080
  </text>
</svg>
"""
    out_path.write_text(svg, encoding="utf-8")


def generate_strategy_comparison_svg(strategies: List[Dict[str, Any]], out_path: Path) -> None:
    """Generates `docs/figures/strategy_comparison.svg` from `results/benchmark_report.json`."""
    width = 960
    height = 420
    chart_left = 78
    chart_top = 68
    chart_w = 840
    chart_h = 260
    chart_bottom = chart_top + chart_h

    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="100%" height="100%" '
        'font-family="Inter, -apple-system, BlinkMacSystemFont, \'Segoe UI\', Roboto, sans-serif">',
        f'  <rect width="{width}" height="{height}" rx="10" fill="#ffffff" stroke="#cbd5e1" stroke-width="1.5"/>',
        '  <text x="480" y="28" text-anchor="middle" font-size="14.5" font-weight="700" fill="#0f172a">',
        "    Experiment A (30 Tasks): Context Compaction, Unblocked Regressions &amp; Multi-Turn Resolution (with 95% Wilson CIs)",
        "  </text>",
        '  <text x="480" y="47" text-anchor="middle" font-size="10.5" fill="#475569">',
        "    Comparison across 5 compaction strategies under a post-compaction budget of max_oracle_turns = 2",
        "  </text>",
    ]

    # Horizontal gridlines (0% to 100%)
    for pct in (0, 20, 40, 60, 80, 100):
        y = chart_bottom - (pct / 100.0) * chart_h
        lines.append(
            f'  <line x1="{chart_left}" y1="{y:.1f}" x2="{chart_left + chart_w}" y2="{y:.1f}" '
            f'stroke="{"#94a3b8" if pct == 0 else "#e2e8f0"}" stroke-width="{"1.5" if pct == 0 else "1"}"/>'
        )
        lines.append(
            f'  <text x="{chart_left - 10}" y="{y + 4:.1f}" text-anchor="end" font-size="10" fill="#475569">{pct}%</text>'
        )

    # 4 bars per strategy:
    # 1. Token Compression (%) - #3b82f6 (Blue)
    # 2. Unblocked Regressions (%) - #ef4444 (Red)
    # 3. Turn-1 Resolution (%) - #f59e0b (Amber)
    # 4. Final 2-Turn Resolution (%) - #10b981 (Emerald) + 95% Wilson CI whiskers
    colors = [
        ("Token Compression %", "#3b82f6"),
        ("Unblocked Regressions %", "#ef4444"),
        ("Turn-1 Resolved %", "#f59e0b"),
        ("Final Resolved % (with 95% CI)", "#10b981"),
    ]

    group_w = chart_w / len(strategies)
    bar_w = 30

    for idx, s in enumerate(strategies):
        group_x = chart_left + idx * group_w + 22
        vals = [
            s["mean_compression_ratio_pct"],
            s["unblocked_regression_rate_pct"],
            s["turn1_resolution_rate_pct"],
            s["resolution_rate_pct"],
        ]
        for b_idx, val in enumerate(vals):
            bx = group_x + b_idx * (bar_w + 4)
            bh = max(2.0, (val / 100.0) * chart_h)
            by = chart_bottom - bh
            color = colors[b_idx][1]
            lines.append(
                f'  <rect x="{bx:.1f}" y="{by:.1f}" width="{bar_w}" height="{bh:.1f}" rx="3" fill="{color}"/>'
            )
            # Value label above bar
            label_y = by - 5
            if b_idx == 3:
                # Draw 95% Wilson CI whisker on Final Resolved bar
                ci_low = s["resolution_ci95_low_pct"]
                ci_high = s["resolution_ci95_high_pct"]
                y_low = chart_bottom - (ci_low / 100.0) * chart_h
                y_high = chart_bottom - (ci_high / 100.0) * chart_h
                cx = bx + bar_w / 2.0
                lines.append(
                    f'  <line x1="{cx:.1f}" y1="{y_high:.1f}" x2="{cx:.1f}" y2="{y_low:.1f}" stroke="#064e3b" stroke-width="1.8"/>'
                )
                lines.append(
                    f'  <line x1="{cx - 5:.1f}" y1="{y_high:.1f}" x2="{cx + 5:.1f}" y2="{y_high:.1f}" stroke="#064e3b" stroke-width="1.8"/>'
                )
                lines.append(
                    f'  <line x1="{cx - 5:.1f}" y1="{y_low:.1f}" x2="{cx + 5:.1f}" y2="{y_low:.1f}" stroke="#064e3b" stroke-width="1.8"/>'
                )
                label_y = min(by, y_high) - 6

            lines.append(
                f'  <text x="{bx + bar_w / 2.0:.1f}" y="{label_y:.1f}" text-anchor="middle" '
                f'font-size="8.8" font-weight="700" fill="#1e293b">{val:.1f}%</text>'
            )

        # Strategy X-axis label
        center_group = group_x + 2 * (bar_w + 4) - 2
        lines.append(
            f'  <text x="{center_group:.1f}" y="{chart_bottom + 20}" text-anchor="middle" '
            f'font-size="9.8" font-weight="700" font-family="monospace" fill="#0f172a">{s["strategy"]}</text>'
        )
        lines.append(
            f'  <text x="{center_group:.1f}" y="{chart_bottom + 34}" text-anchor="middle" '
            f'font-size="8.8" fill="#64748b">Mean Oracle Turns: {s["mean_oracle_turns_to_convergence"]:.2f}</text>'
        )

    # Legend at bottom
    legend_y = 385
    legend_x = 125
    for label, color in colors:
        lines.append(f'  <rect x="{legend_x}" y="{legend_y - 10}" width="13" height="13" rx="2" fill="{color}"/>')
        lines.append(f'  <text x="{legend_x + 18}" y="{legend_y}" font-size="10" font-weight="600" fill="#334155">{label}</text>')
        legend_x += 195

    lines.append("</svg>")
    out_path.write_text("\n".join(lines), encoding="utf-8")


def generate_ablation_study_svg(ablations: List[Dict[str, Any]], out_path: Path) -> None:
    """Generates `docs/figures/ablation_study.svg` from `results/ablation_study.json`."""
    width = 960
    height = 410
    chart_left = 78
    chart_top = 68
    chart_w = 840
    chart_h = 250
    chart_bottom = chart_top + chart_h

    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="100%" height="100%" '
        'font-family="Inter, -apple-system, BlinkMacSystemFont, \'Segoe UI\', Roboto, sans-serif">',
        f'  <rect width="{width}" height="{height}" rx="10" fill="#ffffff" stroke="#cbd5e1" stroke-width="1.5"/>',
        '  <text x="480" y="28" text-anchor="middle" font-size="14.5" font-weight="700" fill="#0f172a">',
        "    Four-Way RegressionGate Ablation Study (60 Candidate Evaluations across 30 Tasks)",
        "  </text>",
        '  <text x="480" y="47" text-anchor="middle" font-size="10.5" fill="#475569">',
        "    Isolating Canonical AST Pre-Filtering, Isolated Witness Replay (Cat. 6 Recall), and Contract Versioning (Cat. 5 False Blocks)",
        "  </text>",
    ]

    for pct in (0, 20, 40, 60, 80, 100):
        y = chart_bottom - (pct / 100.0) * chart_h
        lines.append(
            f'  <line x1="{chart_left}" y1="{y:.1f}" x2="{chart_left + chart_w}" y2="{y:.1f}" '
            f'stroke="{"#94a3b8" if pct == 0 else "#e2e8f0"}" stroke-width="{"1.5" if pct == 0 else "1"}"/>'
        )
        lines.append(
            f'  <text x="{chart_left - 10}" y="{y + 4:.1f}" text-anchor="end" font-size="10" fill="#475569">{pct}%</text>'
        )

    colors = [
        ("Gate Precision %", "#2563eb"),
        ("Overall Recall %", "#0d9488"),
        ("Cat. 6 Syntactic Variant Recall %", "#7c3aed"),
        ("False Block Rate % (Lower is Better)", "#dc2626"),
    ]

    group_w = chart_w / len(ablations)
    bar_w = 34

    for idx, a in enumerate(ablations):
        group_x = chart_left + idx * group_w + 30
        vals = [
            a["gate_precision_pct"],
            a["regression_recall_pct"],
            a["cat6_recall_pct"],
            a["false_block_rate_pct"],
        ]
        for b_idx, val in enumerate(vals):
            bx = group_x + b_idx * (bar_w + 5)
            bh = max(2.5, (val / 100.0) * chart_h)
            by = chart_bottom - bh
            color = colors[b_idx][1]
            lines.append(
                f'  <rect x="{bx:.1f}" y="{by:.1f}" width="{bar_w}" height="{bh:.1f}" rx="3" fill="{color}"/>'
            )
            lines.append(
                f'  <text x="{bx + bar_w / 2.0:.1f}" y="{by - 6:.1f}" text-anchor="middle" '
                f'font-size="9" font-weight="700" fill="#1e293b">{val:.1f}%</text>'
            )

        center_group = group_x + 2 * (bar_w + 5) - 2
        lines.append(
            f'  <text x="{center_group:.1f}" y="{chart_bottom + 20}" text-anchor="middle" '
            f'font-size="10" font-weight="700" font-family="monospace" fill="#0f172a">{a["config_id"]}</text>'
        )
        lines.append(
            f'  <text x="{center_group:.1f}" y="{chart_bottom + 35}" text-anchor="middle" '
            f'font-size="8.8" fill="#64748b">Med/p95: {a["median_gate_latency_ms"]:.2f} / {a["p95_gate_latency_ms"]:.2f} ms</text>'
        )

    legend_y = 382
    legend_x = 95
    for label, color in colors:
        lines.append(f'  <rect x="{legend_x}" y="{legend_y - 10}" width="13" height="13" rx="2" fill="{color}"/>')
        lines.append(f'  <text x="{legend_x + 18}" y="{legend_y}" font-size="10" font-weight="600" fill="#334155">{label}</text>')
        legend_x += 205

    lines.append("</svg>")
    out_path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    root_dir = Path(__file__).resolve().parent.parent
    fig_dir = root_dir / "docs" / "figures"
    fig_dir.mkdir(parents=True, exist_ok=True)

    report = json.loads((root_dir / "results" / "benchmark_report.json").read_text(encoding="utf-8"))
    exp_a = report["experiment_a_controlled_replay"]

    generate_architecture_svg(fig_dir / "cegar_architecture.svg")
    generate_strategy_comparison_svg(exp_a["strategies"], fig_dir / "strategy_comparison.svg")
    generate_ablation_study_svg(exp_a["ablation_study"], fig_dir / "ablation_study.svg")

    print(f"Generated 3 SVG figures in {fig_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
