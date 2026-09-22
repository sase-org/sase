"""Failure and interrupt paths for the live timeline (bead sase-158.4).

Split from ``test_update_command_live_timeline.py``: uv failures, keyboard
interrupts, and the resulting timeline frames and journal records.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from rich.console import Console

import sase.dev_update.journal as journal_mod
import sase.main.update_handler_live as live_handler
from sase.dev_update.models import DevUpdatePlan, DevUpdateResult
from sase.main.update_handler import handle_update_command
from sase.update_progress import StepSpec, UpdateProgressSession
from sase.uv_tool.errors import UvCommandFailedError
from sase.uv_tool.runner import UvChangeSet, parse_uv_output
from sase.version.inventory import VersionPackageRecord
from tests.main.update_command_helpers import (
    _DEV_RECEIPT,
    _args,
    _console,
    _dev_plan,
    _dev_result,
    _install,
    _inventory,
    _record,
    _text,
    _versions,
)


def _session_factory(err: Console, tmp_path: Path):  # type: ignore[no-untyped-def]
    """Build an injectable session factory writing its log under tmp_path."""

    def _factory(**kwargs: Any) -> UpdateProgressSession:
        kwargs.pop("err", None)
        return UpdateProgressSession(err, log_dir=tmp_path, clock=lambda: 0.0, **kwargs)

    return _factory


def test_live_failure_prints_full_log(tmp_path: Path) -> None:
    def _run(argv: list[str]) -> UvChangeSet:
        raise UvCommandFailedError(argv=argv, returncode=2, stderr="No solution found")

    out = _console()
    err = _console()
    code = handle_update_command(
        _args(),
        console=out,
        err_console=err,
        probe_fn=lambda: _install(tmp_path),
        run_fn=_run,
        scheduler_running_fn=lambda: False,
        version_fn=_versions,
        clock=lambda: 0.0,
        progress_session_factory=_session_factory(err, tmp_path),
    )

    assert code == 1
    err_text = _text(err)
    assert "No solution found" in err_text
    assert "✗ Upgrade sase + plugins via uv" in err_text
    assert "Full log: " in err_text
    assert ".log" in err_text


def test_live_interrupt_returns_130(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    host = _record("sase", role="host", source_root="/home/u/sase")

    def _plan(
        records: tuple[VersionPackageRecord, ...] | list[VersionPackageRecord],
        **kwargs: Any,
    ) -> DevUpdatePlan:
        return _dev_plan(*records)

    def _execute(plan: DevUpdatePlan, **kwargs: Any) -> DevUpdateResult:
        raise KeyboardInterrupt

    journal_path = tmp_path / "dev_update.jsonl"
    monkeypatch.setattr(journal_mod, "DEV_UPDATE_JOURNAL", str(journal_path))
    out = _console()
    err = _console()
    code = handle_update_command(
        _args(),
        console=out,
        err_console=err,
        probe_fn=lambda: _install(tmp_path, _DEV_RECEIPT),
        run_fn=lambda argv, **_kwargs: parse_uv_output("Nothing to upgrade"),
        inventory_fn=lambda: _inventory(host),
        plan_dev_update_fn=_plan,
        execute_dev_update_fn=_execute,
        scheduler_running_fn=lambda: False,
        version_fn=_versions,
        clock=lambda: 0.0,
        progress_session_factory=_session_factory(err, tmp_path),
    )

    assert code == 130
    err_text = _text(err)
    assert "Interrupted" in err_text
    assert "Traceback" not in err_text
    record = json.loads(journal_path.read_text(encoding="utf-8").splitlines()[-1])
    assert record["restart"]["reason"] == "interrupted"


def test_failure_frame_skips_pending_and_expands_tail(tmp_path: Path) -> None:
    def _run(argv: list[str], *, on_output: Any = None) -> UvChangeSet:
        if on_output is not None:
            on_output("stderr", "error: No solution found for thyme==9.9.9")
        raise UvCommandFailedError(argv=argv, returncode=2, stderr="No solution found")

    out = _console()
    err = _console()
    code = handle_update_command(
        _args(),
        console=out,
        err_console=err,
        probe_fn=lambda: _install(tmp_path),
        run_fn=_run,
        scheduler_running_fn=lambda: False,
        version_fn=_versions,
        clock=lambda: 0.0,
        progress_session_factory=_session_factory(err, tmp_path),
    )

    assert code == 1
    err_text = _text(err)
    assert "No solution found" in err_text
    assert "No solution found for thyme==9.9.9" in err_text
    assert "– Restart scheduler" in err_text
    assert "– Refresh shell completions" in err_text
    assert "Full log: " in err_text
    # Plain mode prints nothing after the final frame's log line.
    assert err_text.split("Full log: ", 1)[1].splitlines()[-1].endswith(".log")


def test_interrupt_marks_only_running_step(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        journal_mod, "DEV_UPDATE_JOURNAL", str(tmp_path / "journal.jsonl")
    )
    host = _record("sase", role="host", source_root="/home/u/sase")

    def _execute(plan: DevUpdatePlan, **kwargs: Any) -> DevUpdateResult:
        progress: Any = kwargs.get("progress")
        progress.declare((StepSpec("check", "Check for updates"),))
        progress.start("check", title="Check for updates")
        raise KeyboardInterrupt

    sessions: list[UpdateProgressSession] = []
    out = _console()
    err = _console()

    def _factory(**kwargs: Any) -> UpdateProgressSession:
        kwargs.pop("err", None)
        session = UpdateProgressSession(err, log_dir=tmp_path, **kwargs)
        sessions.append(session)
        return session

    code = handle_update_command(
        _args(),
        console=out,
        err_console=err,
        probe_fn=lambda: _install(tmp_path, _DEV_RECEIPT),
        run_fn=lambda argv, **_kwargs: parse_uv_output("Nothing to upgrade"),
        inventory_fn=lambda: _inventory(host),
        plan_dev_update_fn=lambda records, **_kwargs: _dev_plan(*records),
        execute_dev_update_fn=_execute,
        scheduler_running_fn=lambda: False,
        version_fn=_versions,
        clock=lambda: 0.0,
        progress_session_factory=_factory,
    )

    assert code == 130
    assert {row.id: row.status for row in sessions[0].model.snapshot()} == {
        "inspect": "done",
        "check": "interrupted",
        "restart": "skipped",
        "completions": "skipped",
    }


def test_late_interrupt_prints_single_frame_and_journal(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    journal_path = tmp_path / "journal.jsonl"
    monkeypatch.setattr(journal_mod, "DEV_UPDATE_JOURNAL", str(journal_path))
    host = _record("sase", role="host", source_root="/home/u/sase")

    def _boom(*_args: Any, **_kwargs: Any) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(live_handler, "render_completion_refresh", _boom)
    out = _console()
    err = _console()
    code = handle_update_command(
        _args(),
        console=out,
        err_console=err,
        probe_fn=lambda: _install(tmp_path, _DEV_RECEIPT),
        run_fn=lambda argv, **_kwargs: parse_uv_output("Nothing to upgrade"),
        inventory_fn=lambda: _inventory(host),
        plan_dev_update_fn=lambda records, **_kwargs: _dev_plan(*records),
        execute_dev_update_fn=lambda plan, **_kwargs: _dev_result(plan),
        scheduler_running_fn=lambda: False,
        version_fn=_versions,
        clock=lambda: 0.0,
        progress_session_factory=_session_factory(err, tmp_path),
    )

    assert code == 130
    err_text = _text(err)
    assert err_text.count("sase update · dev install") == 1
    assert err_text.count("Interrupted") == 1
    assert len(journal_path.read_text(encoding="utf-8").splitlines()) == 1
