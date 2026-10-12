"""Shared AST primitives for project-display presentation audits."""

from __future__ import annotations

import ast
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]


def parse_source(path: str) -> ast.Module:
    source_path = _ROOT / path
    return ast.parse(source_path.read_text(encoding="utf-8"), filename=path)


def call_name(call: ast.Call) -> str:
    if isinstance(call.func, ast.Name):
        return call.func.id
    if isinstance(call.func, ast.Attribute):
        return call.func.attr
    return ""


def parent_map(tree: ast.AST) -> dict[ast.AST, ast.AST]:
    return {
        child: parent
        for parent in ast.walk(tree)
        for child in ast.iter_child_nodes(parent)
    }


def enclosing_function(
    node: ast.AST,
    parents: dict[ast.AST, ast.AST],
) -> str:
    current: ast.AST | None = node
    while current is not None:
        if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return current.name
        current = parents.get(current)
    return "<module>"
