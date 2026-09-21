"""Tests for the live timeline wiring in ``sase update`` (bead sase-158.4)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from rich.console import Console

import sase.dev_update.journal as journal_mod
from sase.dev_update.models import DevUpdatePlan, DevUpdateResult
from sase.main.parser import create_parser
from sase.main.update_handler import handle_update_command
from sase.service.actions import ServiceProcActionOutcome
from sase.update_progress import NULL_PROGRESS, UpdateProgressSession
from sase.dev_update.progress import is_active_progress
from sase.uv_tool.errors import UvCommandFailedError
from sase.uv_tool.runner import UvChangeSet, parse_uv_output
from sase.version.inventory import VersionPackageRecord
from tests.main.update_command_helpers import (
    _DEV_RECEIPT,
    _UPGRADE_OUTPUT,
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

_SELF_UPDATE_MODULES = (
    "sase.update_progress.session",
    "sase.update_progress.render_live",
    "sase.update_progress.render_plain",
    "sase.main.update_render",
    "sase.main.update_restart",
    "rich.live",
    "rich.spinner",
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


def test_verbose_flag_parses_short_and_long() -> None:
    short = create_parser().parse_args(["update", "-v"])
    long = create_parser().parse_args(["update", "--verbose"])

    assert short.verbose is True
    assert long.verbose is True


def test_self_update_modules_preloaded() -> None:
    import sys

    import sase.main.update_handler  # noqa: F401 - import populates sys.modules.

    for name in _SELF_UPDATE_MODULES:
        assert name in sys.modules, f"{name} must be preloaded before the code swap"


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


def test_live_json_includes_log_path(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    factory_runs: list[dict[str, Any]] = []

    def _factory(**kwargs: Any) -> UpdateProgressSession:
        factory_runs.append(dict(kwargs))
        kwargs.pop("err", None)
        return UpdateProgressSession(
            Console(stderr=True), log_dir=tmp_path, clock=lambda: 0.0, **kwargs
        )

    code = handle_update_command(
        _args(json=True),
        probe_fn=lambda: _install(tmp_path),
        run_fn=lambda _argv: parse_uv_output(_UPGRADE_OUTPUT),
        scheduler_running_fn=lambda: False,
        version_fn=_versions,
        clock=lambda: 0.0,
        progress_session_factory=_factory,
    )

    assert code == 0
    assert factory_runs and factory_runs[0]["verbose"] is False
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["schema_version"] == 4
    assert payload["log_path"] is not None
    assert Path(payload["log_path"]).is_file()
    assert "Upgrade sase" not in captured.out
    assert "Upgrade sase" not in captured.err


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


def test_verbose_with_quiet_stays_one_line(tmp_path: Path) -> None:
    out = _console()
    err = _console()
    code = handle_update_command(
        _args(quiet=True, verbose=True),
        console=out,
        err_console=err,
        probe_fn=lambda: _install(tmp_path),
        run_fn=lambda _argv: parse_uv_output(_UPGRADE_OUTPUT),
        scheduler_running_fn=lambda: False,
        version_fn=_versions,
        clock=lambda: 0.0,
        progress_session_factory=_session_factory(err, tmp_path),
    )

    assert code == 0
    assert len(_text(out).strip().splitlines()) == 1
    assert _text(err) == ""
