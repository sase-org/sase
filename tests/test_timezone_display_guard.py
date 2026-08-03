"""Repo-wide structural guard for configured-timezone display consistency."""

from __future__ import annotations

import ast
from pathlib import Path


_SRC_ROOT = Path(__file__).resolve().parents[1] / "src" / "sase"

_ALLOWED_CLOCK_DISPLAY_SITES = frozenset(
    {
        # Host timezone fallback must inspect the process clock; it is not display.
        "core/time.py:_system_timezone",
    }
)


def test_no_system_clock_display_sites() -> None:
    """Fix new hits by routing through sase.core.time before extending the allowlist."""
    violations: list[str] = []
    for path in sorted(_SRC_ROOT.rglob("*.py")):
        source = path.read_text(encoding="utf-8")
        lines = source.splitlines()
        parents = _ast_parents(ast.parse(source, filename=str(path)))
        relpath = path.relative_to(_SRC_ROOT).as_posix()

        for node in sorted(parents, key=lambda item: getattr(item, "lineno", -1)):
            if not isinstance(node, ast.Call):
                continue
            if not _is_bare_clock_call(node):
                continue
            symbol = _enclosing_symbol(node, parents)
            if f"{relpath}:{symbol}" in _ALLOWED_CLOCK_DISPLAY_SITES:
                continue
            line = lines[node.lineno - 1].strip()
            violations.append(f"src/sase/{relpath}:{node.lineno}: {line}")

    assert not violations, "system-clock display sites:\n" + "\n".join(violations)


def _ast_parents(tree: ast.AST) -> dict[ast.AST, ast.AST]:
    parents: dict[ast.AST, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[child] = node
    return parents


def _enclosing_symbol(node: ast.AST, parents: dict[ast.AST, ast.AST]) -> str:
    current = node
    while current in parents:
        current = parents[current]
        if isinstance(current, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            return current.name
    return "<module>"


def _is_bare_clock_call(node: ast.Call) -> bool:
    func = node.func
    if not isinstance(func, ast.Attribute):
        return False
    if (
        func.attr == "now"
        and isinstance(func.value, ast.Name)
        and func.value.id == "datetime"
    ):
        return not node.args and not node.keywords
    if func.attr == "astimezone":
        return not node.args and not node.keywords
    if (
        func.attr == "fromtimestamp"
        and isinstance(func.value, ast.Name)
        and func.value.id == "datetime"
    ):
        return len(node.args) < 2 and not any(
            keyword.arg == "tz" for keyword in node.keywords
        )
    return False
