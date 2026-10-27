#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

PYTHON_BIN="python3"
if [ -x "$ROOT_DIR/.venv/bin/python" ]; then
    PYTHON_BIN="$ROOT_DIR/.venv/bin/python"
fi

echo "[1/3] Running pytest suite..."
"$PYTHON_BIN" -m pytest -v

echo ""
echo "[2/3] Running CEGAR-Harness Controlled Replay Benchmark & Ablation Study..."
"$PYTHON_BIN" -m cegar_harness.cli bench --output-dir "$ROOT_DIR/results"

echo ""
echo "[3/3] Checking Experiment B (Live LLM Continuation) configuration status..."
"$PYTHON_BIN" -m cegar_harness.cli live-eval --max-tasks 3
