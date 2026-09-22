"""Successful live-timeline row rendering in ``sase update`` (bead sase-158.4).

Split from ``test_update_command_live_timeline.py``: managed/dev streaming,
shared-terminal panel behavior, and execution-order snapshots.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from rich.console import Console

import sase.dev_update.journal as journal_mod
from sase.completion.install import CompletionRefreshReport, RefreshShellOutcome
from sase.dev_update.models import DevUpdatePlan, DevUpdateResult
from sase.dev_update.progress import is_active_progress
from sase.main.update_handler import handle_update_command
from sase.service.actions import ServiceProcActionOutcome
from sase.update_progress import NULL_PROGRESS, StepSpec, UpdateProgressSession
from sase.uv_tool.runner import UvChangeSet, parse_uv_output
from sase.version.inventory import VersionPackageRecord
from tests.main.update_command_helpers import (
    _DEV_RECEIPT,
    _UPGRADE_OUTPUT,
    _TickingClock,
    _args,
    _assert_quiet_after,
    _console,
    _dev_plan,
    _dev_result,
    _install,
    _inventory,
    _record,
    _shared_terminal,
    _text,
    _versions,
)


def _session_factory(err: Console, tmp_path: Path):  # type: ignore[no-untyped-def]
    """Build an injectable session factory writing its log under tmp_path."""

    def _factory(**kwargs: Any) -> UpdateProgressSession:
        kwargs.pop("err", None)
        return UpdateProgressSession(err, log_dir=tmp_path, clock=lambda: 0.0, **kwargs)

    return _factory


def _restart_ok(*, reason: str | None = None) -> ServiceProcActionOutcome:
    return ServiceProcActionOutcome(
        action="restart",
        name="scheduler",
        mutations=(),
        nudged=True,
        message="requested service proc scheduler restart",
    )


def _live_session_factory(err: Console, tmp_path: Path, clock: _TickingClock):  # type: ignore[no-untyped-def]
    """Build a real live-capable session on a shared terminal console."""

    def _factory(**kwargs: Any) -> UpdateProgressSession:
        kwargs.pop("err", None)
        return UpdateProgressSession(err, log_dir=tmp_path, clock=clock, **kwargs)

    return _factory


def _refresh_ok() -> CompletionRefreshReport:
    return CompletionRefreshReport(
        attempted=True,
        outcomes=(
            RefreshShellOutcome(
                shell="zsh",
                ok=True,
                detail="refreshed /tmp/_sase",
                target="/tmp/_sase",
            ),
        ),
    )


def test_managed_live_step_streams_package_rows(tmp_path: Path) -> None:
    seen: dict[str, Any] = {}

    def _run(argv: list[str], *, on_output: Any = None) -> UvChangeSet:
        seen["argv"] = argv
        seen["on_output"] = on_output
        for line in _UPGRADE_OUTPUT.splitlines():
            if on_output is not None:
                on_output("stderr", line)
        return parse_uv_output(_UPGRADE_OUTPUT)

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

    assert code == 0
    assert seen["argv"] == ["uv", "tool", "upgrade", "--color", "never", "sase"]
    assert seen["on_output"] is not None
    err_text = _text(err)
    assert "sase update · managed install" in err_text
    assert "Upgrade sase + plugins via uv" in err_text
    assert "2 upgraded · 1 current" in err_text
    assert "sase-github" in err_text
    assert "0.3.2 → 0.4.0" in err_text
    assert "skipped · not running" in err_text
    assert "Refresh shell completions" in err_text
    assert "Full log" not in err_text
    assert "Updated sase + 1 plugin" in _text(out)


def test_dev_live_timeline_dedups_summary(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    host = _record("sase", role="host", source_root="/home/u/sase")
    seen: dict[str, Any] = {}

    def _plan(
        records: tuple[VersionPackageRecord, ...] | list[VersionPackageRecord],
        *,
        host_record: VersionPackageRecord,
        receipt: Any = None,
        progress: Any = NULL_PROGRESS,
    ) -> DevUpdatePlan:
        seen["plan_progress"] = progress
        assert receipt is not None
        return _dev_plan(*records)

    def _execute(
        plan: DevUpdatePlan, *, run: Any, progress: Any = NULL_PROGRESS
    ) -> DevUpdateResult:
        seen["execute_progress"] = progress
        return _dev_result(plan)

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
        scheduler_running_fn=lambda: True,
        restart_scheduler_fn=_restart_ok,
        version_fn=_versions,
        clock=lambda: 0.0,
        progress_session_factory=_session_factory(err, tmp_path),
    )

    assert code == 0
    assert is_active_progress(seen["plan_progress"])
    assert is_active_progress(seen["execute_progress"])
    err_text = _text(err)
    assert "sase update · dev install" in err_text
    assert "Inspect install" in err_text
    assert "uv tool · 1 editable · 0 managed" in err_text
    out_text = _text(out)
    assert "SASE Dev Update" in out_text
    assert "Reinstall uv-tool editable Python packages" not in out_text
    assert "slowest:" not in out_text


def test_shared_terminal_managed_update_keeps_panel_intact(tmp_path: Path) -> None:
    clock = _TickingClock()

    def _run(argv: list[str], *, on_output: Any = None) -> UvChangeSet:
        clock.advance(2.0)
        for line in _UPGRADE_OUTPUT.splitlines():
            if on_output is not None:
                on_output("stderr", line)
        return parse_uv_output(_UPGRADE_OUTPUT)

    stream, out, err = _shared_terminal()
    code = handle_update_command(
        _args(),
        console=out,
        err_console=err,
        probe_fn=lambda: _install(tmp_path),
        run_fn=_run,
        scheduler_running_fn=lambda: True,
        restart_scheduler_fn=_restart_ok,
        version_fn=_versions,
        clock=clock,
        refresh_completions_fn=_refresh_ok,
        progress_session_factory=_live_session_factory(err, tmp_path, clock),
    )

    assert code == 0
    text = _assert_quiet_after(stream, "Updated sase")
    tail = text.split("Updated sase", 1)[1]
    assert "requested service proc scheduler restart" in tail
    assert "Refreshing installed shell completions" in tail


def test_shared_terminal_dev_update_keeps_panel_intact(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        journal_mod, "DEV_UPDATE_JOURNAL", str(tmp_path / "journal.jsonl")
    )
    host = _record("sase", role="host", source_root="/home/u/sase")
    clock = _TickingClock()

    def _plan(records: Any, **kwargs: Any) -> DevUpdatePlan:
        clock.advance(1.0)
        return _dev_plan(*records)

    def _execute(plan: DevUpdatePlan, **kwargs: Any) -> DevUpdateResult:
        clock.advance(3.0)
        return _dev_result(plan)

    stream, out, err = _shared_terminal()
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
        clock=clock,
        progress_session_factory=_live_session_factory(err, tmp_path, clock),
    )

    assert code == 0
    _assert_quiet_after(stream, "SASE Dev Update")


def test_managed_stream_pairs_rows_and_reaches_log(tmp_path: Path) -> None:
    output = """\
Resolved 5 packages in 200ms
 - sase==0.5.0
 + sase==0.6.1
 + certifi==2024.1.0
 - sase-github==0.3.2
 + sase-github==0.4.0
"""

    def _run(argv: list[str], *, on_output: Any = None) -> UvChangeSet:
        for line in output.splitlines():
            if on_output is not None:
                on_output("stderr", line)
        return parse_uv_output(output)

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
        probe_fn=lambda: _install(tmp_path),
        run_fn=_run,
        scheduler_running_fn=lambda: False,
        version_fn=_versions,
        clock=lambda: 0.0,
        progress_session_factory=_factory,
    )

    assert code == 0
    assert len(sessions) == 1
    session = sessions[0]
    managed = next(row for row in session.model.snapshot() if row.id == "managed")
    children = {child.id: child for child in managed.children}
    assert children["managed:sase"].detail == "0.5.0 → 0.6.1"
    assert children["managed:sase-github"].detail == "0.3.2 → 0.4.0"
    # Transitive uv output becomes a child row, not a top-level one.
    assert children["managed:certifi"].detail == "2024.1.0"
    assert "managed:certifi" not in {row.id for row in session.model.snapshot()}
    assert any("Resolved 5 packages" in line for line in managed.tail)
    assert session.log_path is not None
    log_text = session.log_path.read_text(encoding="utf-8")
    assert "Resolved 5 packages in 200ms" in log_text
    assert "mode: managed install" in log_text


def test_mixed_rows_render_in_execution_order(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    github_root = tmp_path / "sase-github"
    github_root.mkdir()
    mixed_receipt = f"""\
[tool]
requirements = [
    {{ name = "sase" }},
    {{ name = "sase-github", editable = "{github_root}" }},
]
"""
    host = _record("sase", role="host", source_root=None, install_type="wheel")
    github = _record("sase-github", role="plugin", source_root=str(github_root))
    core = _record(
        "sase-core-rs",
        role="core",
        source_root=None,
        display_version="0.4.0",
        distribution_version="0.4.0",
        install_type="wheel",
    )
    monkeypatch.setattr(
        journal_mod, "DEV_UPDATE_JOURNAL", str(tmp_path / "journal.jsonl")
    )

    def _plan(records: Any, **kwargs: Any) -> DevUpdatePlan:
        progress: Any = kwargs.get("progress", NULL_PROGRESS)
        progress.declare((StepSpec("check", "Check for updates"),))
        return _dev_plan(*records, status="skipped")

    def _execute(plan: DevUpdatePlan, **kwargs: Any) -> DevUpdateResult:
        progress: Any = kwargs.get("progress", NULL_PROGRESS)
        progress.declare(
            (
                StepSpec("merge", "Fast-forward checkouts"),
                StepSpec("reconcile:0", "Reconcile install"),
            )
        )
        for step_id in ("check", "merge", "reconcile:0"):
            progress.start(step_id)
            progress.finish(step_id, "done")
        return _dev_result(plan, changed=False)

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
        probe_fn=lambda: _install(tmp_path, mixed_receipt),
        run_fn=lambda argv, **_kwargs: parse_uv_output("Nothing to upgrade"),
        inventory_fn=lambda: _inventory(host, core, github),
        plan_dev_update_fn=_plan,
        execute_dev_update_fn=_execute,
        scheduler_running_fn=lambda: False,
        version_fn=_versions,
        clock=lambda: 0.0,
        progress_session_factory=_factory,
    )

    assert code == 0
    assert len(sessions) == 1
    assert [row.id for row in sessions[0].model.snapshot()] == [
        "inspect",
        "check",
        "merge",
        "reconcile:0",
        "managed",
        "restart",
        "completions",
    ]


def test_dev_rows_render_in_execution_order(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        journal_mod, "DEV_UPDATE_JOURNAL", str(tmp_path / "journal.jsonl")
    )
    host = _record("sase", role="host", source_root="/home/u/sase")

    def _execute(plan: DevUpdatePlan, **kwargs: Any) -> DevUpdateResult:
        progress: Any = kwargs.get("progress", NULL_PROGRESS)
        progress.declare(
            (
                StepSpec("check", "Check for updates"),
                StepSpec("merge", "Fast-forward checkouts"),
                StepSpec("reconcile:0", "Reconcile install"),
            )
        )
        for step_id in ("check", "merge", "reconcile:0"):
            progress.start(step_id)
            progress.finish(step_id, "done")
        return _dev_result(plan)

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

    assert code == 0
    assert [row.id for row in sessions[0].model.snapshot()] == [
        "inspect",
        "check",
        "merge",
        "reconcile:0",
        "restart",
        "completions",
    ]
