"""Session wiring tests for mode-switch and dry-run (bead sase-158.5)."""

from __future__ import annotations

import io
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest
from rich.console import Console

from sase.completion.install import CompletionRefreshReport, RefreshShellOutcome
from sase.dev_update.models import OutputSink
import sase.main.update_handler_mode_switch as mode_switch_handler
from sase.main.update_handler import handle_update_command
from sase.dev_update.progress import is_active_progress
from sase.mode_switch.models import (
    ModeSwitchCommand,
    ModeSwitchOutcome,
    ModeSwitchResult,
    SwitchPackagePlan,
    SwitchPlan,
)
from sase.update_progress import StepSpec, StepStatus
from sase.uv_tool.errors import UvToolError
from sase.uv_tool.runner import UvChangeSet
from tests.main.update_command_helpers import (
    _DEV_RECEIPT,
    _args,
    _console,
    _dev_plan,
    _install,
    _inventory,
    _record,
    _text,
)


class RecordingProgress:
    """In-memory progress sink recording every event in order."""

    def __init__(self) -> None:
        self.events: list[tuple] = []

    def declare(self, specs: Sequence[StepSpec]) -> None:
        self.events.append(
            ("declare", tuple((spec.id, spec.title, spec.parent_id) for spec in specs))
        )

    def start(
        self, id: str, *, title: str | None = None, detail: str | None = None
    ) -> None:
        self.events.append(("start", id, title, detail))

    def output(self, id: str, stream: str, line: str) -> None:
        self.events.append(("output", id, stream, line))

    def finish(self, id: str, status: StepStatus, *, detail: str | None = None) -> None:
        self.events.append(("finish", id, status, detail))

    def command(self, id: str, argv: Sequence[str], cwd: str | None = None) -> None:
        self.events.append(("command", id, tuple(argv), cwd))

    def finalize(self, status_for_pending: StepStatus = "skipped") -> None:
        self.events.append(("finalize", status_for_pending))

    def output_sink(self, id: str) -> OutputSink:
        def sink(stream: str, line: str) -> None:
            self.output(id, stream, line)

        return sink


class FakeSession:
    """Stand-in for UpdateProgressSession recording session-level calls."""

    def __init__(
        self, progress: RecordingProgress, log_path: Path | None = None
    ) -> None:
        self.progress = progress
        self._log_path = log_path
        self.headers: list[str] = []
        self.final_printed = 0
        self.entered = False

    def set_header(self, mode: str) -> None:
        self.headers.append(mode)

    @property
    def log_path(self) -> Path | None:
        return self._log_path

    @property
    def shown(self) -> bool:
        return True

    def print_final(self, *, expand_failures: bool = True) -> None:
        self.final_printed += 1

    def __enter__(self) -> FakeSession:
        self.entered = True
        return self

    def __exit__(self, *exc: object) -> None:
        return None


def _managed_inventory() -> object:
    return _inventory(
        _record("sase", role="host", source_root="", display_version="0.8.0"),
        _record("sase-core-rs", role="core", source_root="", display_version="0.3.1"),
        _record("sase-github", role="plugin", source_root="", display_version="0.1.0"),
        _record(
            "sase-telegram", role="plugin", source_root="", display_version="0.2.0"
        ),
    )


def _switch_plan(tmp_path: Path) -> SwitchPlan:
    return SwitchPlan(
        current_mode="managed",
        target_mode="dev",
        dev_root=str(tmp_path / "dev"),
        packages=(
            SwitchPackagePlan(
                name="sase",
                role="host",
                current_version="0.8.0",
                target_version="0.9.0",
                source="editable checkout",
                repo_action="reuse",
            ),
        ),
        commands=(
            ModeSwitchCommand(
                kind="uv_tool_install",
                label="Install editable package set",
                command=("uv", "tool", "install", "--editable", "/src/sase"),
            ),
        ),
    )


def _switch_result(plan: SwitchPlan) -> ModeSwitchResult:
    return ModeSwitchResult(
        plan=plan,
        changed=True,
        outcomes=(
            ModeSwitchOutcome(
                name="sase",
                role="host",
                status="switched",
                old_version="0.8.0",
                new_version="0.9.0",
                source="editable checkout",
            ),
        ),
        commands=plan.commands,
    )


def _patch_switch(
    monkeypatch: pytest.MonkeyPatch, plan: SwitchPlan, **overrides: Any
) -> dict[str, Any]:
    """Stub plan/execute in the handler module; record execute kwargs."""
    seen: dict[str, Any] = {}
    monkeypatch.setattr(mode_switch_handler, "plan_mode_switch", lambda *_a, **_k: plan)

    def _execute(_plan: SwitchPlan, **kwargs: Any) -> ModeSwitchResult:
        seen.update(kwargs)
        seen["plan"] = _plan
        behavior = overrides.get("execute", "ok")
        if behavior == "fail":
            raise UvToolError("boom\nRestore command: sase update --to managed")
        if behavior == "interrupt":
            raise KeyboardInterrupt
        return _switch_result(plan)

    monkeypatch.setattr(mode_switch_handler, "execute_mode_switch", _execute)
    return seen


def test_mode_switch_runs_in_session_after_confirmation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan = _switch_plan(tmp_path)
    # Real backend with a fake uv runner, so the session sees genuine events.
    monkeypatch.setattr(mode_switch_handler, "plan_mode_switch", lambda *_a, **_k: plan)
    ran: dict[str, Any] = {}

    def _run_uv(argv: list[str], **kwargs: Any) -> UvChangeSet:
        ran["argv"] = argv
        ran["on_output"] = kwargs.get("on_output")
        return UvChangeSet(changes=(), raw_output="")

    order: list[str] = []

    def _confirm(_plan: SwitchPlan, **_kwargs: Any) -> bool:
        order.append("confirm")
        return True

    progress = RecordingProgress()
    session = FakeSession(progress)

    def _factory(**_kwargs: Any) -> FakeSession:
        order.append("factory")
        return session

    monkeypatch.setattr(mode_switch_handler, "_confirm_mode_switch", _confirm)
    out = _console()
    code = handle_update_command(
        _args(to="dev"),
        console=out,
        probe_fn=lambda: _install(tmp_path),
        inventory_fn=_managed_inventory,
        run_fn=_run_uv,
        scheduler_running_fn=lambda: False,
        config_fn=lambda: {"update": {"dev_root": str(tmp_path / "dev")}},
        progress_session_factory=_factory,  # type: ignore[arg-type]
    )

    assert code == 0
    # The confirmation prompt and plan preview stay before any live region.
    assert order == ["confirm", "factory"]
    assert session.entered
    assert session.headers == ["switch to dev"]
    assert ran["argv"] == ["uv", "tool", "install", "--editable", "/src/sase"]
    assert ran["on_output"] is not None
    kinds = [
        (event[0], event[1] if len(event) > 1 else None) for event in progress.events
    ]
    assert any(
        event[0] == "declare"
        and ("switch:0", "Install editable package set", None) in event[1]
        for event in progress.events
    )
    assert ("start", "switch:0") in kinds
    assert ("finish", "switch:0") in kinds
    assert ("finish", "restart") in kinds
    assert ("finish", "completions") in kinds
    assert session.final_printed == 1
    assert "Switched to Dev (editable)" in _text(out)


def test_mode_switch_cancel_never_opens_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan = _switch_plan(tmp_path)
    _patch_switch(monkeypatch, plan)
    monkeypatch.setattr(
        mode_switch_handler, "_confirm_mode_switch", lambda *_a, **_k: False
    )
    factories: list[Any] = []

    def _factory(**kwargs: Any) -> Any:
        factories.append(kwargs)
        raise AssertionError("no session may open before confirmation")

    out = _console()
    err = _console()
    code = handle_update_command(
        _args(to="dev"),
        console=out,
        err_console=err,
        probe_fn=lambda: _install(tmp_path),
        inventory_fn=_managed_inventory,
        scheduler_running_fn=lambda: False,
        config_fn=lambda: {"update": {"dev_root": str(tmp_path / "dev")}},
        progress_session_factory=_factory,  # type: ignore[arg-type]
    )

    assert code == 1
    assert factories == []
    assert "cancelled" in _text(err)


def test_mode_switch_json_carries_log_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    plan = _switch_plan(tmp_path)
    _patch_switch(monkeypatch, plan)
    log_path = tmp_path / "update-20260921T000000Z-123.log"
    log_path.write_text("sase update log\n", encoding="utf-8")
    session = FakeSession(RecordingProgress(), log_path=log_path)

    code = handle_update_command(
        _args(json=True, to="dev", yes=True),
        probe_fn=lambda: _install(tmp_path),
        inventory_fn=_managed_inventory,
        scheduler_running_fn=lambda: False,
        config_fn=lambda: {"update": {"dev_root": str(tmp_path / "dev")}},
        progress_session_factory=lambda **_kwargs: session,  # type: ignore[return-value]
    )

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["dry_run"] is False
    assert payload["log_path"] == str(log_path)
    assert session.final_printed == 1


def test_mode_switch_failure_keeps_restore_hint_and_full_log(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan = _switch_plan(tmp_path)
    _patch_switch(monkeypatch, plan, execute="fail")
    log_path = tmp_path / "update-fail.log"
    log_path.write_text("sase update log\n", encoding="utf-8")
    session = FakeSession(RecordingProgress(), log_path=log_path)
    out = _console()
    err = _console()

    code = handle_update_command(
        _args(to="dev", yes=True),
        console=out,
        err_console=err,
        probe_fn=lambda: _install(tmp_path),
        inventory_fn=_managed_inventory,
        scheduler_running_fn=lambda: False,
        config_fn=lambda: {"update": {"dev_root": str(tmp_path / "dev")}},
        progress_session_factory=lambda **_kwargs: session,  # type: ignore[return-value]
    )

    assert code == 1
    assert session.final_printed == 1
    err_text = _text(err)
    assert "boom" in err_text
    assert "Restore command" in err_text
    assert f"Full log: {log_path}" in err_text


def test_mode_switch_interrupt_returns_130(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan = _switch_plan(tmp_path)
    _patch_switch(monkeypatch, plan, execute="interrupt")
    progress = RecordingProgress()
    session = FakeSession(progress)
    err = _console()

    code = handle_update_command(
        _args(to="dev", yes=True),
        console=_console(),
        err_console=err,
        probe_fn=lambda: _install(tmp_path),
        inventory_fn=_managed_inventory,
        scheduler_running_fn=lambda: False,
        config_fn=lambda: {"update": {"dev_root": str(tmp_path / "dev")}},
        progress_session_factory=lambda **_kwargs: session,  # type: ignore[return-value]
    )

    assert code == 130
    assert ("finalize", "interrupted") in progress.events
    assert session.final_printed == 1
    assert "Interrupted" in _text(err)


def test_mode_switch_handler_preloads_session_modules() -> None:
    import sys

    import sase.main.update_handler_mode_switch  # noqa: F401 - populates sys.modules.

    for name in (
        "sase.update_progress.session",
        "sase.update_progress.render_live",
        "sase.update_progress.render_plain",
    ):
        assert name in sys.modules, f"{name} must be preloaded before the code swap"


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


def test_mode_switch_completions_row_uses_refresh_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan = _switch_plan(tmp_path)
    _patch_switch(monkeypatch, plan)
    progress = RecordingProgress()
    session = FakeSession(progress)
    out = _console()

    code = handle_update_command(
        _args(to="dev", yes=True),
        console=out,
        probe_fn=lambda: _install(tmp_path),
        inventory_fn=_managed_inventory,
        scheduler_running_fn=lambda: False,
        config_fn=lambda: {"update": {"dev_root": str(tmp_path / "dev")}},
        refresh_completions_fn=_refresh_ok,
        progress_session_factory=lambda **_kwargs: session,  # type: ignore[return-value]
    )

    assert code == 0
    finishes = {
        event[1]: (event[2], event[3])
        for event in progress.events
        if event[0] == "finish"
    }
    assert finishes["completions"][0] == "done"
    assert "refreshed /tmp/_sase" in finishes["completions"][1]
    assert "Refreshing installed shell completions" in _text(out)


def test_dry_run_without_terminal_plans_quietly(tmp_path: Path) -> None:
    host = _record("sase", role="host", source_root="/home/u/sase")
    seen: dict[str, Any] = {}

    def _plan_fn(records: Any, **kwargs: Any) -> Any:
        seen["progress"] = kwargs.get("progress")
        return _dev_plan(host)

    out = _console()
    err = _console()
    code = handle_update_command(
        _args(dry_run=True),
        console=out,
        err_console=err,
        probe_fn=lambda: _install(tmp_path, _DEV_RECEIPT),
        inventory_fn=lambda: _inventory(host),
        plan_dev_update_fn=_plan_fn,
    )

    assert code == 0
    # The null sink is never forwarded, so the fake sees no progress kwarg.
    assert seen.get("progress") is None
    assert "SASE Update (dry run)" in _text(out)
    # Plain mode prints nothing extra: the dry-run panel is the only output.
    assert _text(err) == ""


def test_dry_run_live_terminal_plans_with_transient_timeline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TERM", "xterm-256color")
    host = _record("sase", role="host", source_root="/home/u/sase")
    seen: dict[str, Any] = {}

    def _plan_fn(records: Any, **kwargs: Any) -> Any:
        seen["progress"] = kwargs.get("progress")
        return _dev_plan(host)

    out = _console()
    err = Console(file=io.StringIO(), width=80, force_terminal=True)
    code = handle_update_command(
        _args(dry_run=True),
        console=out,
        err_console=err,
        probe_fn=lambda: _install(tmp_path, _DEV_RECEIPT),
        inventory_fn=lambda: _inventory(host),
        plan_dev_update_fn=_plan_fn,
    )

    assert code == 0
    assert is_active_progress(seen.get("progress"))
    # The dry-run panel remains the persistent output after teardown.
    assert "SASE Update (dry run)" in _text(out)


def test_dry_run_opens_no_log_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import sase.update_progress.session as session_mod

    monkeypatch.setenv("TERM", "xterm-256color")
    host = _record("sase", role="host", source_root="/home/u/sase")

    def _no_log(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("dry runs must not open a log file")

    monkeypatch.setattr(session_mod, "UpdateLogSink", _no_log)
    out = _console()
    err = Console(file=io.StringIO(), width=80, force_terminal=True)
    code = handle_update_command(
        _args(dry_run=True),
        console=out,
        err_console=err,
        probe_fn=lambda: _install(tmp_path, _DEV_RECEIPT),
        inventory_fn=lambda: _inventory(host),
        plan_dev_update_fn=lambda records, **_kwargs: _dev_plan(host),
    )

    assert code == 0
    assert "SASE Update (dry run)" in _text(out)


def test_dry_run_json_has_no_timeline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("TERM", "xterm-256color")
    host = _record("sase", role="host", source_root="/home/u/sase")
    seen: dict[str, Any] = {}

    def _plan_fn(records: Any, **kwargs: Any) -> Any:
        seen["progress"] = kwargs.get("progress")
        return _dev_plan(host)

    code = handle_update_command(
        _args(json=True, dry_run=True),
        err_console=Console(file=io.StringIO(), width=80, force_terminal=True),
        probe_fn=lambda: _install(tmp_path, _DEV_RECEIPT),
        inventory_fn=lambda: _inventory(host),
        plan_dev_update_fn=_plan_fn,
    )

    assert code == 0
    assert seen.get("progress") is None
    payload = json.loads(capsys.readouterr().out)
    assert payload["dry_run"] is True
