"""`sase service proc show` splits descriptions into summary plus details."""

from __future__ import annotations

import argparse
from types import SimpleNamespace

import sase.main.service_handler as service_handler


def _snapshot(description: str | None) -> SimpleNamespace:
    proc = SimpleNamespace(
        name="scheduler",
        summary="running",
        source="builtin",
        declared_by="builtin",
        enablement=SimpleNamespace(enabled=True, summary="enabled"),
        desired="running",
        state="running",
        available=True,
        description=description,
        started_at=None,
        pid=None,
        restarts=0,
        last_exit=None,
        launcher_summary=None,
        log_path=None,
        unavailable_reason=None,
    )
    return SimpleNamespace(
        procs=[proc],
        host=SimpleNamespace(state="running", summary="running", pid=None, error=None),
    )


def _run_show(monkeypatch, capsys, description: str | None) -> str:
    monkeypatch.setattr(
        service_handler, "current_service_status", lambda: _snapshot(description)
    )
    args = argparse.Namespace(name="scheduler", json=False)
    assert service_handler.handle_service_proc_show(args) == 0
    return capsys.readouterr().out


def test_multiline_description_prints_summary_and_details(monkeypatch, capsys) -> None:
    out = _run_show(monkeypatch, capsys, "Run automation\n\nDoes things.")
    assert "  description: Run automation" in out
    assert "  details:" in out
    assert "    Does things." in out


def test_single_line_description_prints_no_details(monkeypatch, capsys) -> None:
    out = _run_show(monkeypatch, capsys, "Run automation")
    assert "  description: Run automation" in out
    assert "  details:" not in out


def test_bracketed_text_prints_literally(monkeypatch, capsys) -> None:
    out = _run_show(monkeypatch, capsys, "[bold]not markup[/bold]")
    assert "  description: [bold]not markup[/bold]" in out
