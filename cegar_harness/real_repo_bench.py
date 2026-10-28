"""Multi-File Real Git Repository Evaluation Benchmark (`cegar-harness repo-eval`).

Instantiates 6 real multi-file Git repositories (`pkg/models.py`, `pkg/validators.py`,
`pkg/service.py`, `tests/test_suite.py`) with Git history, records cross-module counterexample
witnesses, verifies pre-execution `RegressionGate` interception and atomic Git rollback
(`git status --porcelain == ""`) via `GitWorkspaceAdapter`, and validates multi-file patch
resolution.
"""

from __future__ import annotations

import json
import statistics
import subprocess
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from cegar_harness.ast_filter import compute_canonical_ast_hash
from cegar_harness.git_workspace import GitWorkspaceAdapter
from cegar_harness.ledger import CounterexampleLedger
from cegar_harness.models import CounterexampleRecord, GateStatus
from cegar_harness.replay import IsolatedTestRunner


@dataclass
class MultiFileRepoSpec:
    """Specification of a multi-file Git repository benchmark scenario."""

    repo_id: str
    repo_name: str
    description: str
    contract_version: str
    initial_committed_files: Dict[str, str]
    pre_compaction_buggy_files: Dict[str, str]
    post_compaction_regressive_files: Dict[str, str]
    post_compaction_valid_files: Dict[str, str]
    witness_name: str
    witness_test_code: str
    full_test_suite_code: str


@dataclass
class RepoEvalResult:
    """Empirical evaluation outcome for a single multi-file Git repository."""

    repo_id: str
    repo_name: str
    files_count: int
    initial_commit_sha: str
    recorded_ce_id: str
    witness_failure_predicate: str
    regression_gate_status: str
    regression_triggered_by: str
    regression_gate_latency_ms: float
    regression_replay_latency_ms: float
    atomic_rollback_verified: bool
    git_status_clean_after_rollback: bool
    files_identical_after_rollback: bool
    valid_patch_gate_status: str
    valid_patch_gate_latency_ms: float
    valid_patch_applied: bool
    full_test_suite_passed: bool
    diff_lines_changed: int


def get_multi_file_repo_specs() -> List[MultiFileRepoSpec]:
    """Returns 6 multi-file Git repository benchmark scenarios."""
    return [
        MultiFileRepoSpec(
            repo_id="REPO-01",
            repo_name="billing_engine",
            description="Multi-module invoice billing engine with 100% discount (0-cent net total) falsy fallback bug across validators.py and service.py",
            contract_version="v1",
            initial_committed_files={
                "pkg/__init__.py": '"""Billing engine package."""\n',
                "pkg/models.py": (
                    "from dataclasses import dataclass\n\n"
                    "@dataclass\n"
                    "class Invoice:\n"
                    "    subtotal_cents: int\n"
                    "    discount_bps: int = 0\n"
                ),
                "pkg/validators.py": (
                    "def compute_discounted_cents(subtotal_cents: int, discount_bps: int) -> int:\n"
                    "    if subtotal_cents < 0 or not (0 <= discount_bps <= 10000):\n"
                    "        raise ValueError('Invalid invoice parameters')\n"
                    "    return (subtotal_cents * (10000 - discount_bps)) // 10000\n"
                ),
                "pkg/service.py": (
                    "from pkg.models import Invoice\n"
                    "from pkg.validators import compute_discounted_cents\n\n"
                    "def finalize_invoice_total(inv: Invoice, fallback_cents: int = 500) -> int:\n"
                    "    net = compute_discounted_cents(inv.subtotal_cents, inv.discount_bps)\n"
                    "    if not net:\n"
                    "        return fallback_cents\n"
                    "    return net\n"
                ),
            },
            pre_compaction_buggy_files={
                "pkg/service.py": (
                    "from pkg.models import Invoice\n"
                    "from pkg.validators import compute_discounted_cents\n\n"
                    "def finalize_invoice_total(inv: Invoice, fallback_cents: int = 500) -> int:\n"
                    "    net = compute_discounted_cents(inv.subtotal_cents, inv.discount_bps)\n"
                    "    if not net:\n"
                    "        return fallback_cents\n"
                    "    return net\n"
                ),
            },
            post_compaction_regressive_files={
                "pkg/validators.py": (
                    "def compute_discounted_cents(subtotal_cents: int, discount_bps: int) -> int:\n"
                    "    if subtotal_cents < 0 or discount_bps < 0 or discount_bps > 10000:\n"
                    "        raise ValueError('Invalid invoice parameters')\n"
                    "    return int(subtotal_cents * (10000 - discount_bps) // 10000)\n"
                ),
                "pkg/service.py": (
                    "from pkg.models import Invoice\n"
                    "from pkg.validators import compute_discounted_cents\n\n"
                    "def finalize_invoice_total(inv: Invoice, fallback_cents: int = 500) -> int:\n"
                    "    net = compute_discounted_cents(inv.subtotal_cents, inv.discount_bps)\n"
                    "    return net or fallback_cents\n"
                ),
            },
            post_compaction_valid_files={
                "pkg/validators.py": (
                    "def compute_discounted_cents(subtotal_cents: int, discount_bps: int) -> int:\n"
                    "    if subtotal_cents < 0 or not (0 <= discount_bps <= 10000):\n"
                    "        raise ValueError('Invalid invoice parameters')\n"
                    "    return (subtotal_cents * (10000 - discount_bps)) // 10000\n"
                ),
                "pkg/service.py": (
                    "from pkg.models import Invoice\n"
                    "from pkg.validators import compute_discounted_cents\n\n"
                    "def finalize_invoice_total(inv: Invoice, fallback_cents: int = 500) -> int:\n"
                    "    if inv is None:\n"
                    "        return fallback_cents\n"
                    "    return compute_discounted_cents(inv.subtotal_cents, inv.discount_bps)\n"
                ),
            },
            witness_name="test_full_discount_zero_cents_preserved",
            witness_test_code=(
                "from pkg.models import Invoice\n"
                "from pkg.service import finalize_invoice_total\n\n"
                "def test_full_discount_zero_cents_preserved():\n"
                "    inv = Invoice(subtotal_cents=2500, discount_bps=10000)\n"
                "    assert finalize_invoice_total(inv, fallback_cents=500) == 0\n"
            ),
            full_test_suite_code=(
                "import pytest\n"
                "from pkg.models import Invoice\n"
                "from pkg.service import finalize_invoice_total\n\n"
                "def test_full_discount_zero_cents_preserved():\n"
                "    assert finalize_invoice_total(Invoice(2500, 10000), 500) == 0\n\n"
                "def test_partial_discount_and_invalid():\n"
                "    assert finalize_invoice_total(Invoice(2000, 2500), 500) == 1500\n"
                "    with pytest.raises(ValueError):\n"
                "        finalize_invoice_total(Invoice(1000, 12000))\n"
            ),
        ),
        MultiFileRepoSpec(
            repo_id="REPO-02",
            repo_name="auth_session_manager",
            description="Cross-module session token expiry unit mismatch (milliseconds in models.py vs seconds in validators.py)",
            contract_version="v1",
            initial_committed_files={
                "pkg/__init__.py": '"""Auth session package."""\n',
                "pkg/models.py": (
                    "from dataclasses import dataclass\n\n"
                    "@dataclass\n"
                    "class SessionToken:\n"
                    "    user_id: str\n"
                    "    issued_at_ms: int\n"
                    "    ttl_seconds: int\n\n"
                    "    @property\n"
                    "    def expires_at_ms(self) -> int:\n"
                    "        return self.issued_at_ms + self.ttl_seconds * 1000\n"
                ),
                "pkg/validators.py": (
                    "from pkg.models import SessionToken\n\n"
                    "def is_session_active(token: SessionToken, now_seconds: int) -> bool:\n"
                    "    return now_seconds < token.expires_at_ms\n"
                ),
                "pkg/service.py": (
                    "from pkg.models import SessionToken\n"
                    "from pkg.validators import is_session_active\n\n"
                    "def authorize_session(user_id: str, issued_at_ms: int, ttl_seconds: int, now_seconds: int) -> bool:\n"
                    "    if not user_id or ttl_seconds <= 0:\n"
                    "        return False\n"
                    "    tok = SessionToken(user_id=user_id, issued_at_ms=issued_at_ms, ttl_seconds=ttl_seconds)\n"
                    "    return is_session_active(tok, now_seconds)\n"
                ),
            },
            pre_compaction_buggy_files={
                "pkg/validators.py": (
                    "from pkg.models import SessionToken\n\n"
                    "def is_session_active(token: SessionToken, now_seconds: int) -> bool:\n"
                    "    return now_seconds < token.expires_at_ms\n"
                ),
            },
            post_compaction_regressive_files={
                "pkg/validators.py": (
                    "from pkg.models import SessionToken\n\n"
                    "def is_session_active(tok: SessionToken, current_sec: int) -> bool:\n"
                    "    return bool(tok.expires_at_ms > current_sec)\n"
                ),
            },
            post_compaction_valid_files={
                "pkg/validators.py": (
                    "from pkg.models import SessionToken\n\n"
                    "def is_session_active(token: SessionToken, now_seconds: int) -> bool:\n"
                    "    return (now_seconds * 1000) < token.expires_at_ms\n"
                ),
            },
            witness_name="test_expired_session_rejected_with_ms_conversion",
            witness_test_code=(
                "from pkg.service import authorize_session\n\n"
                "def test_expired_session_rejected_with_ms_conversion():\n"
                "    assert authorize_session('u1', issued_at_ms=1_000_000, ttl_seconds=60, now_seconds=1_100) is False\n"
            ),
            full_test_suite_code=(
                "from pkg.service import authorize_session\n\n"
                "def test_expired_session_rejected_with_ms_conversion():\n"
                "    assert authorize_session('u1', issued_at_ms=1_000_000, ttl_seconds=60, now_seconds=1_100) is False\n\n"
                "def test_active_and_boundary_sessions():\n"
                "    assert authorize_session('u1', issued_at_ms=1_000_000, ttl_seconds=60, now_seconds=1_030) is True\n"
                "    assert authorize_session('u1', issued_at_ms=1_000_000, ttl_seconds=60, now_seconds=1_060) is False\n"
                "    assert authorize_session('', issued_at_ms=1_000_000, ttl_seconds=60, now_seconds=1_010) is False\n"
            ),
        ),
        MultiFileRepoSpec(
            repo_id="REPO-03",
            repo_name="rate_limiter_gateway",
            description="Cross-module tuple return unpacking bug between validators.check_quota and service.dispatch_request",
            contract_version="v1",
            initial_committed_files={
                "pkg/__init__.py": '"""Rate limiter gateway package."""\n',
                "pkg/models.py": (
                    "from dataclasses import dataclass\n\n"
                    "@dataclass\n"
                    "class QuotaBucket:\n"
                    "    client_id: str\n"
                    "    used: int\n"
                    "    limit: int\n"
                ),
                "pkg/validators.py": (
                    "from typing import Tuple\n"
                    "from pkg.models import QuotaBucket\n\n"
                    "def check_quota(bucket: QuotaBucket) -> Tuple[bool, int]:\n"
                    "    remaining = max(0, bucket.limit - bucket.used)\n"
                    "    return (bucket.used < bucket.limit, remaining)\n"
                ),
                "pkg/service.py": (
                    "from pkg.models import QuotaBucket\n"
                    "from pkg.validators import check_quota\n\n"
                    "def dispatch_request(bucket: QuotaBucket) -> int:\n"
                    "    if check_quota(bucket):\n"
                    "        return 200\n"
                    "    return 429\n"
                ),
            },
            pre_compaction_buggy_files={
                "pkg/service.py": (
                    "from pkg.models import QuotaBucket\n"
                    "from pkg.validators import check_quota\n\n"
                    "def dispatch_request(bucket: QuotaBucket) -> int:\n"
                    "    if check_quota(bucket):\n"
                    "        return 200\n"
                    "    return 429\n"
                ),
            },
            post_compaction_regressive_files={
                "pkg/service.py": (
                    "from pkg.models import QuotaBucket\n"
                    "from pkg.validators import check_quota\n\n"
                    "def dispatch_request(b: QuotaBucket) -> int:\n"
                    "    res = check_quota(b)\n"
                    "    return 200 if bool(res) else 429\n"
                ),
            },
            post_compaction_valid_files={
                "pkg/service.py": (
                    "from pkg.models import QuotaBucket\n"
                    "from pkg.validators import check_quota\n\n"
                    "def dispatch_request(bucket: QuotaBucket) -> int:\n"
                    "    allowed, _ = check_quota(bucket)\n"
                    "    return 200 if allowed else 429\n"
                ),
            },
            witness_name="test_exhausted_bucket_returns_429",
            witness_test_code=(
                "from pkg.models import QuotaBucket\n"
                "from pkg.service import dispatch_request\n\n"
                "def test_exhausted_bucket_returns_429():\n"
                "    b = QuotaBucket(client_id='c1', used=10, limit=10)\n"
                "    assert dispatch_request(b) == 429\n"
            ),
            full_test_suite_code=(
                "from pkg.models import QuotaBucket\n"
                "from pkg.service import dispatch_request\n\n"
                "def test_exhausted_bucket_returns_429():\n"
                "    assert dispatch_request(QuotaBucket('c1', 10, 10)) == 429\n"
                "    assert dispatch_request(QuotaBucket('c1', 15, 10)) == 429\n\n"
                "def test_available_bucket_returns_200():\n"
                "    assert dispatch_request(QuotaBucket('c1', 9, 10)) == 200\n"
            ),
        ),
        MultiFileRepoSpec(
            repo_id="REPO-04",
            repo_name="config_hierarchy_loader",
            description="Multi-module configuration override merger dropping falsy 0 and False overrides across validators.py and service.py",
            contract_version="v1",
            initial_committed_files={
                "pkg/__init__.py": '"""Config hierarchy package."""\n',
                "pkg/models.py": (
                    "from dataclasses import dataclass\n"
                    "from typing import Any, Dict\n\n"
                    "@dataclass\n"
                    "class ConfigLayer:\n"
                    "    defaults: Dict[str, Any]\n"
                    "    overrides: Dict[str, Any]\n"
                ),
                "pkg/validators.py": (
                    "from typing import Any\n\n"
                    "def pick_effective_value(default_val: Any, override_val: Any) -> Any:\n"
                    "    if override_val:\n"
                    "        return override_val\n"
                    "    return default_val\n"
                ),
                "pkg/service.py": (
                    "from typing import Any, Dict\n"
                    "from pkg.models import ConfigLayer\n"
                    "from pkg.validators import pick_effective_value\n\n"
                    "def resolve_config(layer: ConfigLayer) -> Dict[str, Any]:\n"
                    "    merged: Dict[str, Any] = {}\n"
                    "    for k, def_v in layer.defaults.items():\n"
                    "        ov_v = layer.overrides.get(k, None)\n"
                    "        merged[k] = pick_effective_value(def_v, ov_v)\n"
                    "    return merged\n"
                ),
            },
            pre_compaction_buggy_files={
                "pkg/validators.py": (
                    "from typing import Any\n\n"
                    "def pick_effective_value(default_val: Any, override_val: Any) -> Any:\n"
                    "    if override_val:\n"
                    "        return override_val\n"
                    "    return default_val\n"
                ),
            },
            post_compaction_regressive_files={
                "pkg/validators.py": (
                    "from typing import Any\n\n"
                    "def pick_effective_value(default_val: Any, override_val: Any) -> Any:\n"
                    "    return override_val or default_val\n"
                ),
            },
            post_compaction_valid_files={
                "pkg/validators.py": (
                    "from typing import Any\n\n"
                    "def pick_effective_value(default_val: Any, override_val: Any) -> Any:\n"
                    "    return default_val if override_val is None else override_val\n"
                ),
            },
            witness_name="test_zero_and_false_overrides_retained",
            witness_test_code=(
                "from pkg.models import ConfigLayer\n"
                "from pkg.service import resolve_config\n\n"
                "def test_zero_and_false_overrides_retained():\n"
                "    layer = ConfigLayer(defaults={'retries': 3, 'tls': True}, overrides={'retries': 0, 'tls': False})\n"
                "    assert resolve_config(layer) == {'retries': 0, 'tls': False}\n"
            ),
            full_test_suite_code=(
                "from pkg.models import ConfigLayer\n"
                "from pkg.service import resolve_config\n\n"
                "def test_zero_and_false_overrides_retained():\n"
                "    layer = ConfigLayer(defaults={'retries': 3, 'tls': True, 'host': 'localhost'}, overrides={'retries': 0, 'tls': False})\n"
                "    assert resolve_config(layer) == {'retries': 0, 'tls': False, 'host': 'localhost'}\n"
            ),
        ),
        MultiFileRepoSpec(
            repo_id="REPO-05",
            repo_name="dag_workflow_scheduler",
            description="Multi-module DAG cycle detector and shortest-hop planner infinite loop on cyclic unreachable nodes",
            contract_version="v1",
            initial_committed_files={
                "pkg/__init__.py": '"""DAG workflow package."""\n',
                "pkg/models.py": (
                    "from dataclasses import dataclass\n"
                    "from typing import Dict, List\n\n"
                    "@dataclass\n"
                    "class WorkflowGraph:\n"
                    "    edges: Dict[str, List[str]]\n"
                ),
                "pkg/validators.py": (
                    "from typing import List\n"
                    "from pkg.models import WorkflowGraph\n\n"
                    "def next_hops(graph: WorkflowGraph, node: str) -> List[str]:\n"
                    "    return list(graph.edges.get(node, []))\n"
                ),
                "pkg/service.py": (
                    "from collections import deque\n"
                    "from pkg.models import WorkflowGraph\n"
                    "from pkg.validators import next_hops\n\n"
                    "def shortest_execution_chain(graph: WorkflowGraph, start: str, target: str) -> int:\n"
                    "    if start == target:\n"
                    "        return 0\n"
                    "    q = deque([(start, 0)])\n"
                    "    steps = 0\n"
                    "    while q and steps < 50:\n"
                    "        steps += 1\n"
                    "        curr, dist = q.popleft()\n"
                    "        for nxt in next_hops(graph, curr):\n"
                    "            if nxt == target:\n"
                    "                return dist + 1\n"
                    "            q.append((nxt, dist + 1))\n"
                    "    return -2 if steps >= 50 else -1\n"
                ),
            },
            pre_compaction_buggy_files={
                "pkg/service.py": (
                    "from collections import deque\n"
                    "from pkg.models import WorkflowGraph\n"
                    "from pkg.validators import next_hops\n\n"
                    "def shortest_execution_chain(graph: WorkflowGraph, start: str, target: str) -> int:\n"
                    "    if start == target:\n"
                    "        return 0\n"
                    "    q = deque([(start, 0)])\n"
                    "    steps = 0\n"
                    "    while q and steps < 50:\n"
                    "        steps += 1\n"
                    "        curr, dist = q.popleft()\n"
                    "        for nxt in next_hops(graph, curr):\n"
                    "            if nxt == target:\n"
                    "                return dist + 1\n"
                    "            q.append((nxt, dist + 1))\n"
                    "    return -2 if steps >= 50 else -1\n"
                ),
            },
            post_compaction_regressive_files={
                "pkg/service.py": (
                    "from collections import deque\n"
                    "from pkg.models import WorkflowGraph\n"
                    "from pkg.validators import next_hops\n\n"
                    "def shortest_execution_chain(g: WorkflowGraph, s: str, t: str) -> int:\n"
                    "    if s == t:\n"
                    "        return 0\n"
                    "    queue = deque([(s, 0)])\n"
                    "    iters = 0\n"
                    "    while queue and iters < 50:\n"
                    "        iters += 1\n"
                    "        node, d = queue.popleft()\n"
                    "        for nb in next_hops(g, node):\n"
                    "            if nb == t:\n"
                    "                return d + 1\n"
                    "            queue.append((nb, d + 1))\n"
                    "    return -2 if iters >= 50 else -1\n"
                ),
            },
            post_compaction_valid_files={
                "pkg/service.py": (
                    "from collections import deque\n"
                    "from pkg.models import WorkflowGraph\n"
                    "from pkg.validators import next_hops\n\n"
                    "def shortest_execution_chain(graph: WorkflowGraph, start: str, target: str) -> int:\n"
                    "    if start == target:\n"
                    "        return 0\n"
                    "    visited = {start}\n"
                    "    q = deque([(start, 0)])\n"
                    "    while q:\n"
                    "        curr, dist = q.popleft()\n"
                    "        for nxt in next_hops(graph, curr):\n"
                    "            if nxt == target:\n"
                    "                return dist + 1\n"
                    "            if nxt not in visited:\n"
                    "                visited.add(nxt)\n"
                    "                q.append((nxt, dist + 1))\n"
                    "    return -1\n"
                ),
            },
            witness_name="test_cyclic_unreachable_returns_minus_one",
            witness_test_code=(
                "from pkg.models import WorkflowGraph\n"
                "from pkg.service import shortest_execution_chain\n\n"
                "def test_cyclic_unreachable_returns_minus_one():\n"
                "    g = WorkflowGraph(edges={'A': ['B'], 'B': ['A']})\n"
                "    assert shortest_execution_chain(g, 'A', 'Z') == -1\n"
            ),
            full_test_suite_code=(
                "from pkg.models import WorkflowGraph\n"
                "from pkg.service import shortest_execution_chain\n\n"
                "def test_cyclic_unreachable_returns_minus_one():\n"
                "    g = WorkflowGraph(edges={'A': ['B'], 'B': ['A'], 'C': ['D']})\n"
                "    assert shortest_execution_chain(g, 'A', 'Z') == -1\n"
                "    assert shortest_execution_chain(g, 'A', 'A') == 0\n"
                "    assert shortest_execution_chain(g, 'A', 'B') == 1\n"
            ),
        ),
        MultiFileRepoSpec(
            repo_id="REPO-06",
            repo_name="ledger_currency_settlement",
            description="Multi-module FX settlement validator failing to reject IEEE-754 NaN/Inf rates because NaN <= 0 evaluates to False",
            contract_version="v1",
            initial_committed_files={
                "pkg/__init__.py": '"""Currency settlement package."""\n',
                "pkg/models.py": (
                    "from dataclasses import dataclass\n\n"
                    "@dataclass\n"
                    "class TransferOrder:\n"
                    "    amount_usd: float\n"
                    "    fx_rate: float\n"
                ),
                "pkg/validators.py": (
                    "def validate_fx_rate(rate: float) -> float:\n"
                    "    if rate <= 0.0:\n"
                    "        raise ValueError('FX rate must be positive')\n"
                    "    return float(rate)\n"
                ),
                "pkg/service.py": (
                    "from pkg.models import TransferOrder\n"
                    "from pkg.validators import validate_fx_rate\n\n"
                    "def settle_transfer(order: TransferOrder) -> float:\n"
                    "    r = validate_fx_rate(order.fx_rate)\n"
                    "    if order.amount_usd < 0.0:\n"
                    "        raise ValueError('Negative amount')\n"
                    "    return round(order.amount_usd * r, 2)\n"
                ),
            },
            pre_compaction_buggy_files={
                "pkg/validators.py": (
                    "def validate_fx_rate(rate: float) -> float:\n"
                    "    if rate <= 0.0:\n"
                    "        raise ValueError('FX rate must be positive')\n"
                    "    return float(rate)\n"
                ),
            },
            post_compaction_regressive_files={
                "pkg/validators.py": (
                    "def validate_fx_rate(fx: float) -> float:\n"
                    "    if fx < 0.0 or fx == 0.0:\n"
                    "        raise ValueError('FX rate must be positive')\n"
                    "    return float(fx)\n"
                ),
            },
            post_compaction_valid_files={
                "pkg/validators.py": (
                    "import math\n\n"
                    "def validate_fx_rate(rate: float) -> float:\n"
                    "    if not math.isfinite(rate) or rate <= 0.0:\n"
                    "        raise ValueError('FX rate must be finite and positive')\n"
                    "    return float(rate)\n"
                ),
            },
            witness_name="test_nan_and_inf_fx_rate_rejected",
            witness_test_code=(
                "import pytest\n"
                "from pkg.models import TransferOrder\n"
                "from pkg.service import settle_transfer\n\n"
                "def test_nan_and_inf_fx_rate_rejected():\n"
                "    with pytest.raises(ValueError):\n"
                "        settle_transfer(TransferOrder(amount_usd=100.0, fx_rate=float('nan')))\n"
                "    with pytest.raises(ValueError):\n"
                "        settle_transfer(TransferOrder(amount_usd=100.0, fx_rate=float('inf')))\n"
            ),
            full_test_suite_code=(
                "import pytest\n"
                "from pkg.models import TransferOrder\n"
                "from pkg.service import settle_transfer\n\n"
                "def test_nan_and_inf_fx_rate_rejected():\n"
                "    for bad in (float('nan'), float('inf'), float('-inf'), 0.0, -1.2):\n"
                "        with pytest.raises(ValueError):\n"
                "            settle_transfer(TransferOrder(amount_usd=100.0, fx_rate=bad))\n\n"
                "def test_valid_fx_settlement():\n"
                "    assert settle_transfer(TransferOrder(amount_usd=100.0, fx_rate=0.925)) == 92.5\n"
            ),
        ),
    ]


def _init_git_repo(repo_dir: Path, files: Dict[str, str], test_suite: str) -> str:
    """Initializes a real Git repository with committed multi-file package and test suite."""
    subprocess.run(["git", "init"], cwd=str(repo_dir), check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "cegar-bench@example.com"],
        cwd=str(repo_dir),
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "CEGAR Benchmark"],
        cwd=str(repo_dir),
        check=True,
        capture_output=True,
    )
    for rel_path, content in files.items():
        target = repo_dir / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    test_file = repo_dir / "tests" / "test_suite.py"
    test_file.parent.mkdir(parents=True, exist_ok=True)
    test_file.write_text(test_suite, encoding="utf-8")

    subprocess.run(["git", "add", "."], cwd=str(repo_dir), check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "initial multi-file package layout"],
        cwd=str(repo_dir),
        check=True,
        capture_output=True,
    )
    rev = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        cwd=str(repo_dir),
        check=True,
        capture_output=True,
        text=True,
    )
    return rev.stdout.strip()


def run_multi_file_repo_benchmark(output_dir: Optional[str | Path] = "results") -> Dict[str, Any]:
    """Executes the 6-repository multi-file Git workspace benchmark and saves `real_repo_eval.json`."""
    specs = get_multi_file_repo_specs()
    runner = IsolatedTestRunner(timeout_seconds=5.0)
    results: List[RepoEvalResult] = []

    with tempfile.TemporaryDirectory(prefix="cegar_real_repos_") as tmp_root:
        root_path = Path(tmp_root)
        ledger = CounterexampleLedger(root_path / "repo_bench_ledger.sqlite")

        for spec in specs:
            repo_dir = root_path / spec.repo_name
            repo_dir.mkdir(parents=True, exist_ok=True)
            commit_sha = _init_git_repo(repo_dir, spec.initial_committed_files, spec.full_test_suite_code)

            # 1. Pre-compaction failure discovery on the multi-file repository state
            pre_state = dict(spec.initial_committed_files)
            pre_state.update(spec.pre_compaction_buggy_files)
            wit_res = runner.run_test_code(pre_state, spec.witness_test_code)
            if wit_res.passed:
                raise RuntimeError(f"Pre-compaction state for {spec.repo_id} unexpectedly passed witness.")

            ce_id = f"CE-{spec.repo_id}-01"
            primary_file = sorted(spec.pre_compaction_buggy_files.keys())[0]
            ce = CounterexampleRecord(
                ce_id=ce_id,
                task_id=spec.repo_id,
                target_file=primary_file,
                target_symbol=spec.repo_name,
                contract_version=spec.contract_version,
                ast_hash=compute_canonical_ast_hash(pre_state),
                witness_name=spec.witness_name,
                witness_test_code=spec.witness_test_code,
                failure_predicate=wit_res.failure_predicate,
                discovered_at_step=2,
            )
            ledger.record(ce)

            # Snapshot committed files on disk to verify byte-for-byte restoration after rollback
            committed_snapshot = {
                rel: (repo_dir / rel).read_text(encoding="utf-8")
                for rel in spec.initial_committed_files
            }

            adapter = GitWorkspaceAdapter(repo_path=repo_dir, ledger=ledger, runner=runner)

            # 2. Apply post-compaction regressive multi-file patch via GitWorkspaceAdapter
            tx_reg = adapter.apply_candidate_with_gate(
                task_id=spec.repo_id,
                candidate_files=spec.post_compaction_regressive_files,
                contract_version=spec.contract_version,
            )
            git_status_after_rb = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=str(repo_dir),
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()

            files_restored = all(
                (repo_dir / rel).read_text(encoding="utf-8") == orig_text
                for rel, orig_text in committed_snapshot.items()
            )
            rollback_ok = (
                tx_reg.decision.status == GateStatus.REGRESSION_DETECTED
                and not tx_reg.applied
                and tx_reg.rolled_back
                and git_status_after_rb == ""
                and files_restored
            )

            # 3. Apply post-compaction valid multi-file patch via GitWorkspaceAdapter
            tx_fix = adapter.apply_candidate_with_gate(
                task_id=spec.repo_id,
                candidate_files=spec.post_compaction_valid_files,
                contract_version=spec.contract_version,
            )
            diff_lines = len(
                [
                    ln
                    for ln in tx_fix.git_diff.splitlines()
                    if (ln.startswith("+") or ln.startswith("-"))
                    and not ln.startswith("+++")
                    and not ln.startswith("---")
                ]
            )

            # Verify full multi-file repository test suite on the applied Git working tree
            current_repo_files = {
                rel: (repo_dir / rel).read_text(encoding="utf-8")
                for rel in spec.initial_committed_files
            }
            suite_res = runner.run_test_code(current_repo_files, spec.full_test_suite_code)

            results.append(
                RepoEvalResult(
                    repo_id=spec.repo_id,
                    repo_name=spec.repo_name,
                    files_count=len(spec.initial_committed_files) + 1,  # + tests/test_suite.py
                    initial_commit_sha=commit_sha,
                    recorded_ce_id=ce_id,
                    witness_failure_predicate=wit_res.failure_predicate,
                    regression_gate_status=tx_reg.decision.status.value,
                    regression_triggered_by=tx_reg.decision.triggered_by,
                    regression_gate_latency_ms=tx_reg.decision.latency_ms,
                    regression_replay_latency_ms=tx_reg.decision.replay_latency_ms,
                    atomic_rollback_verified=rollback_ok,
                    git_status_clean_after_rollback=(git_status_after_rb == ""),
                    files_identical_after_rollback=files_restored,
                    valid_patch_gate_status=tx_fix.decision.status.value,
                    valid_patch_gate_latency_ms=tx_fix.decision.latency_ms,
                    valid_patch_applied=tx_fix.applied,
                    full_test_suite_passed=suite_res.passed,
                    diff_lines_changed=diff_lines,
                )
            )

        ledger.close()

    reg_latencies = [r.regression_gate_latency_ms for r in results]
    fix_latencies = [r.valid_patch_gate_latency_ms for r in results]
    summary = {
        "generated_at_epoch": time.time(),
        "repositories_evaluated": len(results),
        "regressions_intercepted": sum(
            1 for r in results if r.regression_gate_status == GateStatus.REGRESSION_DETECTED.value
        ),
        "atomic_rollbacks_verified": sum(1 for r in results if r.atomic_rollback_verified),
        "atomic_rollback_rate_pct": round(
            (sum(1 for r in results if r.atomic_rollback_verified) / len(results)) * 100.0, 2
        ),
        "valid_patches_resolved": sum(
            1 for r in results if r.valid_patch_applied and r.full_test_suite_passed
        ),
        "resolution_rate_pct": round(
            (
                sum(1 for r in results if r.valid_patch_applied and r.full_test_suite_passed)
                / len(results)
            )
            * 100.0,
            2,
        ),
        "median_regression_gate_latency_ms": round(statistics.median(reg_latencies), 2),
        "median_valid_gate_latency_ms": round(statistics.median(fix_latencies), 2),
        "repositories": [asdict(r) for r in results],
    }

    if output_dir:
        out_p = Path(output_dir)
        out_p.mkdir(parents=True, exist_ok=True)
        (out_p / "real_repo_eval.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    return summary
