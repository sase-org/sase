"""Static invariants for durable proc submission boundaries."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).parents[1]
SRC = ROOT / "src" / "sase"
FORBIDDEN_NEW_PROC_KINDS = {"detached", "tui"}
FORBIDDEN_KIND_NAMES = {"DETACHED_PROC_KIND", "TUI_PROC_KIND"}
PROC_WRITER_CALLS = {"ProcSubmitRequest", "ProcReserve"}


def test_durable_submit_rejects_callables_before_proc_submission() -> None:
    tree = _parse(SRC / "ace" / "tui" / "durable_submit.py")
    submit = _function(tree, "submit_durable_proc_request")
    guard_lines = _call_lines(submit, "reject_callable_submission")
    submit_lines = _call_lines(submit, "submit_proc_request")

    assert guard_lines
    assert submit_lines
    assert min(guard_lines) < min(submit_lines)

    reject = _function(tree, "reject_callable_submission")
    assert len(_call_lines(reject, "callable")) >= 3


def test_production_proc_writers_do_not_emit_legacy_kinds() -> None:
    offenders: list[str] = []
    for path in sorted(SRC.rglob("*.py")):
        tree = _parse(path)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if _call_name(node.func) not in PROC_WRITER_CALLS:
                continue
            for keyword in node.keywords:
                if keyword.arg != "kind":
                    continue
                if _legacy_kind_value(keyword.value):
                    rel = path.relative_to(ROOT)
                    offenders.append(f"{rel}:{keyword.value.lineno}")

    assert offenders == []


def test_ace_durable_submit_cannot_record_ace_pid_as_proc_owner() -> None:
    tree = _parse(SRC / "ace" / "tui" / "durable_submit.py")
    source_calls = {
        _call_name(node.func) for node in ast.walk(tree) if isinstance(node, ast.Call)
    }
    assert "os.getpid" not in source_calls

    submit = _function(tree, "submit_durable_proc_request")
    for node in ast.walk(submit):
        if not isinstance(node, ast.Call):
            continue
        if _call_name(node.func) != "ProcSubmitRequest":
            continue
        assert {keyword.arg for keyword in node.keywords}.isdisjoint(
            {"pid", "supervisor_id"}
        )


def _parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _function(tree: ast.AST, name: str) -> ast.FunctionDef:
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"missing function {name}")


def _call_lines(tree: ast.AST, name: str) -> list[int]:
    return [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and _call_name(node.func) == name
    ]


def _call_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _call_name(node.value)
        return f"{parent}.{node.attr}" if parent else node.attr
    return ""


def _legacy_kind_value(node: ast.AST) -> bool:
    if isinstance(node, ast.Constant):
        return node.value in FORBIDDEN_NEW_PROC_KINDS
    if isinstance(node, ast.Name):
        return node.id in FORBIDDEN_KIND_NAMES
    return False
