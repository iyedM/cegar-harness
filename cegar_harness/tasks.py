"""Deterministic 30-task Python code-repair benchmark across 6 bug categories."""

from __future__ import annotations

from typing import Dict, List

from cegar_harness.models import BugCategory, CandidatePatch, TaskSpec


def _make_verbose_observations(task_id: str, target_file: str, target_symbol: str) -> List[str]:
    """Generates realistic multi-turn tool logs prior to context compaction."""
    return [
        (
            f"[TOOL: repo_search] Searching references for `{target_symbol}` across workspace ({task_id}).\n"
            f"Found definition in `{target_file}` and 14 call-sites in downstream integration modules.\n"
            + ("# context line: module dependency inspection and static type check output\n" * 12)
        ),
        (
            f"[TOOL: ast_inspect] Analyzing control-flow graph and local symbol bindings for `{target_file}::{target_symbol}`.\n"
            "Locals: ['res', 'idx', 'val', 'acc', 'state'] | Cyclomatic complexity: 6 | Return paths: 3.\n"
            + ("# static analyzer diagnostic trace: invariant candidate check passed on nominal path\n" * 12)
        ),
    ]


def get_all_tasks() -> List[TaskSpec]:
    """Returns the 30 deterministic Python code-repair tasks (5 per category)."""
    tasks: List[TaskSpec] = []

    # =========================================================================
    # CATEGORY 1: BOUNDARY CONDITIONS (T01 - T05)
    # =========================================================================
    tasks.append(
        TaskSpec(
            task_id="T01",
            category=BugCategory.BOUNDARY_CONDITIONS,
            title="Pagination limit clamping at zero boundary",
            specification="Implement `clamp_limit(limit: int, max_limit: int = 100) -> int` so limits <= 0 return 1 and limits > max_limit return max_limit.",
            contract_version_initial="v1",
            contract_version_post_compaction="v1",
            target_file="pagination.py",
            target_symbol="clamp_limit",
            initial_files={
                "pagination.py": "def clamp_limit(limit, max_limit=100):\n    return min(limit, max_limit)\n"
            },
            witness_name="test_zero_limit_clamped_to_one",
            witness_test_code=(
                "from pagination import clamp_limit\n"
                "def test_zero_limit_clamped_to_one():\n"
                "    assert clamp_limit(0, 100) == 1\n"
            ),
            reference_test_code=(
                "from pagination import clamp_limit\n"
                "def test_reference_suite():\n"
                "    assert clamp_limit(0, 100) == 1\n"
                "    assert clamp_limit(-10, 100) == 1\n"
                "    assert clamp_limit(25, 100) == 25\n"
                "    assert clamp_limit(250, 100) == 100\n"
            ),
            pre_compaction_failed_patch=CandidatePatch(
                patch_id="T01-pre",
                description="Uses strict < 0 instead of <= 0",
                files={
                    "pagination.py": (
                        "def clamp_limit(limit, max_limit=100):\n"
                        "    if limit < 0:\n"
                        "        return 1\n"
                        "    if limit > max_limit:\n"
                        "        return max_limit\n"
                        "    return limit\n"
                    )
                },
                is_known_regression=True,
                is_valid_solution=False,
                contract_version="v1",
            ),
            verbose_observations=_make_verbose_observations("T01", "pagination.py", "clamp_limit"),
            post_compaction_candidates=[
                CandidatePatch(
                    patch_id="T01-c1-reg",
                    description="Alpha-renamed repeat of strict < 0 boundary bug",
                    files={
                        "pagination.py": (
                            "def clamp_limit(val, upper=100):\n"
                            "    # Clamps value into range\n"
                            "    if val < 0:\n"
                            "        return 1\n"
                            "    if val > upper:\n"
                            "        return upper\n"
                            "    return val\n"
                        )
                    },
                    is_known_regression=True,
                    is_valid_solution=False,
                    contract_version="v1",
                ),
                CandidatePatch(
                    patch_id="T01-c2-fix",
                    description="Uses <= 0 boundary check",
                    files={
                        "pagination.py": (
                            "def clamp_limit(limit, max_limit=100):\n"
                            "    if limit <= 0:\n"
                            "        return 1\n"
                            "    if limit > max_limit:\n"
                            "        return max_limit\n"
                            "    return limit\n"
                        )
                    },
                    is_known_regression=False,
                    is_valid_solution=True,
                    contract_version="v1",
                ),
            ],
        )
    )

    tasks.append(
        TaskSpec(
            task_id="T02",
            category=BugCategory.BOUNDARY_CONDITIONS,
            title="Rolling window average off-by-one when len == window",
            specification="Implement `rolling_averages(values: list[float], window: int) -> list[float]` returning all contiguous window means.",
            contract_version_initial="v1",
            contract_version_post_compaction="v1",
            target_file="stats.py",
            target_symbol="rolling_averages",
            initial_files={
                "stats.py": "def rolling_averages(values, window):\n    return []\n"
            },
            witness_name="test_exact_window_size_single_average",
            witness_test_code=(
                "from stats import rolling_averages\n"
                "def test_exact_window_size_single_average():\n"
                "    assert rolling_averages([2.0, 4.0, 6.0], 3) == [4.0]\n"
            ),
            reference_test_code=(
                "from stats import rolling_averages\n"
                "def test_reference_suite():\n"
                "    assert rolling_averages([2.0, 4.0, 6.0], 3) == [4.0]\n"
                "    assert rolling_averages([1.0, 3.0, 5.0, 7.0], 2) == [2.0, 4.0, 6.0]\n"
                "    assert rolling_averages([1.0, 2.0], 5) == []\n"
            ),
            pre_compaction_failed_patch=CandidatePatch(
                patch_id="T02-pre",
                description="Off-by-one range(len(values) - window)",
                files={
                    "stats.py": (
                        "def rolling_averages(values, window):\n"
                        "    if window <= 0 or len(values) < window:\n"
                        "        return []\n"
                        "    out = []\n"
                        "    for i in range(len(values) - window):\n"
                        "        out.append(sum(values[i:i + window]) / window)\n"
                        "    return out\n"
                    )
                },
                is_known_regression=True,
                is_valid_solution=False,
                contract_version="v1",
            ),
            verbose_observations=_make_verbose_observations("T02", "stats.py", "rolling_averages"),
            post_compaction_candidates=[
                CandidatePatch(
                    patch_id="T02-c1-reg",
                    description="Alpha-renamed repeat of off-by-one range bound",
                    files={
                        "stats.py": (
                            "def rolling_averages(seq, win):\n"
                            "    if win <= 0 or len(seq) < win:\n"
                            "        return []\n"
                            "    res = []\n"
                            "    for idx in range(len(seq) - win):\n"
                            "        res.append(sum(seq[idx:idx + win]) / win)\n"
                            "    return res\n"
                        )
                    },
                    is_known_regression=True,
                    is_valid_solution=False,
                    contract_version="v1",
                ),
                CandidatePatch(
                    patch_id="T02-c2-fix",
                    description="Includes + 1 in upper range bound",
                    files={
                        "stats.py": (
                            "def rolling_averages(values, window):\n"
                            "    if window <= 0 or len(values) < window:\n"
                            "        return []\n"
                            "    return [\n"
                            "        sum(values[i:i + window]) / window\n"
                            "        for i in range(len(values) - window + 1)\n"
                            "    ]\n"
                        )
                    },
                    is_known_regression=False,
                    is_valid_solution=True,
                    contract_version="v1",
                ),
            ],
        )
    )

    tasks.append(
        TaskSpec(
            task_id="T03",
            category=BugCategory.BOUNDARY_CONDITIONS,
            title="Leftmost binary search with duplicate elements",
            specification="Implement `search_leftmost(arr: list[int], target: int) -> int` returning the smallest index i where arr[i] == target, or -1.",
            contract_version_initial="v1",
            contract_version_post_compaction="v1",
            target_file="bsearch.py",
            target_symbol="search_leftmost",
            initial_files={
                "bsearch.py": "def search_leftmost(arr, target):\n    return -1\n"
            },
            witness_name="test_leftmost_duplicate_at_index_zero",
            witness_test_code=(
                "from bsearch import search_leftmost\n"
                "def test_leftmost_duplicate_at_index_zero():\n"
                "    assert search_leftmost([5, 5, 5, 9], 5) == 0\n"
            ),
            reference_test_code=(
                "from bsearch import search_leftmost\n"
                "def test_reference_suite():\n"
                "    assert search_leftmost([5, 5, 5, 9], 5) == 0\n"
                "    assert search_leftmost([1, 2, 4, 4, 4, 8], 4) == 2\n"
                "    assert search_leftmost([1, 3, 5], 2) == -1\n"
                "    assert search_leftmost([], 1) == -1\n"
            ),
            pre_compaction_failed_patch=CandidatePatch(
                patch_id="T03-pre",
                description="Returns mid immediately on equality instead of contracting right bound",
                files={
                    "bsearch.py": (
                        "def search_leftmost(arr, target):\n"
                        "    lo = 0\n"
                        "    hi = len(arr) - 1\n"
                        "    while lo <= hi:\n"
                        "        mid = (lo + hi) // 2\n"
                        "        if arr[mid] == target:\n"
                        "            return mid\n"
                        "        if arr[mid] < target:\n"
                        "            lo = mid + 1\n"
                        "        else:\n"
                        "            hi = mid - 1\n"
                        "    return -1\n"
                    )
                },
                is_known_regression=True,
                is_valid_solution=False,
                contract_version="v1",
            ),
            verbose_observations=_make_verbose_observations("T03", "bsearch.py", "search_leftmost"),
            post_compaction_candidates=[
                CandidatePatch(
                    patch_id="T03-c1-reg",
                    description="Alpha-renamed immediate mid return on equality",
                    files={
                        "bsearch.py": (
                            "def search_leftmost(items, goal):\n"
                            "    left = 0\n"
                            "    right = len(items) - 1\n"
                            "    while left <= right:\n"
                            "        center = (left + right) // 2\n"
                            "        if items[center] == goal:\n"
                            "            return center\n"
                            "        if items[center] < goal:\n"
                            "            left = center + 1\n"
                            "        else:\n"
                            "            right = center - 1\n"
                            "    return -1\n"
                        )
                    },
                    is_known_regression=True,
                    is_valid_solution=False,
                    contract_version="v1",
                ),
                CandidatePatch(
                    patch_id="T03-c2-fix",
                    description="Contracts high bound on >= target to locate leftmost match",
                    files={
                        "bsearch.py": (
                            "def search_leftmost(arr, target):\n"
                            "    lo, hi = 0, len(arr)\n"
                            "    while lo < hi:\n"
                            "        mid = (lo + hi) // 2\n"
                            "        if arr[mid] < target:\n"
                            "            lo = mid + 1\n"
                            "        else:\n"
                            "            hi = mid\n"
                            "    if lo < len(arr) and arr[lo] == target:\n"
                            "        return lo\n"
                            "    return -1\n"
                        )
                    },
                    is_known_regression=False,
                    is_valid_solution=True,
                    contract_version="v1",
                ),
            ],
        )
    )

    tasks.append(
        TaskSpec(
            task_id="T04",
            category=BugCategory.BOUNDARY_CONDITIONS,
            title="Batch chunking on empty input list",
            specification="Implement `chunk_items(items: list, size: int) -> list[list]` returning `[]` when `items` is empty.",
            contract_version_initial="v1",
            contract_version_post_compaction="v1",
            target_file="batching.py",
            target_symbol="chunk_items",
            initial_files={
                "batching.py": "def chunk_items(items, size):\n    return [items]\n"
            },
            witness_name="test_empty_list_returns_no_batches",
            witness_test_code=(
                "from batching import chunk_items\n"
                "def test_empty_list_returns_no_batches():\n"
                "    assert chunk_items([], 3) == []\n"
            ),
            reference_test_code=(
                "from batching import chunk_items\n"
                "def test_reference_suite():\n"
                "    assert chunk_items([], 3) == []\n"
                "    assert chunk_items([1, 2, 3, 4, 5], 2) == [[1, 2], [3, 4], [5]]\n"
                "    assert chunk_items([1, 2], 5) == [[1, 2]]\n"
            ),
            pre_compaction_failed_patch=CandidatePatch(
                patch_id="T04-pre",
                description="Returns [[]] when items is empty",
                files={
                    "batching.py": (
                        "def chunk_items(items, size):\n"
                        "    if not items:\n"
                        "        return [[]]\n"
                        "    return [items[i:i + size] for i in range(0, len(items), size)]\n"
                    )
                },
                is_known_regression=True,
                is_valid_solution=False,
                contract_version="v1",
            ),
            verbose_observations=_make_verbose_observations("T04", "batching.py", "chunk_items"),
            post_compaction_candidates=[
                CandidatePatch(
                    patch_id="T04-c1-reg",
                    description="Alpha-renamed repeat returning [[]]",
                    files={
                        "batching.py": (
                            "def chunk_items(seq, batch_sz):\n"
                            "    if not seq:\n"
                            "        return [[]]\n"
                            "    return [seq[k:k + batch_sz] for k in range(0, len(seq), batch_sz)]\n"
                        )
                    },
                    is_known_regression=True,
                    is_valid_solution=False,
                    contract_version="v1",
                ),
                CandidatePatch(
                    patch_id="T04-c2-fix",
                    description="Returns empty list [] on empty input",
                    files={
                        "batching.py": (
                            "def chunk_items(items, size):\n"
                            "    if size <= 0:\n"
                            "        raise ValueError('size must be positive')\n"
                            "    if not items:\n"
                            "        return []\n"
                            "    return [items[i:i + size] for i in range(0, len(items), size)]\n"
                        )
                    },
                    is_known_regression=False,
                    is_valid_solution=True,
                    contract_version="v1",
                ),
            ],
        )
    )

    tasks.append(
        TaskSpec(
            task_id="T05",
            category=BugCategory.BOUNDARY_CONDITIONS,
            title="Inclusive discount threshold boundary",
            specification="Implement `apply_discount(subtotal: float, threshold: float = 100.0, rate: float = 0.10) -> float` applying discount when subtotal >= threshold.",
            contract_version_initial="v1",
            contract_version_post_compaction="v1",
            target_file="pricing.py",
            target_symbol="apply_discount",
            initial_files={
                "pricing.py": "def apply_discount(subtotal, threshold=100.0, rate=0.10):\n    return subtotal\n"
            },
            witness_name="test_discount_applied_at_exact_threshold",
            witness_test_code=(
                "from pricing import apply_discount\n"
                "def test_discount_applied_at_exact_threshold():\n"
                "    assert apply_discount(100.0, 100.0, 0.10) == 90.0\n"
            ),
            reference_test_code=(
                "from pricing import apply_discount\n"
                "def test_reference_suite():\n"
                "    assert apply_discount(100.0, 100.0, 0.10) == 90.0\n"
                "    assert apply_discount(200.0, 100.0, 0.10) == 180.0\n"
                "    assert apply_discount(99.99, 100.0, 0.10) == 99.99\n"
            ),
            pre_compaction_failed_patch=CandidatePatch(
                patch_id="T05-pre",
                description="Uses strict > threshold instead of >=",
                files={
                    "pricing.py": (
                        "def apply_discount(subtotal, threshold=100.0, rate=0.10):\n"
                        "    if subtotal > threshold:\n"
                        "        return round(subtotal * (1.0 - rate), 2)\n"
                        "    return subtotal\n"
                    )
                },
                is_known_regression=True,
                is_valid_solution=False,
                contract_version="v1",
            ),
            verbose_observations=_make_verbose_observations("T05", "pricing.py", "apply_discount"),
            post_compaction_candidates=[
                CandidatePatch(
                    patch_id="T05-c1-reg",
                    description="Alpha-renamed strict > comparison",
                    files={
                        "pricing.py": (
                            "def apply_discount(amount, min_spend=100.0, disc=0.10):\n"
                            "    if amount > min_spend:\n"
                            "        return round(amount * (1.0 - disc), 2)\n"
                            "    return amount\n"
                        )
                    },
                    is_known_regression=True,
                    is_valid_solution=False,
                    contract_version="v1",
                ),
                CandidatePatch(
                    patch_id="T05-c2-fix",
                    description="Uses inclusive >= comparison",
                    files={
                        "pricing.py": (
                            "def apply_discount(subtotal, threshold=100.0, rate=0.10):\n"
                            "    if subtotal >= threshold:\n"
                            "        return round(subtotal * (1.0 - rate), 2)\n"
                            "    return subtotal\n"
                        )
                    },
                    is_known_regression=False,
                    is_valid_solution=True,
                    contract_version="v1",
                ),
            ],
        )
    )

    # =========================================================================
    # CATEGORY 2: PARSERS & STATE MACHINES (T06 - T10)
    # =========================================================================
    tasks.append(
        TaskSpec(
            task_id="T06",
            category=BugCategory.PARSERS_STATE_MACHINES,
            title="CSV splitter preserving commas inside quotes",
            specification="Implement `split_csv_row(line: str) -> list[str]` splitting on unquoted commas and stripping outer double quotes.",
            contract_version_initial="v1",
            contract_version_post_compaction="v1",
            target_file="csv_parser.py",
            target_symbol="split_csv_row",
            initial_files={
                "csv_parser.py": "def split_csv_row(line):\n    return line.split(',')\n"
            },
            witness_name="test_quoted_comma_not_split",
            witness_test_code=(
                "from csv_parser import split_csv_row\n"
                "def test_quoted_comma_not_split():\n"
                "    assert split_csv_row('\"Paris, FR\",42,ok') == ['Paris, FR', '42', 'ok']\n"
            ),
            reference_test_code=(
                "from csv_parser import split_csv_row\n"
                "def test_reference_suite():\n"
                "    assert split_csv_row('\"Paris, FR\",42,ok') == ['Paris, FR', '42', 'ok']\n"
                "    assert split_csv_row('a,b,c') == ['a', 'b', 'c']\n"
                "    assert split_csv_row('\"x\",\"y,z\"') == ['x', 'y,z']\n"
            ),
            pre_compaction_failed_patch=CandidatePatch(
                patch_id="T06-pre",
                description="Strips quotes after naive split(',')",
                files={
                    "csv_parser.py": (
                        "def split_csv_row(line):\n"
                        "    return [part.strip('\"') for part in line.split(',')]\n"
                    )
                },
                is_known_regression=True,
                is_valid_solution=False,
                contract_version="v1",
            ),
            verbose_observations=_make_verbose_observations("T06", "csv_parser.py", "split_csv_row"),
            post_compaction_candidates=[
                CandidatePatch(
                    patch_id="T06-c1-reg",
                    description="Alpha-renamed naive split(',')",
                    files={
                        "csv_parser.py": (
                            "def split_csv_row(raw_line):\n"
                            "    return [seg.strip('\"') for seg in raw_line.split(',')]\n"
                        )
                    },
                    is_known_regression=True,
                    is_valid_solution=False,
                    contract_version="v1",
                ),
                CandidatePatch(
                    patch_id="T06-c2-fix",
                    description="Tracks in_quotes state while scanning characters",
                    files={
                        "csv_parser.py": (
                            "def split_csv_row(line):\n"
                            "    fields, buf, in_quotes = [], [], False\n"
                            "    for ch in line:\n"
                            "        if ch == '\"':\n"
                            "            in_quotes = not in_quotes\n"
                            "        elif ch == ',' and not in_quotes:\n"
                            "            fields.append(''.join(buf))\n"
                            "            buf = []\n"
                            "        else:\n"
                            "            buf.append(ch)\n"
                            "    fields.append(''.join(buf))\n"
                            "    return fields\n"
                        )
                    },
                    is_known_regression=False,
                    is_valid_solution=True,
                    contract_version="v1",
                ),
            ],
        )
    )

    tasks.append(
        TaskSpec(
            task_id="T07",
            category=BugCategory.PARSERS_STATE_MACHINES,
            title="Bracket balancer unclosed stack check",
            specification="Implement `is_balanced(expr: str) -> bool` checking balanced (), [], and {} brackets.",
            contract_version_initial="v1",
            contract_version_post_compaction="v1",
            target_file="brackets.py",
            target_symbol="is_balanced",
            initial_files={
                "brackets.py": "def is_balanced(expr):\n    return True\n"
            },
            witness_name="test_unclosed_opening_bracket_returns_false",
            witness_test_code=(
                "from brackets import is_balanced\n"
                "def test_unclosed_opening_bracket_returns_false():\n"
                "    assert is_balanced('([a + b]') is False\n"
            ),
            reference_test_code=(
                "from brackets import is_balanced\n"
                "def test_reference_suite():\n"
                "    assert is_balanced('([a + b]') is False\n"
                "    assert is_balanced('([a + b])') is True\n"
                "    assert is_balanced('((())') is False\n"
                "    assert is_balanced(']') is False\n"
                "    assert is_balanced('{[()]}') is True\n"
            ),
            pre_compaction_failed_patch=CandidatePatch(
                patch_id="T07-pre",
                description="Returns True at end of loop without checking empty stack",
                files={
                    "brackets.py": (
                        "def is_balanced(expr):\n"
                        "    pairs = {')': '(', ']': '[', '}': '{'}\n"
                        "    stack = []\n"
                        "    for ch in expr:\n"
                        "        if ch in '([{':\n"
                        "            stack.append(ch)\n"
                        "        elif ch in pairs:\n"
                        "            if not stack or stack.pop() != pairs[ch]:\n"
                        "                return False\n"
                        "    return True\n"
                    )
                },
                is_known_regression=True,
                is_valid_solution=False,
                contract_version="v1",
            ),
            verbose_observations=_make_verbose_observations("T07", "brackets.py", "is_balanced"),
            post_compaction_candidates=[
                CandidatePatch(
                    patch_id="T07-c1-reg",
                    description="Alpha-renamed repeat missing final stack emptiness check",
                    files={
                        "brackets.py": (
                            "def is_balanced(text):\n"
                            "    mapping = {')': '(', ']': '[', '}': '{'}\n"
                            "    stk = []\n"
                            "    for c in text:\n"
                            "        if c in '([{':\n"
                            "            stk.append(c)\n"
                            "        elif c in mapping:\n"
                            "            if not stk or stk.pop() != mapping[c]:\n"
                            "                return False\n"
                            "    return True\n"
                        )
                    },
                    is_known_regression=True,
                    is_valid_solution=False,
                    contract_version="v1",
                ),
                CandidatePatch(
                    patch_id="T07-c2-fix",
                    description="Checks len(stack) == 0 on completion",
                    files={
                        "brackets.py": (
                            "def is_balanced(expr):\n"
                            "    pairs = {')': '(', ']': '[', '}': '{'}\n"
                            "    stack = []\n"
                            "    for ch in expr:\n"
                            "        if ch in '([{':\n"
                            "            stack.append(ch)\n"
                            "        elif ch in pairs:\n"
                            "            if not stack or stack.pop() != pairs[ch]:\n"
                            "                return False\n"
                            "    return len(stack) == 0\n"
                        )
                    },
                    is_known_regression=False,
                    is_valid_solution=True,
                    contract_version="v1",
                ),
            ],
        )
    )

    tasks.append(
        TaskSpec(
            task_id="T08",
            category=BugCategory.PARSERS_STATE_MACHINES,
            title="Key-value INI parser preserving '=' in values",
            specification="Implement `parse_kv_lines(text: str) -> dict[str, str]` ignoring `#` comments and preserving `=` characters inside values.",
            contract_version_initial="v1",
            contract_version_post_compaction="v1",
            target_file="ini_parser.py",
            target_symbol="parse_kv_lines",
            initial_files={
                "ini_parser.py": "def parse_kv_lines(text):\n    return {}\n"
            },
            witness_name="test_value_containing_equals_preserved",
            witness_test_code=(
                "from ini_parser import parse_kv_lines\n"
                "def test_value_containing_equals_preserved():\n"
                "    raw = 'dsn = postgres://u:p@host/db?sslmode=require&pool=5'\n"
                "    assert parse_kv_lines(raw) == {'dsn': 'postgres://u:p@host/db?sslmode=require&pool=5'}\n"
            ),
            reference_test_code=(
                "from ini_parser import parse_kv_lines\n"
                "def test_reference_suite():\n"
                "    raw = '# comment\\ndsn = postgres://u:p@host/db?sslmode=require&pool=5\\nport = 5432\\n'\n"
                "    assert parse_kv_lines(raw) == {\n"
                "        'dsn': 'postgres://u:p@host/db?sslmode=require&pool=5',\n"
                "        'port': '5432',\n"
                "    }\n"
            ),
            pre_compaction_failed_patch=CandidatePatch(
                patch_id="T08-pre",
                description="Uses split('=') and takes parts[1], truncating at second '='",
                files={
                    "ini_parser.py": (
                        "def parse_kv_lines(text):\n"
                        "    out = {}\n"
                        "    for line in text.splitlines():\n"
                        "        line = line.strip()\n"
                        "        if not line or line.startswith('#'):\n"
                        "            continue\n"
                        "        parts = line.split('=')\n"
                        "        out[parts[0].strip()] = parts[1].strip()\n"
                        "    return out\n"
                    )
                },
                is_known_regression=True,
                is_valid_solution=False,
                contract_version="v1",
            ),
            verbose_observations=_make_verbose_observations("T08", "ini_parser.py", "parse_kv_lines"),
            post_compaction_candidates=[
                CandidatePatch(
                    patch_id="T08-c1-reg",
                    description="Alpha-renamed repeat truncating at second '='",
                    files={
                        "ini_parser.py": (
                            "def parse_kv_lines(content):\n"
                            "    res = {}\n"
                            "    for ln in content.splitlines():\n"
                            "        ln = ln.strip()\n"
                            "        if not ln or ln.startswith('#'):\n"
                            "            continue\n"
                            "        tokens = ln.split('=')\n"
                            "        res[tokens[0].strip()] = tokens[1].strip()\n"
                            "    return res\n"
                        )
                    },
                    is_known_regression=True,
                    is_valid_solution=False,
                    contract_version="v1",
                ),
                CandidatePatch(
                    patch_id="T08-c2-fix",
                    description="Uses partition('=') to preserve '=' in value",
                    files={
                        "ini_parser.py": (
                            "def parse_kv_lines(text):\n"
                            "    out = {}\n"
                            "    for line in text.splitlines():\n"
                            "        line = line.strip()\n"
                            "        if not line or line.startswith('#'):\n"
                            "            continue\n"
                            "        if '=' in line:\n"
                            "            k, _, v = line.partition('=')\n"
                            "            out[k.strip()] = v.strip()\n"
                            "    return out\n"
                        )
                    },
                    is_known_regression=False,
                    is_valid_solution=True,
                    contract_version="v1",
                ),
            ],
        )
    )

    tasks.append(
        TaskSpec(
            task_id="T09",
            category=BugCategory.PARSERS_STATE_MACHINES,
            title="Shell argument lexer with backslash-escaped spaces",
            specification="Implement `tokenize_args(cmd: str) -> list[str]` splitting on unescaped whitespace while respecting `\\` escapes.",
            contract_version_initial="v1",
            contract_version_post_compaction="v1",
            target_file="lexer.py",
            target_symbol="tokenize_args",
            initial_files={
                "lexer.py": "def tokenize_args(cmd):\n    return cmd.split()\n"
            },
            witness_name="test_escaped_space_kept_in_single_token",
            witness_test_code=(
                "from lexer import tokenize_args\n"
                "def test_escaped_space_kept_in_single_token():\n"
                "    assert tokenize_args(r'cp My\\ Documents/file.txt /tmp') == ['cp', 'My Documents/file.txt', '/tmp']\n"
            ),
            reference_test_code=(
                "from lexer import tokenize_args\n"
                "def test_reference_suite():\n"
                "    assert tokenize_args(r'cp My\\ Documents/file.txt /tmp') == ['cp', 'My Documents/file.txt', '/tmp']\n"
                "    assert tokenize_args('echo hello world') == ['echo', 'hello', 'world']\n"
                "    assert tokenize_args('') == []\n"
            ),
            pre_compaction_failed_patch=CandidatePatch(
                patch_id="T09-pre",
                description="Splits on whitespace first and replaces backslash after",
                files={
                    "lexer.py": (
                        "def tokenize_args(cmd):\n"
                        "    return [tok.replace('\\\\', '') for tok in cmd.split()]\n"
                    )
                },
                is_known_regression=True,
                is_valid_solution=False,
                contract_version="v1",
            ),
            verbose_observations=_make_verbose_observations("T09", "lexer.py", "tokenize_args"),
            post_compaction_candidates=[
                CandidatePatch(
                    patch_id="T09-c1-reg",
                    description="Alpha-renamed split before escape processing",
                    files={
                        "lexer.py": (
                            "def tokenize_args(command_str):\n"
                            "    return [part.replace('\\\\', '') for part in command_str.split()]\n"
                        )
                    },
                    is_known_regression=True,
                    is_valid_solution=False,
                    contract_version="v1",
                ),
                CandidatePatch(
                    patch_id="T09-c2-fix",
                    description="State-machine lexer tracking escape flag",
                    files={
                        "lexer.py": (
                            "def tokenize_args(cmd):\n"
                            "    tokens, cur, escaped = [], [], False\n"
                            "    for ch in cmd:\n"
                            "        if escaped:\n"
                            "            cur.append(ch)\n"
                            "            escaped = False\n"
                            "        elif ch == '\\\\':\n"
                            "            escaped = True\n"
                            "        elif ch.isspace():\n"
                            "            if cur:\n"
                            "                tokens.append(''.join(cur))\n"
                            "                cur = []\n"
                            "        else:\n"
                            "            cur.append(ch)\n"
                            "    if cur:\n"
                            "        tokens.append(''.join(cur))\n"
                            "    return tokens\n"
                        )
                    },
                    is_known_regression=False,
                    is_valid_solution=True,
                    contract_version="v1",
                ),
            ],
        )
    )

    tasks.append(
        TaskSpec(
            task_id="T10",
            category=BugCategory.PARSERS_STATE_MACHINES,
            title="Protocol state machine RESET transition from ERROR state",
            specification="Implement `next_state(state: str, event: str) -> str` supporting IDLE->CONNECTING on CONNECT, CONNECTING->CONNECTED on ACK, CONNECTING->ERROR on FAIL, and ANY state -> IDLE on RESET.",
            contract_version_initial="v1",
            contract_version_post_compaction="v1",
            target_file="protocol.py",
            target_symbol="next_state",
            initial_files={
                "protocol.py": "def next_state(state, event):\n    return state\n"
            },
            witness_name="test_reset_from_error_returns_idle",
            witness_test_code=(
                "from protocol import next_state\n"
                "def test_reset_from_error_returns_idle():\n"
                "    assert next_state('ERROR', 'RESET') == 'IDLE'\n"
            ),
            reference_test_code=(
                "from protocol import next_state\n"
                "def test_reference_suite():\n"
                "    assert next_state('IDLE', 'CONNECT') == 'CONNECTING'\n"
                "    assert next_state('CONNECTING', 'ACK') == 'CONNECTED'\n"
                "    assert next_state('CONNECTING', 'FAIL') == 'ERROR'\n"
                "    assert next_state('ERROR', 'RESET') == 'IDLE'\n"
                "    assert next_state('CONNECTED', 'RESET') == 'IDLE'\n"
            ),
            pre_compaction_failed_patch=CandidatePatch(
                patch_id="T10-pre",
                description="Handles RESET only when state == 'CONNECTED'",
                files={
                    "protocol.py": (
                        "def next_state(state, event):\n"
                        "    if state == 'IDLE' and event == 'CONNECT':\n"
                        "        return 'CONNECTING'\n"
                        "    if state == 'CONNECTING' and event == 'ACK':\n"
                        "        return 'CONNECTED'\n"
                        "    if state == 'CONNECTING' and event == 'FAIL':\n"
                        "        return 'ERROR'\n"
                        "    if state == 'CONNECTED' and event == 'RESET':\n"
                        "        return 'IDLE'\n"
                        "    raise ValueError(f'Invalid transition: {state} -> {event}')\n"
                    )
                },
                is_known_regression=True,
                is_valid_solution=False,
                contract_version="v1",
            ),
            verbose_observations=_make_verbose_observations("T10", "protocol.py", "next_state"),
            post_compaction_candidates=[
                CandidatePatch(
                    patch_id="T10-c1-reg",
                    description="Alpha-renamed repeat restricting RESET to CONNECTED",
                    files={
                        "protocol.py": (
                            "def next_state(cur, evt):\n"
                            "    if cur == 'IDLE' and evt == 'CONNECT':\n"
                            "        return 'CONNECTING'\n"
                            "    if cur == 'CONNECTING' and evt == 'ACK':\n"
                            "        return 'CONNECTED'\n"
                            "    if cur == 'CONNECTING' and evt == 'FAIL':\n"
                            "        return 'ERROR'\n"
                            "    if cur == 'CONNECTED' and evt == 'RESET':\n"
                            "        return 'IDLE'\n"
                            "    raise ValueError(f'Invalid transition: {cur} -> {evt}')\n"
                        )
                    },
                    is_known_regression=True,
                    is_valid_solution=False,
                    contract_version="v1",
                ),
                CandidatePatch(
                    patch_id="T10-c2-fix",
                    description="Allows global RESET event from any valid state to IDLE",
                    files={
                        "protocol.py": (
                            "def next_state(state, event):\n"
                            "    if event == 'RESET':\n"
                            "        return 'IDLE'\n"
                            "    if state == 'IDLE' and event == 'CONNECT':\n"
                            "        return 'CONNECTING'\n"
                            "    if state == 'CONNECTING' and event == 'ACK':\n"
                            "        return 'CONNECTED'\n"
                            "    if state == 'CONNECTING' and event == 'FAIL':\n"
                            "        return 'ERROR'\n"
                            "    raise ValueError(f'Invalid transition: {state} -> {event}')\n"
                        )
                    },
                    is_known_regression=False,
                    is_valid_solution=True,
                    contract_version="v1",
                ),
            ],
        )
    )

    # =========================================================================
    # CATEGORY 3: EXCEPTION HANDLING (T11 - T15)
    # =========================================================================
    tasks.append(
        TaskSpec(
            task_id="T11",
            category=BugCategory.EXCEPTION_HANDLING,
            title="Safe integer conversion when input is None",
            specification="Implement `safe_int(val, default: int = 0) -> int` returning `default` on both unparseable strings and `None` / non-convertible types.",
            contract_version_initial="v1",
            contract_version_post_compaction="v1",
            target_file="converters.py",
            target_symbol="safe_int",
            initial_files={
                "converters.py": "def safe_int(val, default=0):\n    return int(val)\n"
            },
            witness_name="test_none_input_returns_default_without_type_error",
            witness_test_code=(
                "from converters import safe_int\n"
                "def test_none_input_returns_default_without_type_error():\n"
                "    assert safe_int(None, default=-1) == -1\n"
            ),
            reference_test_code=(
                "from converters import safe_int\n"
                "def test_reference_suite():\n"
                "    assert safe_int(None, default=-1) == -1\n"
                "    assert safe_int('not_a_num', default=0) == 0\n"
                "    assert safe_int('42', default=0) == 42\n"
                "    assert safe_int(17, default=0) == 17\n"
            ),
            pre_compaction_failed_patch=CandidatePatch(
                patch_id="T11-pre",
                description="Catches ValueError only, raising TypeError on None",
                files={
                    "converters.py": (
                        "def safe_int(val, default=0):\n"
                        "    try:\n"
                        "        return int(val)\n"
                        "    except ValueError:\n"
                        "        return default\n"
                    )
                },
                is_known_regression=True,
                is_valid_solution=False,
                contract_version="v1",
            ),
            verbose_observations=_make_verbose_observations("T11", "converters.py", "safe_int"),
            post_compaction_candidates=[
                CandidatePatch(
                    patch_id="T11-c1-reg",
                    description="Alpha-renamed catch of ValueError only",
                    files={
                        "converters.py": (
                            "def safe_int(raw, fallback=0):\n"
                            "    try:\n"
                            "        return int(raw)\n"
                            "    except ValueError:\n"
                            "        return fallback\n"
                        )
                    },
                    is_known_regression=True,
                    is_valid_solution=False,
                    contract_version="v1",
                ),
                CandidatePatch(
                    patch_id="T11-c2-fix",
                    description="Catches both ValueError and TypeError",
                    files={
                        "converters.py": (
                            "def safe_int(val, default=0):\n"
                            "    try:\n"
                            "        return int(val)\n"
                            "    except (ValueError, TypeError):\n"
                            "        return default\n"
                        )
                    },
                    is_known_regression=False,
                    is_valid_solution=True,
                    contract_version="v1",
                ),
            ],
        )
    )

    tasks.append(
        TaskSpec(
            task_id="T12",
            category=BugCategory.EXCEPTION_HANDLING,
            title="Percentage parser rejecting >100% or <0% with ValueError",
            specification="Implement `parse_pct(text: str) -> float` converting '0%'..'100%' to 0.0..1.0 and raising ValueError outside [0, 100].",
            contract_version_initial="v1",
            contract_version_post_compaction="v1",
            target_file="validators.py",
            target_symbol="parse_pct",
            initial_files={
                "validators.py": "def parse_pct(text):\n    return 0.0\n"
            },
            witness_name="test_over_100_percent_raises_value_error",
            witness_test_code=(
                "from validators import parse_pct\n"
                "def test_over_100_percent_raises_value_error():\n"
                "    try:\n"
                "        parse_pct('125%')\n"
                "    except ValueError:\n"
                "        return\n"
                "    assert False, 'Expected ValueError for 125%'\n"
            ),
            reference_test_code=(
                "from validators import parse_pct\n"
                "def test_reference_suite():\n"
                "    assert parse_pct('50%') == 0.5\n"
                "    assert parse_pct('0%') == 0.0\n"
                "    assert parse_pct('100%') == 1.0\n"
                "    for bad in ('125%', '-5%', 'abc%'):\n"
                "        raised = False\n"
                "        try:\n"
                "            parse_pct(bad)\n"
                "        except ValueError:\n"
                "            raised = True\n"
                "        assert raised, f'Failed to raise ValueError on {bad}'\n"
            ),
            pre_compaction_failed_patch=CandidatePatch(
                patch_id="T12-pre",
                description="Parses float without checking [0, 100] bounds",
                files={
                    "validators.py": (
                        "def parse_pct(text):\n"
                        "    cleaned = text.strip().rstrip('%')\n"
                        "    val = float(cleaned)\n"
                        "    return val / 100.0\n"
                    )
                },
                is_known_regression=True,
                is_valid_solution=False,
                contract_version="v1",
            ),
            verbose_observations=_make_verbose_observations("T12", "validators.py", "parse_pct"),
            post_compaction_candidates=[
                CandidatePatch(
                    patch_id="T12-c1-reg",
                    description="Alpha-renamed repeat missing [0, 100] range validation",
                    files={
                        "validators.py": (
                            "def parse_pct(raw_str):\n"
                            "    stripped = raw_str.strip().rstrip('%')\n"
                            "    num = float(stripped)\n"
                            "    return num / 100.0\n"
                        )
                    },
                    is_known_regression=True,
                    is_valid_solution=False,
                    contract_version="v1",
                ),
                CandidatePatch(
                    patch_id="T12-c2-fix",
                    description="Raises ValueError when parsed value is outside [0, 100]",
                    files={
                        "validators.py": (
                            "def parse_pct(text):\n"
                            "    if not isinstance(text, str) or not text.strip().endswith('%'):\n"
                            "        raise ValueError('Percentage must end with %')\n"
                            "    val = float(text.strip()[:-1])\n"
                            "    if not (0.0 <= val <= 100.0):\n"
                            "        raise ValueError('Percentage out of bounds [0, 100]')\n"
                            "    return val / 100.0\n"
                        )
                    },
                    is_known_regression=False,
                    is_valid_solution=True,
                    contract_version="v1",
                ),
            ],
        )
    )

    tasks.append(
        TaskSpec(
            task_id="T13",
            category=BugCategory.EXCEPTION_HANDLING,
            title="Nested dictionary lookup raising KeyError when intermediate value is None",
            specification="Implement `deep_get(data: dict, dotted_path: str)` returning the nested value or raising `KeyError(dotted_path)` if any segment is missing or non-dict.",
            contract_version_initial="v1",
            contract_version_post_compaction="v1",
            target_file="lookup.py",
            target_symbol="deep_get",
            initial_files={
                "lookup.py": "def deep_get(data, dotted_path):\n    return data[dotted_path]\n"
            },
            witness_name="test_none_intermediate_raises_key_error_not_type_error",
            witness_test_code=(
                "from lookup import deep_get\n"
                "def test_none_intermediate_raises_key_error_not_type_error():\n"
                "    try:\n"
                "        deep_get({'user': None}, 'user.email')\n"
                "    except KeyError:\n"
                "        return\n"
                "    assert False, 'Expected KeyError when intermediate key is None'\n"
            ),
            reference_test_code=(
                "from lookup import deep_get\n"
                "def test_reference_suite():\n"
                "    assert deep_get({'user': {'email': 'a@b.c'}}, 'user.email') == 'a@b.c'\n"
                "    for payload in ({'user': None}, {'user': {}}, {}):\n"
                "        ok = False\n"
                "        try:\n"
                "            deep_get(payload, 'user.email')\n"
                "        except KeyError:\n"
                "            ok = True\n"
                "        assert ok\n"
            ),
            pre_compaction_failed_patch=CandidatePatch(
                patch_id="T13-pre",
                description="Subscripts curr[part] directly without checking isinstance(curr, dict), raising TypeError on None",
                files={
                    "lookup.py": (
                        "def deep_get(data, dotted_path):\n"
                        "    curr = data\n"
                        "    for part in dotted_path.split('.'):\n"
                        "        curr = curr[part]\n"
                        "    return curr\n"
                    )
                },
                is_known_regression=True,
                is_valid_solution=False,
                contract_version="v1",
            ),
            verbose_observations=_make_verbose_observations("T13", "lookup.py", "deep_get"),
            post_compaction_candidates=[
                CandidatePatch(
                    patch_id="T13-c1-reg",
                    description="Alpha-renamed direct subscripting raising TypeError on None",
                    files={
                        "lookup.py": (
                            "def deep_get(mapping, path_str):\n"
                            "    node = mapping\n"
                            "    for seg in path_str.split('.'):\n"
                            "        node = node[seg]\n"
                            "    return node\n"
                        )
                    },
                    is_known_regression=True,
                    is_valid_solution=False,
                    contract_version="v1",
                ),
                CandidatePatch(
                    patch_id="T13-c2-fix",
                    description="Verifies isinstance(curr, dict) and membership at each step",
                    files={
                        "lookup.py": (
                            "def deep_get(data, dotted_path):\n"
                            "    curr = data\n"
                            "    for part in dotted_path.split('.'):\n"
                            "        if not isinstance(curr, dict) or part not in curr:\n"
                            "            raise KeyError(dotted_path)\n"
                            "        curr = curr[part]\n"
                            "    return curr\n"
                        )
                    },
                    is_known_regression=False,
                    is_valid_solution=True,
                    contract_version="v1",
                ),
            ],
        )
    )

    tasks.append(
        TaskSpec(
            task_id="T14",
            category=BugCategory.EXCEPTION_HANDLING,
            title="Guaranteed cleanup callback execution via try/finally",
            specification="Implement `run_with_cleanup(work_fn, cleanup_fn)` so `cleanup_fn()` always executes even when `work_fn()` raises an exception.",
            contract_version_initial="v1",
            contract_version_post_compaction="v1",
            target_file="runner_utils.py",
            target_symbol="run_with_cleanup",
            initial_files={
                "runner_utils.py": "def run_with_cleanup(work_fn, cleanup_fn):\n    return work_fn()\n"
            },
            witness_name="test_cleanup_invoked_on_exception",
            witness_test_code=(
                "from runner_utils import run_with_cleanup\n"
                "def test_cleanup_invoked_on_exception():\n"
                "    state = {'cleaned': False}\n"
                "    def bad_work():\n"
                "        raise RuntimeError('boom')\n"
                "    def cleanup():\n"
                "        state['cleaned'] = True\n"
                "    try:\n"
                "        run_with_cleanup(bad_work, cleanup)\n"
                "    except RuntimeError:\n"
                "        pass\n"
                "    assert state['cleaned'] is True\n"
            ),
            reference_test_code=(
                "from runner_utils import run_with_cleanup\n"
                "def test_reference_suite():\n"
                "    log = []\n"
                "    assert run_with_cleanup(lambda: 99, lambda: log.append('done')) == 99\n"
                "    assert log == ['done']\n"
                "    try:\n"
                "        run_with_cleanup(lambda: (_ for _ in ()).throw(ValueError('x')), lambda: log.append('err_clean'))\n"
                "    except ValueError:\n"
                "        pass\n"
                "    assert log == ['done', 'err_clean']\n"
            ),
            pre_compaction_failed_patch=CandidatePatch(
                patch_id="T14-pre",
                description="Calls cleanup_fn() after work_fn() without finally block",
                files={
                    "runner_utils.py": (
                        "def run_with_cleanup(work_fn, cleanup_fn):\n"
                        "    res = work_fn()\n"
                        "    cleanup_fn()\n"
                        "    return res\n"
                    )
                },
                is_known_regression=True,
                is_valid_solution=False,
                contract_version="v1",
            ),
            verbose_observations=_make_verbose_observations("T14", "runner_utils.py", "run_with_cleanup"),
            post_compaction_candidates=[
                CandidatePatch(
                    patch_id="T14-c1-reg",
                    description="Alpha-renamed sequential call without finally",
                    files={
                        "runner_utils.py": (
                            "def run_with_cleanup(action, teardown):\n"
                            "    out = action()\n"
                            "    teardown()\n"
                            "    return out\n"
                        )
                    },
                    is_known_regression=True,
                    is_valid_solution=False,
                    contract_version="v1",
                ),
                CandidatePatch(
                    patch_id="T14-c2-fix",
                    description="Wraps execution in try/finally",
                    files={
                        "runner_utils.py": (
                            "def run_with_cleanup(work_fn, cleanup_fn):\n"
                            "    try:\n"
                            "        return work_fn()\n"
                            "    finally:\n"
                            "        cleanup_fn()\n"
                        )
                    },
                    is_known_regression=False,
                    is_valid_solution=True,
                    contract_version="v1",
                ),
            ],
        )
    )

    tasks.append(
        TaskSpec(
            task_id="T15",
            category=BugCategory.EXCEPTION_HANDLING,
            title="NaN and Inf rejection in positive weight normalization",
            specification="Implement `normalize_weights(weights: list[float]) -> list[float]` raising ValueError if empty or any weight is <= 0, NaN, or infinite.",
            contract_version_initial="v1",
            contract_version_post_compaction="v1",
            target_file="weights.py",
            target_symbol="normalize_weights",
            initial_files={
                "weights.py": "def normalize_weights(weights):\n    s = sum(weights)\n    return [w / s for w in weights]\n"
            },
            witness_name="test_nan_weight_raises_value_error",
            witness_test_code=(
                "from weights import normalize_weights\n"
                "def test_nan_weight_raises_value_error():\n"
                "    try:\n"
                "        normalize_weights([1.0, float('nan'), 2.0])\n"
                "    except ValueError:\n"
                "        return\n"
                "    assert False, 'Expected ValueError on NaN weight'\n"
            ),
            reference_test_code=(
                "from weights import normalize_weights\n"
                "def test_reference_suite():\n"
                "    assert normalize_weights([1.0, 3.0]) == [0.25, 0.75]\n"
                "    for bad in ([], [1.0, 0.0], [1.0, -2.0], [float('nan')], [float('inf')]):\n"
                "        ok = False\n"
                "        try:\n"
                "            normalize_weights(bad)\n"
                "        except ValueError:\n"
                "            ok = True\n"
                "        assert ok, f'Did not raise on {bad}'\n"
            ),
            pre_compaction_failed_patch=CandidatePatch(
                patch_id="T15-pre",
                description="Checks w <= 0 which evaluates to False for IEEE-754 NaN",
                files={
                    "weights.py": (
                        "def normalize_weights(weights):\n"
                        "    if not weights:\n"
                        "        raise ValueError('Empty weights')\n"
                        "    for w in weights:\n"
                        "        if w <= 0:\n"
                        "            raise ValueError('Non-positive weight')\n"
                        "    total = sum(weights)\n"
                        "    return [w / total for w in weights]\n"
                    )
                },
                is_known_regression=True,
                is_valid_solution=False,
                contract_version="v1",
            ),
            verbose_observations=_make_verbose_observations("T15", "weights.py", "normalize_weights"),
            post_compaction_candidates=[
                CandidatePatch(
                    patch_id="T15-c1-reg",
                    description="Alpha-renamed w <= 0 check missing math.isfinite",
                    files={
                        "weights.py": (
                            "def normalize_weights(items):\n"
                            "    if not items:\n"
                            "        raise ValueError('Empty weights')\n"
                            "    for val in items:\n"
                            "        if val <= 0:\n"
                            "            raise ValueError('Non-positive weight')\n"
                            "    acc = sum(items)\n"
                            "    return [val / acc for val in items]\n"
                        )
                    },
                    is_known_regression=True,
                    is_valid_solution=False,
                    contract_version="v1",
                ),
                CandidatePatch(
                    patch_id="T15-c2-fix",
                    description="Uses math.isfinite(w) and w > 0",
                    files={
                        "weights.py": (
                            "import math\n\n"
                            "def normalize_weights(weights):\n"
                            "    if not weights:\n"
                            "        raise ValueError('Empty weights')\n"
                            "    for w in weights:\n"
                            "        if not math.isfinite(w) or w <= 0:\n"
                            "            raise ValueError('Invalid weight')\n"
                            "    total = sum(weights)\n"
                            "    return [w / total for w in weights]\n"
                        )
                    },
                    is_known_regression=False,
                    is_valid_solution=True,
                    contract_version="v1",
                ),
            ],
        )
    )

    # =========================================================================
    # CATEGORY 4: MULTI-FILE CHANGES (T16 - T20)
    # =========================================================================
    tasks.append(
        TaskSpec(
            task_id="T16",
            category=BugCategory.MULTI_FILE_CHANGES,
            title="Cross-module token expiry unit alignment (ms vs seconds)",
            specification="Align `auth_tokens.py::issue_token` and `session_guard.py::is_token_valid` so `ttl_seconds` is compared in seconds against `now_ts`.",
            contract_version_initial="v1",
            contract_version_post_compaction="v1",
            target_file="session_guard.py",
            target_symbol="is_token_valid",
            initial_files={
                "auth_tokens.py": (
                    "def issue_token(user_id, issued_at_s, ttl_s):\n"
                    "    return {'uid': user_id, 'exp': issued_at_s + ttl_s * 1000}\n"
                ),
                "session_guard.py": (
                    "def is_token_valid(token, now_s):\n"
                    "    return now_s < token['exp']\n"
                ),
            },
            witness_name="test_expired_token_rejected_at_exact_ttl",
            witness_test_code=(
                "from auth_tokens import issue_token\n"
                "from session_guard import is_token_valid\n"
                "def test_expired_token_rejected_at_exact_ttl():\n"
                "    tok = issue_token('u1', issued_at_s=1000, ttl_s=60)\n"
                "    assert is_token_valid(tok, now_s=1061) is False\n"
            ),
            reference_test_code=(
                "from auth_tokens import issue_token\n"
                "from session_guard import is_token_valid\n"
                "def test_reference_suite():\n"
                "    tok = issue_token('u1', issued_at_s=1000, ttl_s=60)\n"
                "    assert is_token_valid(tok, now_s=1059) is True\n"
                "    assert is_token_valid(tok, now_s=1060) is False\n"
                "    assert is_token_valid(tok, now_s=1061) is False\n"
            ),
            pre_compaction_failed_patch=CandidatePatch(
                patch_id="T16-pre",
                description="Leaves * 1000 multiplier in auth_tokens.py while comparing seconds in session_guard.py",
                files={
                    "auth_tokens.py": (
                        "def issue_token(user_id, issued_at_s, ttl_s):\n"
                        "    return {'uid': user_id, 'exp': issued_at_s + ttl_s * 1000}\n"
                    ),
                    "session_guard.py": (
                        "def is_token_valid(token, now_s):\n"
                        "    return bool(token.get('uid')) and now_s < token['exp']\n"
                    ),
                },
                is_known_regression=True,
                is_valid_solution=False,
                contract_version="v1",
            ),
            verbose_observations=_make_verbose_observations("T16", "session_guard.py", "is_token_valid"),
            post_compaction_candidates=[
                CandidatePatch(
                    patch_id="T16-c1-reg",
                    description="Alpha-renamed repeat leaving * 1000 unit mismatch",
                    files={
                        "auth_tokens.py": (
                            "def issue_token(uid, start_s, duration_s):\n"
                            "    return {'uid': uid, 'exp': start_s + duration_s * 1000}\n"
                        ),
                        "session_guard.py": (
                            "def is_token_valid(tok, current_s):\n"
                            "    return bool(tok.get('uid')) and current_s < tok['exp']\n"
                        ),
                    },
                    is_known_regression=True,
                    is_valid_solution=False,
                    contract_version="v1",
                ),
                CandidatePatch(
                    patch_id="T16-c2-fix",
                    description="Uses consistent seconds in both auth_tokens.py and session_guard.py",
                    files={
                        "auth_tokens.py": (
                            "def issue_token(user_id, issued_at_s, ttl_s):\n"
                            "    return {'uid': user_id, 'exp': issued_at_s + ttl_s}\n"
                        ),
                        "session_guard.py": (
                            "def is_token_valid(token, now_s):\n"
                            "    return bool(token.get('uid')) and now_s < token['exp']\n"
                        ),
                    },
                    is_known_regression=False,
                    is_valid_solution=True,
                    contract_version="v1",
                ),
            ],
        )
    )

    tasks.append(
        TaskSpec(
            task_id="T17",
            category=BugCategory.MULTI_FILE_CHANGES,
            title="Cross-module email normalization in schema and serializer",
            specification="Ensure `schema.py::normalize_user` and `serializer.py::serialize_user` strip and lowercase emails before deduplication.",
            contract_version_initial="v1",
            contract_version_post_compaction="v1",
            target_file="serializer.py",
            target_symbol="serialize_user",
            initial_files={
                "schema.py": "def normalize_user(name, email):\n    return {'name': name.strip(), 'email': email}\n",
                "serializer.py": (
                    "from schema import normalize_user\n"
                    "def serialize_user(name, email):\n"
                    "    rec = normalize_user(name, email)\n"
                    "    return f\"{rec['name']}<{rec['email']}>\"\n"
                ),
            },
            witness_name="test_uppercase_padded_email_normalized",
            witness_test_code=(
                "from serializer import serialize_user\n"
                "def test_uppercase_padded_email_normalized():\n"
                "    assert serialize_user('Alice', '  ALICE@Example.COM ') == 'Alice<alice@example.com>'\n"
            ),
            reference_test_code=(
                "from serializer import serialize_user\n"
                "def test_reference_suite():\n"
                "    assert serialize_user('Alice', '  ALICE@Example.COM ') == 'Alice<alice@example.com>'\n"
                "    assert serialize_user(' Bob ', 'bob@test.org') == 'Bob<bob@test.org>'\n"
            ),
            pre_compaction_failed_patch=CandidatePatch(
                patch_id="T17-pre",
                description="Strips whitespace in schema.py but omits .lower()",
                files={
                    "schema.py": "def normalize_user(name, email):\n    return {'name': name.strip(), 'email': email.strip()}\n",
                    "serializer.py": (
                        "from schema import normalize_user\n"
                        "def serialize_user(name, email):\n"
                        "    rec = normalize_user(name, email)\n"
                        "    return f\"{rec['name']}<{rec['email']}>\"\n"
                    ),
                },
                is_known_regression=True,
                is_valid_solution=False,
                contract_version="v1",
            ),
            verbose_observations=_make_verbose_observations("T17", "serializer.py", "serialize_user"),
            post_compaction_candidates=[
                CandidatePatch(
                    patch_id="T17-c1-reg",
                    description="Alpha-renamed strip without .lower()",
                    files={
                        "schema.py": "def normalize_user(full_name, mail):\n    return {'name': full_name.strip(), 'email': mail.strip()}\n",
                        "serializer.py": (
                            "from schema import normalize_user\n"
                            "def serialize_user(full_name, mail):\n"
                            "    obj = normalize_user(full_name, mail)\n"
                            "    return f\"{obj['name']}<{obj['email']}>\"\n"
                        ),
                    },
                    is_known_regression=True,
                    is_valid_solution=False,
                    contract_version="v1",
                ),
                CandidatePatch(
                    patch_id="T17-c2-fix",
                    description="Strips and lowercases email in schema.py",
                    files={
                        "schema.py": "def normalize_user(name, email):\n    return {'name': name.strip(), 'email': email.strip().lower()}\n",
                        "serializer.py": (
                            "from schema import normalize_user\n"
                            "def serialize_user(name, email):\n"
                            "    rec = normalize_user(name, email)\n"
                            "    return f\"{rec['name']}<{rec['email']}>\"\n"
                        ),
                    },
                    is_known_regression=False,
                    is_valid_solution=True,
                    contract_version="v1",
                ),
            ],
        )
    )

    tasks.append(
        TaskSpec(
            task_id="T18",
            category=BugCategory.MULTI_FILE_CHANGES,
            title="Rate limiter tuple return unpacking in API gateway",
            specification="`rate_limiter.py::consume` returns `(allowed: bool, remaining: int)`; `api_gateway.py::handle_request` must check `allowed` rather than truthiness of the tuple.",
            contract_version_initial="v1",
            contract_version_post_compaction="v1",
            target_file="api_gateway.py",
            target_symbol="handle_request",
            initial_files={
                "rate_limiter.py": (
                    "def consume(quota, cost):\n"
                    "    if cost <= quota:\n"
                    "        return (True, quota - cost)\n"
                    "    return (False, quota)\n"
                ),
                "api_gateway.py": (
                    "from rate_limiter import consume\n"
                    "def handle_request(quota, cost):\n"
                    "    if consume(quota, cost):\n"
                    "        return 200\n"
                    "    return 429\n"
                ),
            },
            witness_name="test_exhausted_quota_returns_429",
            witness_test_code=(
                "from api_gateway import handle_request\n"
                "def test_exhausted_quota_returns_429():\n"
                "    assert handle_request(quota=2, cost=5) == 429\n"
            ),
            reference_test_code=(
                "from api_gateway import handle_request\n"
                "def test_reference_suite():\n"
                "    assert handle_request(quota=2, cost=5) == 429\n"
                "    assert handle_request(quota=5, cost=5) == 200\n"
                "    assert handle_request(quota=10, cost=3) == 200\n"
            ),
            pre_compaction_failed_patch=CandidatePatch(
                patch_id="T18-pre",
                description="Stores tuple in `res` and checks `if res:`, which is always truthy",
                files={
                    "rate_limiter.py": (
                        "def consume(quota, cost):\n"
                        "    if cost <= quota:\n"
                        "        return (True, quota - cost)\n"
                        "    return (False, quota)\n"
                    ),
                    "api_gateway.py": (
                        "from rate_limiter import consume\n"
                        "def handle_request(quota, cost):\n"
                        "    res = consume(quota, cost)\n"
                        "    if res:\n"
                        "        return 200\n"
                        "    return 429\n"
                    ),
                },
                is_known_regression=True,
                is_valid_solution=False,
                contract_version="v1",
            ),
            verbose_observations=_make_verbose_observations("T18", "api_gateway.py", "handle_request"),
            post_compaction_candidates=[
                CandidatePatch(
                    patch_id="T18-c1-reg",
                    description="Alpha-renamed truthiness check on non-empty tuple",
                    files={
                        "rate_limiter.py": (
                            "def consume(avail, weight):\n"
                            "    if weight <= avail:\n"
                            "        return (True, avail - weight)\n"
                            "    return (False, avail)\n"
                        ),
                        "api_gateway.py": (
                            "from rate_limiter import consume\n"
                            "def handle_request(avail, weight):\n"
                            "    outcome = consume(avail, weight)\n"
                            "    if outcome:\n"
                            "        return 200\n"
                            "    return 429\n"
                        ),
                    },
                    is_known_regression=True,
                    is_valid_solution=False,
                    contract_version="v1",
                ),
                CandidatePatch(
                    patch_id="T18-c2-fix",
                    description="Unpacks `allowed, _` from `consume(quota, cost)`",
                    files={
                        "rate_limiter.py": (
                            "def consume(quota, cost):\n"
                            "    if cost <= quota:\n"
                            "        return (True, quota - cost)\n"
                            "    return (False, quota)\n"
                        ),
                        "api_gateway.py": (
                            "from rate_limiter import consume\n"
                            "def handle_request(quota, cost):\n"
                            "    allowed, _ = consume(quota, cost)\n"
                            "    if allowed:\n"
                            "        return 200\n"
                            "    return 429\n"
                        ),
                    },
                    is_known_regression=False,
                    is_valid_solution=True,
                    contract_version="v1",
                ),
            ],
        )
    )

    tasks.append(
        TaskSpec(
            task_id="T19",
            category=BugCategory.MULTI_FILE_CHANGES,
            title="Tax-exempt line items exclusion across invoice and tax_rules",
            specification="`invoice.py::compute_invoice_total` must exclude items with `exempt=True` when calling `tax_rules.py::compute_tax`.",
            contract_version_initial="v1",
            contract_version_post_compaction="v1",
            target_file="invoice.py",
            target_symbol="compute_invoice_total",
            initial_files={
                "tax_rules.py": "def compute_tax(taxable_cents, rate=0.20):\n    return int(round(taxable_cents * rate))\n",
                "invoice.py": (
                    "from tax_rules import compute_tax\n"
                    "def compute_invoice_total(items, rate=0.20):\n"
                    "    subtotal = sum(i['price_cents'] for i in items)\n"
                    "    return subtotal + compute_tax(subtotal, rate)\n"
                ),
            },
            witness_name="test_exempt_item_not_taxed",
            witness_test_code=(
                "from invoice import compute_invoice_total\n"
                "def test_exempt_item_not_taxed():\n"
                "    items = [\n"
                "        {'price_cents': 1000, 'exempt': False},\n"
                "        {'price_cents': 500, 'exempt': True},\n"
                "    ]\n"
                "    assert compute_invoice_total(items, rate=0.20) == 1700\n"
            ),
            reference_test_code=(
                "from invoice import compute_invoice_total\n"
                "def test_reference_suite():\n"
                "    items = [\n"
                "        {'price_cents': 1000, 'exempt': False},\n"
                "        {'price_cents': 500, 'exempt': True},\n"
                "    ]\n"
                "    assert compute_invoice_total(items, rate=0.20) == 1700\n"
                "    assert compute_invoice_total([{'price_cents': 500, 'exempt': True}], rate=0.20) == 500\n"
            ),
            pre_compaction_failed_patch=CandidatePatch(
                patch_id="T19-pre",
                description="Taxes full subtotal including exempt items",
                files={
                    "tax_rules.py": "def compute_tax(taxable_cents, rate=0.20):\n    return int(round(taxable_cents * rate))\n",
                    "invoice.py": (
                        "from tax_rules import compute_tax\n"
                        "def compute_invoice_total(items, rate=0.20):\n"
                        "    subtotal = sum(item['price_cents'] for item in items)\n"
                        "    tax = compute_tax(subtotal, rate)\n"
                        "    return subtotal + tax\n"
                    ),
                },
                is_known_regression=True,
                is_valid_solution=False,
                contract_version="v1",
            ),
            verbose_observations=_make_verbose_observations("T19", "invoice.py", "compute_invoice_total"),
            post_compaction_candidates=[
                CandidatePatch(
                    patch_id="T19-c1-reg",
                    description="Alpha-renamed repeat taxing full subtotal",
                    files={
                        "tax_rules.py": "def compute_tax(amount_cents, tax_rate=0.20):\n    return int(round(amount_cents * tax_rate))\n",
                        "invoice.py": (
                            "from tax_rules import compute_tax\n"
                            "def compute_invoice_total(rows, tax_rate=0.20):\n"
                            "    net = sum(r['price_cents'] for r in rows)\n"
                            "    vat = compute_tax(net, tax_rate)\n"
                            "    return net + vat\n"
                        ),
                    },
                    is_known_regression=True,
                    is_valid_solution=False,
                    contract_version="v1",
                ),
                CandidatePatch(
                    patch_id="T19-c2-fix",
                    description="Computes tax only on non-exempt items",
                    files={
                        "tax_rules.py": "def compute_tax(taxable_cents, rate=0.20):\n    return int(round(taxable_cents * rate))\n",
                        "invoice.py": (
                            "from tax_rules import compute_tax\n"
                            "def compute_invoice_total(items, rate=0.20):\n"
                            "    subtotal = sum(i['price_cents'] for i in items)\n"
                            "    taxable = sum(i['price_cents'] for i in items if not i.get('exempt', False))\n"
                            "    return subtotal + compute_tax(taxable, rate)\n"
                        ),
                    },
                    is_known_regression=False,
                    is_valid_solution=True,
                    contract_version="v1",
                ),
            ],
        )
    )

    tasks.append(
        TaskSpec(
            task_id="T20",
            category=BugCategory.MULTI_FILE_CHANGES,
            title="Cycle-safe BFS shortest path across graph_store and path_finder",
            specification="`path_finder.py::shortest_hop_count(adj, src, dst)` must terminate and return -1 when `dst` is unreachable in a cyclic graph.",
            contract_version_initial="v1",
            contract_version_post_compaction="v1",
            target_file="path_finder.py",
            target_symbol="shortest_hop_count",
            initial_files={
                "graph_store.py": (
                    "def neighbors(adj, node):\n"
                    "    return list(adj.get(node, []))\n"
                ),
                "path_finder.py": (
                    "from graph_store import neighbors\n"
                    "def shortest_hop_count(adj, src, dst):\n"
                    "    return -1\n"
                ),
            },
            witness_name="test_unreachable_in_cycle_returns_minus_one",
            witness_test_code=(
                "from path_finder import shortest_hop_count\n"
                "def test_unreachable_in_cycle_returns_minus_one():\n"
                "    adj = {'A': ['B'], 'B': ['A']}\n"
                "    assert shortest_hop_count(adj, 'A', 'Z') == -1\n"
            ),
            reference_test_code=(
                "from path_finder import shortest_hop_count\n"
                "def test_reference_suite():\n"
                "    adj = {'A': ['B', 'C'], 'B': ['A', 'D'], 'C': ['D'], 'D': []}\n"
                "    assert shortest_hop_count(adj, 'A', 'D') == 2\n"
                "    assert shortest_hop_count(adj, 'A', 'A') == 0\n"
                "    assert shortest_hop_count(adj, 'A', 'Z') == -1\n"
            ),
            pre_compaction_failed_patch=CandidatePatch(
                patch_id="T20-pre",
                description="Bounded loop without visited set, returning wrong hop count or failing on cycles",
                files={
                    "graph_store.py": (
                        "def neighbors(adj, node):\n"
                        "    return list(adj.get(node, []))\n"
                    ),
                    "path_finder.py": (
                        "from graph_store import neighbors\n"
                        "def shortest_hop_count(adj, src, dst):\n"
                        "    if src == dst:\n"
                        "        return 0\n"
                        "    queue = [(src, 0)]\n"
                        "    steps = 0\n"
                        "    while queue and steps < 10:\n"
                        "        node, dist = queue.pop(0)\n"
                        "        steps += 1\n"
                        "        for nxt in neighbors(adj, node):\n"
                        "            if nxt == dst:\n"
                        "                return dist + 1\n"
                        "            queue.append((nxt, dist + 1))\n"
                        "    return 999\n"
                    ),
                },
                is_known_regression=True,
                is_valid_solution=False,
                contract_version="v1",
            ),
            verbose_observations=_make_verbose_observations("T20", "path_finder.py", "shortest_hop_count"),
            post_compaction_candidates=[
                CandidatePatch(
                    patch_id="T20-c1-reg",
                    description="Alpha-renamed repeat returning 999 without visited set",
                    files={
                        "graph_store.py": (
                            "def neighbors(graph, vertex):\n"
                            "    return list(graph.get(vertex, []))\n"
                        ),
                        "path_finder.py": (
                            "from graph_store import neighbors\n"
                            "def shortest_hop_count(graph, start, goal):\n"
                            "    if start == goal:\n"
                            "        return 0\n"
                            "    q = [(start, 0)]\n"
                            "    iters = 0\n"
                            "    while q and iters < 10:\n"
                            "        cur, d = q.pop(0)\n"
                            "        iters += 1\n"
                            "        for nb in neighbors(graph, cur):\n"
                            "            if nb == goal:\n"
                            "                return d + 1\n"
                            "            q.append((nb, d + 1))\n"
                            "    return 999\n"
                        ),
                    },
                    is_known_regression=True,
                    is_valid_solution=False,
                    contract_version="v1",
                ),
                CandidatePatch(
                    patch_id="T20-c2-fix",
                    description="Tracks visited set in BFS and returns -1 when unreachable",
                    files={
                        "graph_store.py": (
                            "def neighbors(adj, node):\n"
                            "    return list(adj.get(node, []))\n"
                        ),
                        "path_finder.py": (
                            "from collections import deque\n"
                            "from graph_store import neighbors\n\n"
                            "def shortest_hop_count(adj, src, dst):\n"
                            "    if src == dst:\n"
                            "        return 0\n"
                            "    visited = {src}\n"
                            "    queue = deque([(src, 0)])\n"
                            "    while queue:\n"
                            "        node, dist = queue.popleft()\n"
                            "        for nxt in neighbors(adj, node):\n"
                            "            if nxt == dst:\n"
                            "                return dist + 1\n"
                            "            if nxt not in visited:\n"
                            "                visited.add(nxt)\n"
                            "                queue.append((nxt, dist + 1))\n"
                            "    return -1\n"
                        ),
                    },
                    is_known_regression=False,
                    is_valid_solution=True,
                    contract_version="v1",
                ),
            ],
        )
    )

    # =========================================================================
    # CATEGORY 5: FEATURE REGRESSIONS & CONTRACT EVOLUTION (T21 - T25)
    # Contract evolves from v1 (pre-compaction witness) to v2 (post-compaction reference).
    # =========================================================================
    tasks.append(
        TaskSpec(
            task_id="T21",
            category=BugCategory.FEATURE_REGRESSIONS,
            title="Slug separator contract evolution (v1 underscore -> v2 hyphen)",
            specification="v1 used underscores; v2 contract requires lowercase hyphen-separated slugs with max_len truncation and no trailing hyphens.",
            contract_version_initial="v1",
            contract_version_post_compaction="v2",
            target_file="slug.py",
            target_symbol="slugify",
            initial_files={
                "slug.py": "def slugify(text, max_len=20):\n    return text\n"
            },
            witness_name="test_v1_lowercase_underscore_slug",
            witness_test_code=(
                "from slug import slugify\n"
                "def test_v1_lowercase_underscore_slug():\n"
                "    assert slugify('Hello World') == 'hello_world'\n"
            ),
            reference_test_code=(
                "from slug import slugify\n"
                "def test_reference_suite():\n"
                "    assert slugify('Hello World!') == 'hello-world'\n"
                "    assert slugify('  Multiple   Spaces  ') == 'multiple-spaces'\n"
                "    assert slugify('hello-world-long', max_len=11) == 'hello-world'\n"
            ),
            pre_compaction_failed_patch=CandidatePatch(
                patch_id="T21-pre",
                description="Replaces spaces with underscores but forgets .lower()",
                files={
                    "slug.py": (
                        "def slugify(text, max_len=20):\n"
                        "    return text.strip().replace(' ', '_')[:max_len]\n"
                    )
                },
                is_known_regression=True,
                is_valid_solution=False,
                contract_version="v1",
            ),
            verbose_observations=_make_verbose_observations("T21", "slug.py", "slugify"),
            post_compaction_candidates=[
                CandidatePatch(
                    patch_id="T21-c1-reg",
                    description="Alpha-renamed repeat of uppercase underscore bug",
                    files={
                        "slug.py": (
                            "def slugify(title, limit=20):\n"
                            "    return title.strip().replace(' ', '_')[:limit]\n"
                        )
                    },
                    is_known_regression=True,
                    is_valid_solution=False,
                    contract_version="v1",
                ),
                CandidatePatch(
                    patch_id="T21-c2-fix-v2",
                    description="Implements v2 hyphenated lowercase slug contract",
                    files={
                        "slug.py": (
                            "import re\n\n"
                            "def slugify(text, max_len=20):\n"
                            "    cleaned = re.sub(r'[^a-z0-9]+', '-', text.lower()).strip('-')\n"
                            "    return cleaned[:max_len].rstrip('-')\n"
                        )
                    },
                    is_known_regression=False,
                    is_valid_solution=True,
                    contract_version="v2",
                ),
            ],
        )
    )

    tasks.append(
        TaskSpec(
            task_id="T22",
            category=BugCategory.FEATURE_REGRESSIONS,
            title="Config lookup missing-key policy evolution (v1 None -> v2 KeyError)",
            specification="v1 returned None on unknown keys; v2 contract requires raising KeyError on unknown keys while merging overrides over defaults.",
            contract_version_initial="v1",
            contract_version_post_compaction="v2",
            target_file="config_loader.py",
            target_symbol="get_config_value",
            initial_files={
                "config_loader.py": "def get_config_value(defaults, overrides, key):\n    return defaults[key]\n"
            },
            witness_name="test_v1_unknown_key_returns_none",
            witness_test_code=(
                "from config_loader import get_config_value\n"
                "def test_v1_unknown_key_returns_none():\n"
                "    assert get_config_value({'a': 1}, {'b': 2}, 'missing') is None\n"
            ),
            reference_test_code=(
                "from config_loader import get_config_value\n"
                "def test_reference_suite():\n"
                "    d = {'host': 'localhost', 'port': 8080}\n"
                "    o = {'port': 9090}\n"
                "    assert get_config_value(d, o, 'port') == 9090\n"
                "    assert get_config_value(d, o, 'host') == 'localhost'\n"
                "    assert d == {'host': 'localhost', 'port': 8080}\n"
                "    raised = False\n"
                "    try:\n"
                "        get_config_value(d, o, 'missing')\n"
                "    except KeyError:\n"
                "        raised = True\n"
                "    assert raised\n"
            ),
            pre_compaction_failed_patch=CandidatePatch(
                patch_id="T22-pre",
                description="Returns empty string '' instead of None under v1",
                files={
                    "config_loader.py": (
                        "def get_config_value(defaults, overrides, key):\n"
                        "    merged = dict(defaults)\n"
                        "    merged.update(overrides)\n"
                        "    return merged.get(key, '')\n"
                    )
                },
                is_known_regression=True,
                is_valid_solution=False,
                contract_version="v1",
            ),
            verbose_observations=_make_verbose_observations("T22", "config_loader.py", "get_config_value"),
            post_compaction_candidates=[
                CandidatePatch(
                    patch_id="T22-c1-reg",
                    description="Alpha-renamed repeat returning '' on missing key",
                    files={
                        "config_loader.py": (
                            "def get_config_value(base, custom, name):\n"
                            "    combined = dict(base)\n"
                            "    combined.update(custom)\n"
                            "    return combined.get(name, '')\n"
                        )
                    },
                    is_known_regression=True,
                    is_valid_solution=False,
                    contract_version="v1",
                ),
                CandidatePatch(
                    patch_id="T22-c2-fix-v2",
                    description="Implements v2 strict KeyError contract without mutating defaults",
                    files={
                        "config_loader.py": (
                            "def get_config_value(defaults, overrides, key):\n"
                            "    merged = {**defaults, **overrides}\n"
                            "    if key not in merged:\n"
                            "        raise KeyError(f'Missing required key: {key}')\n"
                            "    return merged[key]\n"
                        )
                    },
                    is_known_regression=False,
                    is_valid_solution=True,
                    contract_version="v2",
                ),
            ],
        )
    )

    tasks.append(
        TaskSpec(
            task_id="T23",
            category=BugCategory.FEATURE_REGRESSIONS,
            title="Heavy freight shipping fee policy evolution (v1 free >=50kg -> v2 surcharge)",
            specification="v1 gave free shipping for weight >= 50kg; v2 contract charges base (weight * 2.0) plus a 25.0 heavy surcharge for weight >= 50kg.",
            contract_version_initial="v1",
            contract_version_post_compaction="v2",
            target_file="shipping.py",
            target_symbol="shipping_fee",
            initial_files={
                "shipping.py": "def shipping_fee(weight_kg):\n    return weight_kg * 2.0\n"
            },
            witness_name="test_v1_free_shipping_at_50kg",
            witness_test_code=(
                "from shipping import shipping_fee\n"
                "def test_v1_free_shipping_at_50kg():\n"
                "    assert shipping_fee(50.0) == 0.0\n"
            ),
            reference_test_code=(
                "from shipping import shipping_fee\n"
                "def test_reference_suite():\n"
                "    assert shipping_fee(10.0) == 20.0\n"
                "    assert shipping_fee(50.0) == 125.0\n"
                "    assert shipping_fee(60.0) == 145.0\n"
            ),
            pre_compaction_failed_patch=CandidatePatch(
                patch_id="T23-pre",
                description="Uses > 50.0 instead of >= 50.0 under v1",
                files={
                    "shipping.py": (
                        "def shipping_fee(weight_kg):\n"
                        "    if weight_kg > 50.0:\n"
                        "        return 0.0\n"
                        "    return weight_kg * 2.0\n"
                    )
                },
                is_known_regression=True,
                is_valid_solution=False,
                contract_version="v1",
            ),
            verbose_observations=_make_verbose_observations("T23", "shipping.py", "shipping_fee"),
            post_compaction_candidates=[
                CandidatePatch(
                    patch_id="T23-c1-reg",
                    description="Alpha-renamed repeat of v1 > 50.0 bug",
                    files={
                        "shipping.py": (
                            "def shipping_fee(kg):\n"
                            "    if kg > 50.0:\n"
                            "        return 0.0\n"
                            "    return kg * 2.0\n"
                        )
                    },
                    is_known_regression=True,
                    is_valid_solution=False,
                    contract_version="v1",
                ),
                CandidatePatch(
                    patch_id="T23-c2-fix-v2",
                    description="Implements v2 heavy freight surcharge >= 50kg",
                    files={
                        "shipping.py": (
                            "def shipping_fee(weight_kg):\n"
                            "    if weight_kg < 0:\n"
                            "        raise ValueError('Negative weight')\n"
                            "    base = weight_kg * 2.0\n"
                            "    return base + 25.0 if weight_kg >= 50.0 else base\n"
                        )
                    },
                    is_known_regression=False,
                    is_valid_solution=True,
                    contract_version="v2",
                ),
            ],
        )
    )

    tasks.append(
        TaskSpec(
            task_id="T24",
            category=BugCategory.FEATURE_REGRESSIONS,
            title="PII redaction token evolution (v1 '***' -> v2 '[REDACTED]')",
            specification="v1 masked sensitive keys ('password', 'api_key') with '***'; v2 contract requires masking them with '[REDACTED]'.",
            contract_version_initial="v1",
            contract_version_post_compaction="v2",
            target_file="redactor.py",
            target_symbol="redact_payload",
            initial_files={
                "redactor.py": "def redact_payload(data):\n    return dict(data)\n"
            },
            witness_name="test_v1_api_key_masked_with_asterisks",
            witness_test_code=(
                "from redactor import redact_payload\n"
                "def test_v1_api_key_masked_with_asterisks():\n"
                "    assert redact_payload({'user': 'bob', 'api_key': 'secret123'}) == {'user': 'bob', 'api_key': '***'}\n"
            ),
            reference_test_code=(
                "from redactor import redact_payload\n"
                "def test_reference_suite():\n"
                "    orig = {'user': 'bob', 'api_key': 's1', 'password': 'p1'}\n"
                "    assert redact_payload(orig) == {'user': 'bob', 'api_key': '[REDACTED]', 'password': '[REDACTED]'}\n"
                "    assert orig['api_key'] == 's1'\n"
            ),
            pre_compaction_failed_patch=CandidatePatch(
                patch_id="T24-pre",
                description="Redacts 'password' with '***' but forgets 'api_key'",
                files={
                    "redactor.py": (
                        "def redact_payload(data):\n"
                        "    out = dict(data)\n"
                        "    if 'password' in out:\n"
                        "        out['password'] = '***'\n"
                        "    return out\n"
                    )
                },
                is_known_regression=True,
                is_valid_solution=False,
                contract_version="v1",
            ),
            verbose_observations=_make_verbose_observations("T24", "redactor.py", "redact_payload"),
            post_compaction_candidates=[
                CandidatePatch(
                    patch_id="T24-c1-reg",
                    description="Alpha-renamed repeat forgetting 'api_key'",
                    files={
                        "redactor.py": (
                            "def redact_payload(record):\n"
                            "    res = dict(record)\n"
                            "    if 'password' in res:\n"
                            "        res['password'] = '***'\n"
                            "    return res\n"
                        )
                    },
                    is_known_regression=True,
                    is_valid_solution=False,
                    contract_version="v1",
                ),
                CandidatePatch(
                    patch_id="T24-c2-fix-v2",
                    description="Implements v2 '[REDACTED]' marker across all sensitive keys",
                    files={
                        "redactor.py": (
                            "SENSITIVE = {'password', 'api_key', 'secret'}\n\n"
                            "def redact_payload(data):\n"
                            "    return {\n"
                            "        k: ('[REDACTED]' if k in SENSITIVE else v)\n"
                            "        for k, v in data.items()\n"
                            "    }\n"
                        )
                    },
                    is_known_regression=False,
                    is_valid_solution=True,
                    contract_version="v2",
                ),
            ],
        )
    )

    tasks.append(
        TaskSpec(
            task_id="T25",
            category=BugCategory.FEATURE_REGRESSIONS,
            title="Negative currency formatting evolution (v1 '-$12.50' -> v2 '($12.50)')",
            specification="v1 formatted negative cents with leading minus '-$12.50'; v2 accounting contract requires parenthesized '($12.50)'.",
            contract_version_initial="v1",
            contract_version_post_compaction="v2",
            target_file="money.py",
            target_symbol="format_usd",
            initial_files={
                "money.py": "def format_usd(cents):\n    return f'${cents / 100:.2f}'\n"
            },
            witness_name="test_v1_negative_cents_leading_minus",
            witness_test_code=(
                "from money import format_usd\n"
                "def test_v1_negative_cents_leading_minus():\n"
                "    assert format_usd(-1250) == '-$12.50'\n"
            ),
            reference_test_code=(
                "from money import format_usd\n"
                "def test_reference_suite():\n"
                "    assert format_usd(-1250) == '($12.50)'\n"
                "    assert format_usd(1250) == '$12.50'\n"
                "    assert format_usd(0) == '$0.00'\n"
            ),
            pre_compaction_failed_patch=CandidatePatch(
                patch_id="T25-pre",
                description="Places minus sign after dollar sign '$-12.50'",
                files={
                    "money.py": (
                        "def format_usd(cents):\n"
                        "    return f'${cents / 100:.2f}'\n"
                    )
                },
                is_known_regression=True,
                is_valid_solution=False,
                contract_version="v1",
            ),
            verbose_observations=_make_verbose_observations("T25", "money.py", "format_usd"),
            post_compaction_candidates=[
                CandidatePatch(
                    patch_id="T25-c1-reg",
                    description="Alpha-renamed repeat producing '$-12.50'",
                    files={
                        "money.py": (
                            "def format_usd(amount_cents):\n"
                            "    return f'${amount_cents / 100:.2f}'\n"
                        )
                    },
                    is_known_regression=True,
                    is_valid_solution=False,
                    contract_version="v1",
                ),
                CandidatePatch(
                    patch_id="T25-c2-fix-v2",
                    description="Implements v2 accounting parentheses for negative cents",
                    files={
                        "money.py": (
                            "def format_usd(cents):\n"
                            "    abs_c = abs(cents)\n"
                            "    body = f'${abs_c // 100}.{abs_c % 100:02d}'\n"
                            "    return f'({body})' if cents < 0 else body\n"
                        )
                    },
                    is_known_regression=False,
                    is_valid_solution=True,
                    contract_version="v2",
                ),
            ],
        )
    )

    # =========================================================================
    # CATEGORY 6: SYNTACTIC VARIANTS OF THE SAME LOGICAL BUG (T26 - T30)
    # Candidate 1 has a DIFFERENT canonical AST structure from pre_compaction_failed_patch,
    # proving why AST hashing alone is insufficient and Witness Replay is required.
    # =========================================================================
    tasks.append(
        TaskSpec(
            task_id="T26",
            category=BugCategory.SYNTACTIC_VARIANTS,
            title="Zero score dropped by truthiness filter (for-loop vs list comprehension)",
            specification="Implement `keep_valid_scores(scores: list[int | None]) -> list[int]` keeping all integers in [0, 100] including 0.",
            contract_version_initial="v1",
            contract_version_post_compaction="v1",
            target_file="scores.py",
            target_symbol="keep_valid_scores",
            initial_files={
                "scores.py": "def keep_valid_scores(scores):\n    return []\n"
            },
            witness_name="test_zero_score_preserved",
            witness_test_code=(
                "from scores import keep_valid_scores\n"
                "def test_zero_score_preserved():\n"
                "    assert keep_valid_scores([0, 50, None, 100]) == [0, 50, 100]\n"
            ),
            reference_test_code=(
                "from scores import keep_valid_scores\n"
                "def test_reference_suite():\n"
                "    assert keep_valid_scores([0, 50, None, 100, -1, 105]) == [0, 50, 100]\n"
                "    assert keep_valid_scores([None]) == []\n"
            ),
            pre_compaction_failed_patch=CandidatePatch(
                patch_id="T26-pre",
                description="For-loop using truthiness `if s:` which drops 0",
                files={
                    "scores.py": (
                        "def keep_valid_scores(scores):\n"
                        "    res = []\n"
                        "    for s in scores:\n"
                        "        if s and 0 <= s <= 100:\n"
                        "            res.append(s)\n"
                        "    return res\n"
                    )
                },
                is_known_regression=True,
                is_valid_solution=False,
                contract_version="v1",
            ),
            verbose_observations=_make_verbose_observations("T26", "scores.py", "keep_valid_scores"),
            post_compaction_candidates=[
                CandidatePatch(
                    patch_id="T26-c1-synvar",
                    description="Syntactic variant: list comprehension with bool(s) filter that still drops 0",
                    files={
                        "scores.py": (
                            "def keep_valid_scores(scores):\n"
                            "    return [s for s in scores if bool(s) and s <= 100 and s >= 0]\n"
                        )
                    },
                    is_known_regression=True,
                    is_valid_solution=False,
                    contract_version="v1",
                    syntactic_variant_of="T26-pre",
                ),
                CandidatePatch(
                    patch_id="T26-c2-fix",
                    description="Explicit `s is not None` check preserving 0",
                    files={
                        "scores.py": (
                            "def keep_valid_scores(scores):\n"
                            "    return [s for s in scores if s is not None and 0 <= s <= 100]\n"
                        )
                    },
                    is_known_regression=False,
                    is_valid_solution=True,
                    contract_version="v1",
                ),
            ],
        )
    )

    tasks.append(
        TaskSpec(
            task_id="T27",
            category=BugCategory.SYNTACTIC_VARIANTS,
            title="Order-destroying deduplication (sorted(set) vs list.sort())",
            specification="Implement `dedup_ordered(items: list) -> list` removing duplicates while preserving first-seen order.",
            contract_version_initial="v1",
            contract_version_post_compaction="v1",
            target_file="collections_ext.py",
            target_symbol="dedup_ordered",
            initial_files={
                "collections_ext.py": "def dedup_ordered(items):\n    return items\n"
            },
            witness_name="test_insertion_order_preserved_on_unsorted_input",
            witness_test_code=(
                "from collections_ext import dedup_ordered\n"
                "def test_insertion_order_preserved_on_unsorted_input():\n"
                "    assert dedup_ordered(['z', 'a', 'z', 'm']) == ['z', 'a', 'm']\n"
            ),
            reference_test_code=(
                "from collections_ext import dedup_ordered\n"
                "def test_reference_suite():\n"
                "    assert dedup_ordered(['z', 'a', 'z', 'm']) == ['z', 'a', 'm']\n"
                "    assert dedup_ordered([3, 1, 2, 1, 3]) == [3, 1, 2]\n"
                "    assert dedup_ordered([]) == []\n"
            ),
            pre_compaction_failed_patch=CandidatePatch(
                patch_id="T27-pre",
                description="Uses sorted(set(items)) which sorts lexicographically instead of preserving first-seen order",
                files={
                    "collections_ext.py": (
                        "def dedup_ordered(items):\n"
                        "    return sorted(list(set(items)))\n"
                    )
                },
                is_known_regression=True,
                is_valid_solution=False,
                contract_version="v1",
            ),
            verbose_observations=_make_verbose_observations("T27", "collections_ext.py", "dedup_ordered"),
            post_compaction_candidates=[
                CandidatePatch(
                    patch_id="T27-c1-synvar",
                    description="Syntactic variant: imperative loop calling out.sort() at end",
                    files={
                        "collections_ext.py": (
                            "def dedup_ordered(items):\n"
                            "    out = []\n"
                            "    for x in items:\n"
                            "        if x not in out:\n"
                            "            out.append(x)\n"
                            "    out.sort()\n"
                            "    return out\n"
                        )
                    },
                    is_known_regression=True,
                    is_valid_solution=False,
                    contract_version="v1",
                    syntactic_variant_of="T27-pre",
                ),
                CandidatePatch(
                    patch_id="T27-c2-fix",
                    description="Preserves insertion order using a seen set",
                    files={
                        "collections_ext.py": (
                            "def dedup_ordered(items):\n"
                            "    seen = set()\n"
                            "    out = []\n"
                            "    for x in items:\n"
                            "        if x not in seen:\n"
                            "            seen.add(x)\n"
                            "            out.append(x)\n"
                            "    return out\n"
                        )
                    },
                    is_known_regression=False,
                    is_valid_solution=True,
                    contract_version="v1",
                ),
            ],
        )
    )

    tasks.append(
        TaskSpec(
            task_id="T28",
            category=BugCategory.SYNTACTIC_VARIANTS,
            title="Zero timeout overridden by truthy fallback (if-else vs boolean `or`)",
            specification="Implement `resolve_timeout(opts: dict, default: int = 30) -> int` preserving explicit `timeout=0`.",
            contract_version_initial="v1",
            contract_version_post_compaction="v1",
            target_file="options.py",
            target_symbol="resolve_timeout",
            initial_files={
                "options.py": "def resolve_timeout(opts, default=30):\n    return default\n"
            },
            witness_name="test_explicit_zero_timeout_preserved",
            witness_test_code=(
                "from options import resolve_timeout\n"
                "def test_explicit_zero_timeout_preserved():\n"
                "    assert resolve_timeout({'timeout': 0}, default=30) == 0\n"
            ),
            reference_test_code=(
                "from options import resolve_timeout\n"
                "def test_reference_suite():\n"
                "    assert resolve_timeout({'timeout': 0}, default=30) == 0\n"
                "    assert resolve_timeout({'timeout': 15}, default=30) == 15\n"
                "    assert resolve_timeout({}, default=30) == 30\n"
                "    assert resolve_timeout({'timeout': None}, default=30) == 30\n"
            ),
            pre_compaction_failed_patch=CandidatePatch(
                patch_id="T28-pre",
                description="Uses `if val:` branch which treats 0 as falsy",
                files={
                    "options.py": (
                        "def resolve_timeout(opts, default=30):\n"
                        "    val = opts.get('timeout')\n"
                        "    if val:\n"
                        "        return val\n"
                        "    return default\n"
                    )
                },
                is_known_regression=True,
                is_valid_solution=False,
                contract_version="v1",
            ),
            verbose_observations=_make_verbose_observations("T28", "options.py", "resolve_timeout"),
            post_compaction_candidates=[
                CandidatePatch(
                    patch_id="T28-c1-synvar",
                    description="Syntactic variant: short-circuit `opts.get('timeout') or default` expression",
                    files={
                        "options.py": (
                            "def resolve_timeout(opts, default=30):\n"
                            "    return opts.get('timeout') or default\n"
                        )
                    },
                    is_known_regression=True,
                    is_valid_solution=False,
                    contract_version="v1",
                    syntactic_variant_of="T28-pre",
                ),
                CandidatePatch(
                    patch_id="T28-c2-fix",
                    description="Checks `val is None` explicitly",
                    files={
                        "options.py": (
                            "def resolve_timeout(opts, default=30):\n"
                            "    val = opts.get('timeout')\n"
                            "    return default if val is None else int(val)\n"
                        )
                    },
                    is_known_regression=False,
                    is_valid_solution=True,
                    contract_version="v1",
                ),
            ],
        )
    )

    tasks.append(
        TaskSpec(
            task_id="T29",
            category=BugCategory.SYNTACTIC_VARIANTS,
            title="Parent directory '..' resolution in path normalizer (comprehension vs loop skip)",
            specification="Implement `normalize_relpath(path: str) -> str` resolving `.` and popping the previous segment on `..`.",
            contract_version_initial="v1",
            contract_version_post_compaction="v1",
            target_file="path_utils.py",
            target_symbol="normalize_relpath",
            initial_files={
                "path_utils.py": "def normalize_relpath(path):\n    return path\n"
            },
            witness_name="test_parent_dotdot_pops_previous_segment",
            witness_test_code=(
                "from path_utils import normalize_relpath\n"
                "def test_parent_dotdot_pops_previous_segment():\n"
                "    assert normalize_relpath('src/utils/../core/main.py') == 'src/core/main.py'\n"
            ),
            reference_test_code=(
                "from path_utils import normalize_relpath\n"
                "def test_reference_suite():\n"
                "    assert normalize_relpath('src/utils/../core/main.py') == 'src/core/main.py'\n"
                "    assert normalize_relpath('a/./b//c/') == 'a/b/c'\n"
                "    assert normalize_relpath('a/b/..') == 'a'\n"
            ),
            pre_compaction_failed_patch=CandidatePatch(
                patch_id="T29-pre",
                description="List comprehension simply dropping '..' instead of popping parent segment",
                files={
                    "path_utils.py": (
                        "def normalize_relpath(path):\n"
                        "    parts = [p for p in path.split('/') if p and p not in ('.', '..')]\n"
                        "    return '/'.join(parts)\n"
                    )
                },
                is_known_regression=True,
                is_valid_solution=False,
                contract_version="v1",
            ),
            verbose_observations=_make_verbose_observations("T29", "path_utils.py", "normalize_relpath"),
            post_compaction_candidates=[
                CandidatePatch(
                    patch_id="T29-c1-synvar",
                    description="Syntactic variant: imperative for-loop skipping '..' with continue",
                    files={
                        "path_utils.py": (
                            "def normalize_relpath(path):\n"
                            "    acc = []\n"
                            "    for seg in path.split('/'):\n"
                            "        if seg == '' or seg == '.' or seg == '..':\n"
                            "            continue\n"
                            "        acc.append(seg)\n"
                            "    return '/'.join(acc)\n"
                        )
                    },
                    is_known_regression=True,
                    is_valid_solution=False,
                    contract_version="v1",
                    syntactic_variant_of="T29-pre",
                ),
                CandidatePatch(
                    patch_id="T29-c2-fix",
                    description="Pops from segment stack on '..'",
                    files={
                        "path_utils.py": (
                            "def normalize_relpath(path):\n"
                            "    stack = []\n"
                            "    for seg in path.split('/'):\n"
                            "        if not seg or seg == '.':\n"
                            "            continue\n"
                            "        if seg == '..':\n"
                            "            if stack:\n"
                            "                stack.pop()\n"
                            "        else:\n"
                            "            stack.append(seg)\n"
                            "    return '/'.join(stack)\n"
                        )
                    },
                    is_known_regression=False,
                    is_valid_solution=True,
                    contract_version="v1",
                ),
            ],
        )
    )

    tasks.append(
        TaskSpec(
            task_id="T30",
            category=BugCategory.SYNTACTIC_VARIANTS,
            title="Even-length median calculation (upper-middle index vs float average)",
            specification="Implement `median_value(nums: list[float]) -> float` averaging the two middle values when `len(nums)` is even.",
            contract_version_initial="v1",
            contract_version_post_compaction="v1",
            target_file="metrics.py",
            target_symbol="median_value",
            initial_files={
                "metrics.py": "def median_value(nums):\n    return 0.0\n"
            },
            witness_name="test_even_length_median_averages_two_middle_elements",
            witness_test_code=(
                "from metrics import median_value\n"
                "def test_even_length_median_averages_two_middle_elements():\n"
                "    assert median_value([1.0, 2.0, 4.0, 10.0]) == 3.0\n"
            ),
            reference_test_code=(
                "from metrics import median_value\n"
                "def test_reference_suite():\n"
                "    assert median_value([1.0, 2.0, 4.0, 10.0]) == 3.0\n"
                "    assert median_value([10.0, 2.0, 5.0]) == 5.0\n"
                "    assert median_value([7.0]) == 7.0\n"
            ),
            pre_compaction_failed_patch=CandidatePatch(
                patch_id="T30-pre",
                description="Takes single element s[len(s) // 2] for both odd and even lengths",
                files={
                    "metrics.py": (
                        "def median_value(nums):\n"
                        "    s = sorted(nums)\n"
                        "    return float(s[len(s) // 2])\n"
                    )
                },
                is_known_regression=True,
                is_valid_solution=False,
                contract_version="v1",
            ),
            verbose_observations=_make_verbose_observations("T30", "metrics.py", "median_value"),
            post_compaction_candidates=[
                CandidatePatch(
                    patch_id="T30-c1-synvar",
                    description="Syntactic variant: in-place sort and int(len * 0.5) indexing",
                    files={
                        "metrics.py": (
                            "def median_value(nums):\n"
                            "    copied = list(nums)\n"
                            "    copied.sort()\n"
                            "    mid_idx = int(len(copied) * 0.5)\n"
                            "    return copied[mid_idx] if copied else 0.0\n"
                        )
                    },
                    is_known_regression=True,
                    is_valid_solution=False,
                    contract_version="v1",
                    syntactic_variant_of="T30-pre",
                ),
                CandidatePatch(
                    patch_id="T30-c2-fix",
                    description="Averages s[mid - 1] and s[mid] when length is even",
                    files={
                        "metrics.py": (
                            "def median_value(nums):\n"
                            "    if not nums:\n"
                            "        raise ValueError('Empty sequence')\n"
                            "    s = sorted(nums)\n"
                            "    n = len(s)\n"
                            "    mid = n // 2\n"
                            "    if n % 2 == 1:\n"
                            "        return float(s[mid])\n"
                            "    return (s[mid - 1] + s[mid]) / 2.0\n"
                        )
                    },
                    is_known_regression=False,
                    is_valid_solution=True,
                    contract_version="v1",
                ),
            ],
        )
    )

    _attach_partial_witness_challenges(tasks)
    return tasks


def _attach_partial_witness_challenges(tasks: List[TaskSpec]) -> None:
    """Enriches benchmark tasks with Partial Witness Coverage and Lossy Distractor candidates.

    Each `partial_coverage_candidate` passes the initial witness assertion (`witness_test_code`),
    so a first-round RegressionGate legitimately returns `PASS`, but fails a secondary edge case
    in the full reference oracle (`reference_test_code`), triggering a second CEGAR refinement round.
    """
    by_id = {t.task_id: t for t in tasks}

    # T01: Passes witness (0 -> 1), but forgets upper bound clamp (> max_limit)
    by_id["T01"].partial_coverage_candidates = [
        CandidatePatch(
            patch_id="T01-c1b-partial",
            description="Fixes <= 0 lower bound (passes witness) but omits > max_limit upper clamp",
            files={
                "pagination.py": (
                    "def clamp_limit(limit, max_limit=100):\n"
                    "    if limit <= 0:\n"
                    "        return 1\n"
                    "    return limit\n"
                )
            },
            is_known_regression=False,
            is_valid_solution=False,
            contract_version="v1",
        )
    ]

    # T03: Passes witness ([5, 5, 5, 9], 5 -> 0), but returns insertion index instead of -1 when missing
    by_id["T03"].partial_coverage_candidates = [
        CandidatePatch(
            patch_id="T03-c1b-partial",
            description="Contracts high bound on >= target (passes witness) but omits final equality guard",
            files={
                "bsearch.py": (
                    "def search_leftmost(arr, target):\n"
                    "    if not arr:\n"
                    "        return -1\n"
                    "    lo, hi = 0, len(arr) - 1\n"
                    "    while lo < hi:\n"
                    "        mid = (lo + hi) // 2\n"
                    "        if arr[mid] < target:\n"
                    "            lo = mid + 1\n"
                    "        else:\n"
                    "            hi = mid\n"
                    "    return lo\n"
                )
            },
            is_known_regression=False,
            is_valid_solution=False,
            contract_version="v1",
        )
    ]

    # T08: Passes witness (single line with '=' in value), but fails to skip '#' comment lines
    by_id["T08"].partial_coverage_candidates = [
        CandidatePatch(
            patch_id="T08-c1b-partial",
            description="Uses partition('=') (passes witness) but forgets to ignore '#' comment lines",
            files={
                "ini_parser.py": (
                    "def parse_kv_lines(text):\n"
                    "    out = {}\n"
                    "    for line in text.splitlines():\n"
                    "        line = line.strip()\n"
                    "        if '=' in line:\n"
                    "            k, _, v = line.partition('=')\n"
                    "            out[k.strip()] = v.strip()\n"
                    "        elif line:\n"
                    "            out[line] = ''\n"
                    "    return out\n"
                )
            },
            is_known_regression=False,
            is_valid_solution=False,
            contract_version="v1",
        )
    ]

    # T10: Passes witness (ERROR + RESET -> IDLE), but only allows RESET from ERROR, failing CONNECTED + RESET
    by_id["T10"].partial_coverage_candidates = [
        CandidatePatch(
            patch_id="T10-c1b-partial",
            description="Handles RESET only when state == 'ERROR' (passes witness, fails CONNECTED -> RESET)",
            files={
                "protocol.py": (
                    "def next_state(state, event):\n"
                    "    if state == 'ERROR' and event == 'RESET':\n"
                    "        return 'IDLE'\n"
                    "    if state == 'IDLE' and event == 'CONNECT':\n"
                    "        return 'CONNECTING'\n"
                    "    if state == 'CONNECTING' and event == 'ACK':\n"
                    "        return 'CONNECTED'\n"
                    "    if state == 'CONNECTING' and event == 'FAIL':\n"
                    "        return 'ERROR'\n"
                    "    raise ValueError(f'Invalid transition: {state} -> {event}')\n"
                )
            },
            is_known_regression=False,
            is_valid_solution=False,
            contract_version="v1",
        )
    ]

    # T13: Passes witness ({'user': None} raises KeyError), but returns None instead of raising KeyError on missing leaf
    by_id["T13"].partial_coverage_candidates = [
        CandidatePatch(
            patch_id="T13-c1b-partial",
            description="Raises KeyError when curr is None (passes witness) but uses curr.get(part) returning None on missing leaf",
            files={
                "lookup.py": (
                    "def deep_get(data, dotted_path):\n"
                    "    curr = data\n"
                    "    for part in dotted_path.split('.'):\n"
                    "        if not isinstance(curr, dict):\n"
                    "            raise KeyError(dotted_path)\n"
                    "        curr = curr.get(part)\n"
                    "    if curr is None:\n"
                    "        raise KeyError(dotted_path)\n"
                    "    return out_val if (out_val := curr) != 'a@b.c' else None\n"
                )
            },
            is_known_regression=False,
            is_valid_solution=False,
            contract_version="v1",
        )
    ]

    # T20 (Multi-constraint): Two chained partial candidates that both pass the cycle witness (return -1 on unreachable)
    # 1) Returns 1 instead of 0 when src == dst
    # 2) Uses DFS stack (pop()) instead of BFS queue (popleft()), finding non-shortest hop count
    by_id["T20"].partial_coverage_candidates = [
        CandidatePatch(
            patch_id="T20-c1b-partial1",
            description="Tracks visited set (passes cycle witness) but omits src == dst zero-hop check",
            files={
                "graph_store.py": "def neighbors(adj, node):\n    return list(adj.get(node, []))\n",
                "path_finder.py": (
                    "from collections import deque\n"
                    "from graph_store import neighbors\n\n"
                    "def shortest_hop_count(adj, src, dst):\n"
                    "    visited = {src}\n"
                    "    queue = deque([(src, 0)])\n"
                    "    while queue:\n"
                    "        node, dist = queue.popleft()\n"
                    "        for nxt in neighbors(adj, node):\n"
                    "            if nxt == dst:\n"
                    "                return dist + 1\n"
                    "            if nxt not in visited:\n"
                    "                visited.add(nxt)\n"
                    "                queue.append((nxt, dist + 1))\n"
                    "    return -1\n"
                ),
            },
            is_known_regression=False,
            is_valid_solution=False,
            contract_version="v1",
        ),
        CandidatePatch(
            patch_id="T20-c1c-partial2",
            description="Handles src == dst and cycles (passes witness) but off-by-one initial distance = 1",
            files={
                "graph_store.py": "def neighbors(adj, node):\n    return list(adj.get(node, []))\n",
                "path_finder.py": (
                    "from collections import deque\n"
                    "from graph_store import neighbors\n\n"
                    "def shortest_hop_count(adj, src, dst):\n"
                    "    if src == dst:\n"
                    "        return 0\n"
                    "    visited = {src}\n"
                    "    queue = deque([(src, 1)])\n"
                    "    while queue:\n"
                    "        node, dist = queue.popleft()\n"
                    "        for nxt in neighbors(adj, node):\n"
                    "            if nxt == dst:\n"
                    "                return dist + 1\n"
                    "            if nxt not in visited:\n"
                    "                visited.add(nxt)\n"
                    "                queue.append((nxt, dist + 1))\n"
                    "    return -1\n"
                ),
            },
            is_known_regression=False,
            is_valid_solution=False,
            contract_version="v1",
        ),
    ]

    # T28 (Cat 6 + Partial): Passes witness ({'timeout': 0} -> 0), but fails when {'timeout': None} is passed (TypeError: int(None))
    by_id["T28"].partial_coverage_candidates = [
        CandidatePatch(
            patch_id="T28-c1b-partial",
            description="Uses `'timeout' in opts` check (passes witness on 0) but crashes on {'timeout': None}",
            files={
                "options.py": (
                    "def resolve_timeout(opts, default=30):\n"
                    "    if 'timeout' in opts:\n"
                    "        return int(opts['timeout'])\n"
                    "    return default\n"
                )
            },
            is_known_regression=False,
            is_valid_solution=False,
            contract_version="v1",
        )
    ]

    # T29 (Cat 6 + Partial): Passes witness ('src/utils/../core/main.py'), but forgets to skip '.' segments ('a/./b//c/')
    by_id["T29"].partial_coverage_candidates = [
        CandidatePatch(
            patch_id="T29-c1b-partial",
            description="Pops stack on '..' (passes witness) but fails to ignore '.' current-dir segments",
            files={
                "path_utils.py": (
                    "def normalize_relpath(path):\n"
                    "    stack = []\n"
                    "    for seg in path.split('/'):\n"
                    "        if not seg:\n"
                    "            continue\n"
                    "        if seg == '..':\n"
                    "            if stack:\n"
                    "                stack.pop()\n"
                    "        else:\n"
                    "            stack.append(seg)\n"
                    "    return '/'.join(stack)\n"
                )
            },
            is_known_regression=False,
            is_valid_solution=False,
            contract_version="v1",
        )
    ]

    # T30 (Cat 6 + 2 Chained Partials):
    # 1) Averages middle elements without sorting first (passes already-sorted witness [1, 2, 4, 10], fails unsorted [10, 2, 5])
    # 2) Sorts and averages even-length (passes witness), but uses mid - 1 on odd-length lists (fails single-element/odd test)
    by_id["T30"].partial_coverage_candidates = [
        CandidatePatch(
            patch_id="T30-c1b-partial1",
            description="Averages middle two on even length without sorting first (passes sorted witness, fails unsorted)",
            files={
                "metrics.py": (
                    "def median_value(nums):\n"
                    "    n = len(nums)\n"
                    "    mid = n // 2\n"
                    "    if n % 2 == 1:\n"
                    "        return float(nums[mid])\n"
                    "    return (nums[mid - 1] + nums[mid]) / 2.0\n"
                )
            },
            is_known_regression=False,
            is_valid_solution=False,
            contract_version="v1",
        ),
        CandidatePatch(
            patch_id="T30-c1c-partial2",
            description="Sorts and averages even lengths (passes witness) but uses (s[mid-1]+s[mid])/2 unconditionally on odd lengths",
            files={
                "metrics.py": (
                    "def median_value(nums):\n"
                    "    s = sorted(nums)\n"
                    "    mid = len(s) // 2\n"
                    "    return (s[mid - 1] + s[mid]) / 2.0\n"
                )
            },
            is_known_regression=False,
            is_valid_solution=False,
            contract_version="v1",
        ),
    ]

    # Lossy narrative summarization distractors on 4 stateful/multi-file tasks (T07, T16, T17, T18)
    by_id["T07"].lossy_distractor_candidates = [
        CandidatePatch(
            patch_id="T07-lossy-distractor",
            description="Only checks parentheses count without square/curly brackets when trace is lost",
            files={
                "brackets.py": (
                    "def is_balanced(expr):\n"
                    "    return expr.count('(') == expr.count(')')\n"
                )
            },
            is_known_regression=False,
            is_valid_solution=False,
            contract_version="v1",
        )
    ]
    by_id["T16"].lossy_distractor_candidates = [
        CandidatePatch(
            patch_id="T16-lossy-distractor",
            description="Uses <= token['exp'] off-by-one boundary after lossy summary strips exact timestamp trace",
            files={
                "auth_tokens.py": "def issue_token(user_id, issued_at_s, ttl_s):\n    return {'uid': user_id, 'exp': issued_at_s + ttl_s}\n",
                "session_guard.py": "def is_token_valid(token, now_s):\n    return bool(token.get('uid')) and now_s <= token['exp']\n",
            },
            is_known_regression=False,
            is_valid_solution=False,
            contract_version="v1",
        )
    ]
    by_id["T17"].lossy_distractor_candidates = [
        CandidatePatch(
            patch_id="T17-lossy-distractor",
            description="Normalizes email but forgets to strip whitespace on user name across schema.py",
            files={
                "schema.py": "def normalize_user(name, email):\n    return {'name': name, 'email': email.strip().lower()}\n",
                "serializer.py": "from schema import normalize_user\ndef serialize_user(name, email):\n    rec = normalize_user(name, email)\n    return f\"{rec['name']}<{rec['email']}>\"\n",
            },
            is_known_regression=False,
            is_valid_solution=False,
            contract_version="v1",
        )
    ]
    by_id["T18"].lossy_distractor_candidates = [
        CandidatePatch(
            patch_id="T18-lossy-distractor",
            description="Uses strict cost < quota instead of cost <= quota when cross-module contract is summarized",
            files={
                "rate_limiter.py": "def consume(quota, cost):\n    if cost < quota:\n        return (True, quota - cost)\n    return (False, quota)\n",
                "api_gateway.py": "from rate_limiter import consume\ndef handle_request(quota, cost):\n    allowed, _ = consume(quota, cost)\n    return 200 if allowed else 429\n",
            },
            is_known_regression=False,
            is_valid_solution=False,
            contract_version="v1",
        )
    ]


def get_tasks_by_id() -> Dict[str, TaskSpec]:
    """Returns a dictionary mapping task_id -> TaskSpec."""
    return {t.task_id: t for t in get_all_tasks()}

