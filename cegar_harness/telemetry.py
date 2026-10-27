"""Structured JSONL event logger and OpenTelemetry instrumentation."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from cegar_harness.models import GateEvaluationResult


class TelemetryRecorder:
    """Records OpenTelemetry spans and structured JSONL events for auditability."""

    def __init__(self, jsonl_path: Optional[str | Path] = None) -> None:
        self.jsonl_path = Path(jsonl_path) if jsonl_path else None
        if self.jsonl_path:
            self.jsonl_path.parent.mkdir(parents=True, exist_ok=True)

        self.exporter = InMemorySpanExporter()
        self.provider = TracerProvider(
            resource=Resource.create({"service.name": "cegar-harness"})
        )
        self.provider.add_span_processor(SimpleSpanProcessor(self.exporter))
        self.tracer = self.provider.get_tracer("cegar_harness.telemetry")
        self.events: List[Dict[str, Any]] = []

    def record_gate_evaluation(self, task_id: str, result: GateEvaluationResult) -> None:
        with self.tracer.start_as_current_span("cegar.gate.evaluate") as span:
            span.set_attribute("cegar.task_id", task_id)
            span.set_attribute("cegar.gate.status", result.status.value)
            span.set_attribute("cegar.gate.triggered_by", result.triggered_by)
            span.set_attribute("cegar.gate.latency_ms", round(result.latency_ms, 4))
            span.set_attribute("cegar.gate.witnesses_checked", result.witnesses_checked)
            if result.matched_ce_id:
                span.set_attribute("cegar.gate.matched_ce_id", result.matched_ce_id)

        self._write_event(
            {
                "timestamp": time.time(),
                "event_type": "gate_evaluation",
                "task_id": task_id,
                "status": result.status.value,
                "triggered_by": result.triggered_by,
                "matched_ce_id": result.matched_ce_id,
                "latency_ms": round(result.latency_ms, 4),
                "witnesses_checked": result.witnesses_checked,
                "reason": result.reason,
            }
        )

    def record_compaction(
        self,
        task_id: str,
        strategy: str,
        tokens_before: int,
        tokens_after: int,
        witness_retained: bool,
    ) -> None:
        with self.tracer.start_as_current_span("cegar.compaction.run") as span:
            span.set_attribute("cegar.task_id", task_id)
            span.set_attribute("cegar.compaction.strategy", strategy)
            span.set_attribute("cegar.compaction.tokens_before", tokens_before)
            span.set_attribute("cegar.compaction.tokens_after", tokens_after)
            span.set_attribute("cegar.compaction.witness_retained", witness_retained)

        self._write_event(
            {
                "timestamp": time.time(),
                "event_type": "compaction",
                "task_id": task_id,
                "strategy": strategy,
                "tokens_before": tokens_before,
                "tokens_after": tokens_after,
                "witness_retained": witness_retained,
            }
        )

    def _write_event(self, payload: Dict[str, Any]) -> None:
        self.events.append(payload)
        if self.jsonl_path:
            with self.jsonl_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(payload) + "\n")
