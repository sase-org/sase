"""Gate-shell-reclaim output-contract tests, plus the cross-chop handler
result-contract check that scans every registered builtin chop.
"""

from __future__ import annotations

import ast
import importlib
import inspect
import json
import pkgutil
import textwrap
from pathlib import Path

import pytest

from sase.gate_shell.reclaim import GateHandoffReconcileSummary, GateShellReclaimSummary
from sase.gate_shell.store import GateShellSnapshot
from sase.chops.builtin import run_builtin_chop

from tests._axe_chop_output_contract_helpers import (
    _isolate_chop_result_file,  # noqa: F401 (registers the result-file isolation fixture)
    _write_context,
)


def _stub_empty_snapshot(monkeypatch: pytest.MonkeyPatch, script: object) -> None:
    """Keep the gate-shell reclaim chop's shared-snapshot read off a real index."""
    monkeypatch.setattr(
        script,
        "load_gate_shell_snapshot",
        lambda **_kwargs: GateShellSnapshot(
            taken_at=0.0, gate_shells=(), family_members={}, record_count=0
        ),
    )


_COUNTERS_ZERO = {
    "accepted_unfinished": 0,
    "answered": 0,
    "errors": 0,
    "handoff_adopted": 0,
    "handoff_deferred": 0,
    "handoff_errors": 0,
    "handoff_incomplete": 0,
    "handoff_scanned": 0,
    "handoff_skipped": 0,
    "lost": 0,
    "scanned": 0,
    "stopped": 0,
    "timed_out": 0,
}


def test_gate_shell_reclaim_emits_noop_summary(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    script = importlib.import_module("sase.scripts.sase_chop_gate_shell_reclaim")
    result_path = tmp_path / "result.json"
    context_path = _write_context(tmp_path, result_path)
    _stub_empty_snapshot(monkeypatch, script)
    monkeypatch.setattr(
        script,
        "reclaim_pending_gate_shells",
        lambda **_kwargs: GateShellReclaimSummary(),
    )
    monkeypatch.setattr(
        script,
        "reconcile_incomplete_gate_handoffs",
        lambda **_kwargs: GateHandoffReconcileSummary(),
    )

    run_builtin_chop("gate_shell_reclaim", ["--context", str(context_path)])

    out = capsys.readouterr().out
    assert "gate_shell_reclaim:" in out
    assert "scanned=0" in out
    assert "reason=no_pending_gate_shells" in out
    assert "gate shell reclaim progress: snapshot read" in out
    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert result["schema_version"] == 1
    assert result["status"] == "no_op"
    assert result["reason"] == "no_pending_gate_shells"
    assert result["counters"] == _COUNTERS_ZERO


def test_gate_shell_reclaim_reports_budget_exhausted_when_every_gate_was_deferred(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    script = importlib.import_module("sase.scripts.sase_chop_gate_shell_reclaim")
    result_path = tmp_path / "result.json"
    context_path = _write_context(tmp_path, result_path)
    _stub_empty_snapshot(monkeypatch, script)
    monkeypatch.setattr(
        script,
        "reclaim_pending_gate_shells",
        lambda **_kwargs: GateShellReclaimSummary(),
    )
    monkeypatch.setattr(
        script,
        "reconcile_incomplete_gate_handoffs",
        lambda **_kwargs: GateHandoffReconcileSummary(deferred=4),
    )

    run_builtin_chop("gate_shell_reclaim", ["--context", str(context_path)])

    captured = capsys.readouterr()
    assert "reason=budget_exhausted" in captured.out
    assert "deferred 4 gate(s) past its time budget" in captured.out + captured.err
    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert result["status"] == "no_op"
    assert result["reason"] == "budget_exhausted"
    assert result["counters"] == {**_COUNTERS_ZERO, "handoff_deferred": 4}


def test_gate_shell_reclaim_emits_action_summary(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    script = importlib.import_module("sase.scripts.sase_chop_gate_shell_reclaim")
    result_path = tmp_path / "result.json"
    context_path = _write_context(tmp_path, result_path)
    _stub_empty_snapshot(monkeypatch, script)
    monkeypatch.setattr(
        script,
        "reclaim_pending_gate_shells",
        lambda **_kwargs: GateShellReclaimSummary(scanned=3, answered=1, lost=1),
    )
    monkeypatch.setattr(
        script,
        "reconcile_incomplete_gate_handoffs",
        lambda **_kwargs: GateHandoffReconcileSummary(),
    )

    run_builtin_chop("gate_shell_reclaim", ["--context", str(context_path)])

    out = capsys.readouterr().out
    assert "gate_shell_reclaim:" in out
    assert "scanned=3" in out
    assert "answered=1" in out
    assert "lost=1" in out
    assert "gate shell reclaim progress: reclaim phase done" in out
    assert "gate shell reclaim progress: reconcile done" in out
    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert result["status"] == "ok"
    assert result["reason"] is None
    assert result["counters"] == {
        **_COUNTERS_ZERO,
        "answered": 1,
        "lost": 1,
        "scanned": 3,
    }


def test_gate_shell_reclaim_emits_accepted_unfinished_counter_and_log(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    script = importlib.import_module("sase.scripts.sase_chop_gate_shell_reclaim")
    result_path = tmp_path / "result.json"
    context_path = _write_context(tmp_path, result_path)
    _stub_empty_snapshot(monkeypatch, script)
    monkeypatch.setattr(
        script,
        "reclaim_pending_gate_shells",
        lambda **_kwargs: GateShellReclaimSummary(scanned=2, accepted_unfinished=2),
    )
    monkeypatch.setattr(
        script,
        "reconcile_incomplete_gate_handoffs",
        lambda **_kwargs: GateHandoffReconcileSummary(),
    )

    run_builtin_chop("gate_shell_reclaim", ["--context", str(context_path)])

    out = capsys.readouterr().out
    assert "accepted_unfinished=2" in out
    assert "2 gate(s) have an accepted decision with execution still incomplete" in out
    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert result["status"] == "ok"
    assert result["reason"] is None
    assert result["counters"] == {
        **_COUNTERS_ZERO,
        "accepted_unfinished": 2,
        "scanned": 2,
    }


def test_gate_shell_reclaim_reports_check_error_on_reclaim_errors(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    script = importlib.import_module("sase.scripts.sase_chop_gate_shell_reclaim")
    result_path = tmp_path / "result.json"
    context_path = _write_context(tmp_path, result_path)
    detail = "lane--gate: RuntimeError: bundle exploded"
    _stub_empty_snapshot(monkeypatch, script)
    monkeypatch.setattr(
        script,
        "reclaim_pending_gate_shells",
        lambda **_kwargs: GateShellReclaimSummary(
            scanned=1,
            errors=1,
            error_details=(detail,),
        ),
    )
    monkeypatch.setattr(
        script,
        "reconcile_incomplete_gate_handoffs",
        lambda **_kwargs: GateHandoffReconcileSummary(),
    )

    run_builtin_chop("gate_shell_reclaim", ["--context", str(context_path)])

    captured = capsys.readouterr()
    assert "gate_shell_reclaim:" in captured.out
    assert "reason=reclaim_errors" in captured.out
    assert f"gate shell reclaim failed: {detail}" in captured.err
    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert result["status"] == "check_error"
    assert result["reason"] == "reclaim_errors"
    assert result["counters"] == {
        **_COUNTERS_ZERO,
        "errors": 1,
        "scanned": 1,
    }


def _load_all_builtin_chop_scripts() -> None:
    import sase.scripts as scripts_pkg

    for module_info in pkgutil.iter_modules(scripts_pkg.__path__):
        if module_info.name.startswith("sase_chop_"):
            importlib.import_module(f"sase.scripts.{module_info.name}")


def _handler_function_def(handler: object) -> ast.FunctionDef:
    source = textwrap.dedent(inspect.getsource(handler))  # type: ignore[arg-type]
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            return node
    raise AssertionError(f"handler source has no function definition: {handler!r}")


def _returns_chop_result_builder(func: ast.FunctionDef) -> bool:
    returns = func.returns
    if returns is None:
        return False
    if isinstance(returns, ast.Name):
        return returns.id == "ChopResultBuilder"
    if isinstance(returns, ast.Attribute):
        return returns.attr == "ChopResultBuilder"
    return isinstance(returns, ast.Constant) and returns.value == "ChopResultBuilder"


def _delegates_through_runtime_runner(func: ast.FunctionDef) -> bool:
    for node in ast.walk(func):
        if not isinstance(node, ast.Attribute):
            continue
        if node.attr not in {"hook_runner", "check_cycle_runner"}:
            continue
        if isinstance(node.value, ast.Name) and node.value.id == "runtime":
            return True
    return False


def _deletes_runtime(func: ast.FunctionDef) -> bool:
    for node in ast.walk(func):
        if not isinstance(node, ast.Delete):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id == "runtime":
                return True
    return False


def test_builtin_chop_handlers_satisfy_result_contract() -> None:
    _load_all_builtin_chop_scripts()
    from sase.chops.builtin import _BUILTIN_CHOPS

    for name, handler in sorted(_BUILTIN_CHOPS.items()):
        func = _handler_function_def(handler)
        if _deletes_runtime(func):
            raise AssertionError(
                f"builtin chop {name!r} deletes runtime; handlers must keep "
                "the runtime and either return ChopResultBuilder or delegate "
                "through runtime.hook_runner / runtime.check_cycle_runner"
            )
        if not (
            _returns_chop_result_builder(func)
            or _delegates_through_runtime_runner(func)
        ):
            raise AssertionError(
                f"builtin chop {name!r} is not annotated to return "
                "ChopResultBuilder and does not delegate through "
                "runtime.hook_runner / runtime.check_cycle_runner"
            )
