"""Core data models and enums for CEGAR-Harness."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class GateStatus(str, Enum):
    """Three-state outcome of the Regression Gate evaluation."""

    PASS = "PASS"
    REGRESSION_DETECTED = "REGRESSION_DETECTED"
    INCONCLUSIVE = "INCONCLUSIVE"


class CompactionStrategy(str, Enum):
    """Supported context compaction strategies for empirical comparison."""

    FULL_HISTORY = "FULL_HISTORY"
    OBSERVATION_MASKING = "OBSERVATION_MASKING"
    LOSSY_SUMMARY = "LOSSY_SUMMARY"
    CEGAR_LEDGER_ONLY = "CEGAR_LEDGER_ONLY"
    CEGAR_HARNESS_FULL = "CEGAR_HARNESS_FULL"


class BugCategory(str, Enum):
    """Six benchmark categories of Python code-repair tasks."""

    BOUNDARY_CONDITIONS = "1_boundary_conditions"
    PARSERS_STATE_MACHINES = "2_parsers_state_machines"
    EXCEPTION_HANDLING = "3_exception_handling"
    MULTI_FILE_CHANGES = "4_multi_file_changes"
    FEATURE_REGRESSIONS = "5_feature_regressions"
    SYNTACTIC_VARIANTS = "6_syntactic_variants"


@dataclass
class CounterexampleRecord:
    """Versioned counterexample witness stored in the persistent SQLite ledger."""

    ce_id: str
    task_id: str
    target_file: str
    target_symbol: str
    contract_version: str
    ast_hash: str
    witness_name: str
    witness_test_code: str
    failure_predicate: str
    discovered_at_step: int
    status: str = "ACTIVE"  # ACTIVE, RESOLVED, OBSOLETE
    provenance: str = "oracle_test_failure"


@dataclass
class GateEvaluationResult:
    """Detailed result returned by the Regression Gate before full test execution."""

    status: GateStatus
    triggered_by: str  # "none", "ast_filter", "witness_replay", "contract_mismatch", "replay_error"
    matched_ce_id: Optional[str] = None
    reason: str = ""
    latency_ms: float = 0.0
    witnesses_checked: int = 0
    ast_hash: str = ""


@dataclass
class CandidatePatch:
    """A candidate code patch proposed during a repair trajectory."""

    patch_id: str
    description: str
    files: Dict[str, str]
    is_known_regression: bool
    is_valid_solution: bool
    contract_version: str
    syntactic_variant_of: Optional[str] = None


@dataclass
class TaskSpec:
    """Complete specification for a deterministic code-repair benchmark task."""

    task_id: str
    category: BugCategory
    title: str
    specification: str
    contract_version_initial: str
    contract_version_post_compaction: str
    target_file: str
    target_symbol: str
    initial_files: Dict[str, str]
    reference_test_code: str
    witness_name: str
    witness_test_code: str
    pre_compaction_failed_patch: CandidatePatch
    verbose_observations: List[str]
    post_compaction_candidates: List[CandidatePatch]
    metadata: Dict[str, Any] = field(default_factory=dict)
