"""Unit tests for the optional AST canonicalization filter."""

from cegar_harness.ast_filter import compute_canonical_ast_hash


def test_ast_hash_invariant_to_comments_docstrings_and_alpha_renaming() -> None:
    patch_a = {
        "mod.py": '''
def clamp_value(x, lo, hi):
    """Docstring A."""
    # Some comment
    res = x
    if res < lo:
        return lo
    return res
'''
    }
    patch_b = {
        "mod.py": '''
def clamp_value(val, min_b, max_b):
    """Completely different docstring."""
    out = val
    if out < min_b:
        return min_b
    return out
'''
    }
    assert compute_canonical_ast_hash(patch_a) == compute_canonical_ast_hash(patch_b)


def test_ast_hash_differs_on_syntactic_variants_of_same_bug() -> None:
    """Demonstrates why AST hashing alone is NOT semantic equivalence."""
    patch_if = {
        "mod.py": "def f(x):\n    if x >= 0:\n        return x\n    return 0\n"
    }
    patch_ternary = {
        "mod.py": "def f(x):\n    return x if not (x < 0) else 0\n"
    }
    assert compute_canonical_ast_hash(patch_if) != compute_canonical_ast_hash(patch_ternary)
