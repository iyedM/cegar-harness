"""Optional AST canonicalization filter for fast syntactic duplicate detection.

NOTE ON LIMITATIONS:
Normalized AST hashing detects exact repeats and alpha-renamed local variable variants
(e.g., renaming `x` to `val` or adding comments/docstrings). It does NOT establish
general semantic equivalence. Syntactically distinct implementations of the same
logical bug (e.g., `for` loop vs. list comprehension or inverted boolean guards)
produce different AST hashes and require behavioral Witness Replay for detection.
"""

from __future__ import annotations

import ast
import builtins
import hashlib
from typing import Dict, Set


class _AlphaNormalizer(ast.NodeTransformer):
    """Normalizes local variable and argument identifiers while preserving builtins and attributes."""

    _BUILTINS: Set[str] = set(dir(builtins))

    def __init__(self) -> None:
        super().__init__()
        self._var_map: Dict[str, str] = {}
        self._counter: int = 0

    def _canonical_name(self, name: str) -> str:
        if name in self._BUILTINS or name in {"self", "cls", "True", "False", "None"}:
            return name
        if name not in self._var_map:
            self._var_map[name] = f"_v{self._counter}"
            self._counter += 1
        return self._var_map[name]

    def _strip_docstring(self, body: list[ast.stmt]) -> list[ast.stmt]:
        if (
            body
            and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)
        ):
            return body[1:]
        return body

    def visit_Module(self, node: ast.Module) -> ast.Module:
        node.body = self._strip_docstring(node.body)
        self.generic_visit(node)
        return node

    def visit_FunctionDef(self, node: ast.FunctionDef) -> ast.FunctionDef:
        saved_map = self._var_map.copy()
        saved_counter = self._counter
        node.body = self._strip_docstring(node.body)
        for arg in node.args.args + node.args.posonlyargs + node.args.kwonlyargs:
            arg.arg = self._canonical_name(arg.arg)
        if node.args.vararg:
            node.args.vararg.arg = self._canonical_name(node.args.vararg.arg)
        if node.args.kwarg:
            node.args.kwarg.arg = self._canonical_name(node.args.kwarg.arg)
        for stmt in node.body:
            self.visit(stmt)
        self._var_map = saved_map
        self._counter = saved_counter
        return node

    def visit_Name(self, node: ast.Name) -> ast.Name:
        if isinstance(node.ctx, (ast.Store, ast.Load, ast.Del)):
            if node.id in self._var_map or isinstance(node.ctx, ast.Store):
                node.id = self._canonical_name(node.id)
        return node

    def visit_ListComp(self, node: ast.ListComp) -> ast.ListComp:
        for gen in node.generators:
            self.visit(gen)
        node.elt = self.visit(node.elt)
        return node

    def visit_GeneratorExp(self, node: ast.GeneratorExp) -> ast.GeneratorExp:
        for gen in node.generators:
            self.visit(gen)
        node.elt = self.visit(node.elt)
        return node

    def visit_SetComp(self, node: ast.SetComp) -> ast.SetComp:
        for gen in node.generators:
            self.visit(gen)
        node.elt = self.visit(node.elt)
        return node

    def visit_DictComp(self, node: ast.DictComp) -> ast.DictComp:
        for gen in node.generators:
            self.visit(gen)
        node.key = self.visit(node.key)
        node.value = self.visit(node.value)
        return node


def compute_canonical_ast_hash(files: Dict[str, str]) -> str:
    """Computes a canonical SHA-256 fingerprint across a dictionary of Python file contents."""
    hasher = hashlib.sha256()
    for path in sorted(files.keys()):
        source = files[path]
        hasher.update(path.encode("utf-8"))
        try:
            tree = ast.parse(source)
            normalized = _AlphaNormalizer().visit(tree)
            ast.fix_missing_locations(normalized)
            dumped = ast.dump(normalized, annotate_fields=True, include_attributes=False)
            hasher.update(dumped.encode("utf-8"))
        except SyntaxError:
            # Fallback to whitespace-normalized raw source if syntax is invalid
            compact = " ".join(source.split())
            hasher.update(compact.encode("utf-8"))
    return hasher.hexdigest()
