"""Tests for ACE-side proc reconciliation guards."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sase.ace.tui import proc_reconciler as pr


def test_reconciler_refuses_unsandboxed_pytest_store(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    calls: list[int] = []
    monkeypatch.setenv("SASE_PYTEST_SANDBOX_DIR", str(tmp_path / "sandbox"))
    monkeypatch.setattr(
        pr, "proc_store_path", lambda: tmp_path / "real" / "procs.jsonl"
    )
    monkeypatch.setattr(pr, "reconcile_running_procs", lambda: calls.append(1))

    assert pr.reconcile_running_procs_safely() == []
    assert calls == []


def test_reconciler_swallows_store_errors(monkeypatch: Any, tmp_path: Path) -> None:
    monkeypatch.setenv("SASE_PYTEST_SANDBOX_DIR", str(tmp_path))
    monkeypatch.setattr(pr, "proc_store_path", lambda: tmp_path / "procs.jsonl")

    def _boom() -> list[object]:
        raise RuntimeError("boom")

    monkeypatch.setattr(pr, "reconcile_running_procs", _boom)

    assert pr.reconcile_running_procs_safely() == []
