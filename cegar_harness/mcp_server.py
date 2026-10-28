"""Model Context Protocol (MCP) JSON-RPC 2.0 Server over stdio for CEGAR-Harness."""

from __future__ import annotations

import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, IO, List, Optional

from cegar_harness.ast_filter import compute_canonical_ast_hash
from cegar_harness.compactor import CompactionController, TrajectoryTurn
from cegar_harness.gate import RegressionGate
from cegar_harness.ledger import CounterexampleLedger
from cegar_harness.models import CompactionStrategy, CounterexampleRecord
from cegar_harness.replay import IsolatedTestRunner
from cegar_harness.telemetry import TelemetryRecorder


class CEGARMCPServer:
    """Standard JSON-RPC 2.0 Model Context Protocol (MCP) Server exposing 4 CEGAR-Harness tools."""

    SERVER_NAME = "cegar-harness-mcp"
    SERVER_VERSION = "0.2.0"
    PROTOCOL_VERSION = "2024-11-05"

    def __init__(
        self,
        db_path: str | Path = "results/counterexamples.sqlite",
        jsonl_path: Optional[str | Path] = None,
    ) -> None:
        Path(db_path).parent.mkdir(parents=True, exist_ok=True) if str(db_path) != ":memory:" else None
        self.ledger = CounterexampleLedger(db_path)
        self.runner = IsolatedTestRunner(timeout_seconds=5.0)
        self.telemetry = TelemetryRecorder(jsonl_path)
        self.gate = RegressionGate(
            ledger=self.ledger,
            runner=self.runner,
            telemetry=self.telemetry,
        )
        self.compactor = CompactionController(sliding_window_turns=2)

    def list_tools(self) -> List[Dict[str, Any]]:
        """Returns the MCP tool definitions for Claude Code, Cursor, and MCP clients."""
        return [
            {
                "name": "cegar_evaluate_patch",
                "description": (
                    "Evaluate a candidate code patch against the versioned SQLite Counterexample Ledger "
                    "and run isolated Witness Replay before authorizing file writes. Returns PASS, "
                    "REGRESSION_DETECTED, or INCONCLUSIVE."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "task_id": {"type": "string", "description": "Task or session identifier"},
                        "files": {
                            "type": "object",
                            "additionalProperties": {"type": "string"},
                            "description": "Mapping of relative file paths to candidate source code",
                        },
                        "contract_version": {
                            "type": "string",
                            "default": "v1",
                            "description": "Active specification contract version",
                        },
                    },
                    "required": ["task_id", "files"],
                },
            },
            {
                "name": "cegar_record_witness",
                "description": (
                    "Record a reproducible failure witness (counterexample) into the persistent SQLite ledger "
                    "with its canonical AST hash and contract version."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "ce_id": {"type": "string"},
                        "task_id": {"type": "string"},
                        "target_file": {"type": "string"},
                        "target_symbol": {"type": "string"},
                        "contract_version": {"type": "string", "default": "v1"},
                        "files": {
                            "type": "object",
                            "additionalProperties": {"type": "string"},
                        },
                        "witness_name": {"type": "string"},
                        "witness_test_code": {"type": "string"},
                        "failure_predicate": {"type": "string"},
                        "discovered_at_step": {"type": "integer", "default": 1},
                    },
                    "required": [
                        "ce_id",
                        "task_id",
                        "target_file",
                        "target_symbol",
                        "files",
                        "witness_name",
                        "witness_test_code",
                    ],
                },
            },
            {
                "name": "cegar_compact_trajectory",
                "description": (
                    "Compact an agent conversation trajectory using regression-aware context compaction "
                    "that pins active counterexample predicates from the SQLite ledger."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "task_id": {"type": "string"},
                        "specification": {"type": "string"},
                        "contract_version": {"type": "string", "default": "v1"},
                        "strategy": {
                            "type": "string",
                            "default": "CEGAR_HARNESS_FULL",
                            "enum": [s.value for s in CompactionStrategy],
                        },
                        "turns": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "step": {"type": "integer"},
                                    "role": {"type": "string"},
                                    "content": {"type": "string"},
                                    "is_failure_observation": {"type": "boolean"},
                                    "witness_predicate": {"type": "string"},
                                },
                                "required": ["step", "role", "content"],
                            },
                        },
                    },
                    "required": ["task_id", "specification", "turns"],
                },
            },
            {
                "name": "cegar_query_ledger",
                "description": (
                    "Query stored counterexamples from the SQLite ledger filtered by task_id, "
                    "target_file, target_symbol, or status."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "task_id": {"type": "string"},
                        "target_file": {"type": "string"},
                        "target_symbol": {"type": "string"},
                        "include_resolved": {"type": "boolean", "default": True},
                    },
                    "required": ["task_id"],
                },
            },
        ]

    def handle_request(self, request: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Processes a single JSON-RPC 2.0 request dictionary and returns the response dictionary."""
        method = request.get("method", "")
        req_id = request.get("id")
        params = request.get("params") or {}

        # Notifications have no 'id' and require no response
        if req_id is None and method.startswith("notifications/"):
            return None

        try:
            if method == "initialize":
                result = {
                    "protocolVersion": self.PROTOCOL_VERSION,
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {
                        "name": self.SERVER_NAME,
                        "version": self.SERVER_VERSION,
                    },
                }
            elif method == "ping":
                result = {}
            elif method == "tools/list":
                result = {"tools": self.list_tools()}
            elif method == "tools/call":
                tool_name = params.get("name", "")
                args = params.get("arguments") or {}
                tool_output = self._call_tool(tool_name, args)
                result = {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(tool_output, indent=2),
                        }
                    ],
                    "structuredContent": tool_output,
                    "isError": False,
                }
            else:
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {"code": -32601, "message": f"Method not found: {method}"},
                }

            return {"jsonrpc": "2.0", "id": req_id, "result": result}
        except Exception as exc:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32602, "message": str(exc)},
            }

    def _call_tool(self, name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        if name == "cegar_evaluate_patch":
            task_id = str(args["task_id"])
            files = dict(args["files"])
            contract_version = str(args.get("contract_version", "v1"))
            res = self.gate.evaluate(
                task_id=task_id,
                candidate_files=files,
                current_contract_version=contract_version,
            )
            return {
                "status": res.status.value,
                "triggered_by": res.triggered_by,
                "matched_ce_id": res.matched_ce_id,
                "reason": res.reason,
                "latency_ms": round(res.latency_ms, 3),
                "ledger_lookup_ms": round(res.ledger_lookup_ms, 3),
                "replay_latency_ms": round(res.replay_latency_ms, 3),
                "witnesses_checked": res.witnesses_checked,
                "ast_hash": res.ast_hash,
            }

        if name == "cegar_record_witness":
            files = dict(args["files"])
            witness_code = str(args["witness_test_code"])
            predicate = args.get("failure_predicate")
            if not predicate:
                exec_res = self.runner.run_test_code(files, witness_code)
                predicate = exec_res.failure_predicate

            ce = CounterexampleRecord(
                ce_id=str(args["ce_id"]),
                task_id=str(args["task_id"]),
                target_file=str(args["target_file"]),
                target_symbol=str(args["target_symbol"]),
                contract_version=str(args.get("contract_version", "v1")),
                ast_hash=compute_canonical_ast_hash(files),
                witness_name=str(args["witness_name"]),
                witness_test_code=witness_code,
                failure_predicate=str(predicate),
                discovered_at_step=int(args.get("discovered_at_step", 1)),
                status="ACTIVE",
                provenance="mcp_record_witness",
            )
            self.ledger.record(ce)
            return {"recorded": True, "counterexample": asdict(ce)}

        if name == "cegar_compact_trajectory":
            task_id = str(args["task_id"])
            spec = str(args["specification"])
            contract_version = str(args.get("contract_version", "v1"))
            strat = CompactionStrategy(args.get("strategy", "CEGAR_HARNESS_FULL"))
            raw_turns = args.get("turns") or []
            turns = [
                TrajectoryTurn(
                    step=int(t["step"]),
                    role=str(t["role"]),
                    content=str(t["content"]),
                    is_failure_observation=bool(t.get("is_failure_observation", False)),
                    witness_predicate=str(t.get("witness_predicate", "")),
                )
                for t in raw_turns
            ]
            comp = self.compactor.compact(
                task_id=task_id,
                specification=spec,
                contract_version=contract_version,
                turns=turns,
                strategy=strat,
                ledger=self.ledger,
            )
            return {
                "strategy": comp.strategy.value,
                "rendered_context": comp.rendered_context,
                "tokens_before": comp.tokens_before,
                "tokens_after": comp.tokens_after,
                "compression_ratio": comp.compression_ratio,
                "witness_predicate_retained": comp.witness_predicate_retained,
                "pinned_counterexample_count": comp.pinned_counterexample_count,
            }

        if name == "cegar_query_ledger":
            task_id = str(args["task_id"])
            include_resolved = bool(args.get("include_resolved", True))
            target_file = args.get("target_file")
            target_symbol = args.get("target_symbol")
            records = self.ledger.get_by_task(task_id, include_resolved=include_resolved)
            if target_file:
                records = [r for r in records if r.target_file == target_file]
            if target_symbol:
                records = [r for r in records if r.target_symbol == target_symbol]
            return {
                "task_id": task_id,
                "count": len(records),
                "counterexamples": [asdict(r) for r in records],
            }

        raise ValueError(f"Unknown MCP tool: {name}")

    def serve_stdio(
        self,
        in_stream: Optional[IO[str]] = None,
        out_stream: Optional[IO[str]] = None,
    ) -> None:
        """Runs the JSON-RPC 2.0 loop over newline-delimited stdio."""
        reader = in_stream or sys.stdin
        writer = out_stream or sys.stdout
        for raw_line in reader:
            line = raw_line.strip()
            if not line:
                continue
            try:
                req = json.loads(line)
            except json.JSONDecodeError as exc:
                err_resp = {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {"code": -32700, "message": f"Parse error: {exc}"},
                }
                writer.write(json.dumps(err_resp) + "\n")
                writer.flush()
                continue

            resp = self.handle_request(req)
            if resp is not None:
                writer.write(json.dumps(resp) + "\n")
                writer.flush()

    def close(self) -> None:
        self.ledger.close()
