"""Pilot tests for the TTY-blocked terminal valve escape hatch."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.modals.init_plan_modal import InitPlanModal
from tests.ace.tui._projects_pane_init_flow_helpers import (
    _SuspendRecorder,
    _completion,
    _install_submit,
    _open_projects,
    _patch_panes,
    _tty_blocked_payload,
)


def _patch_init_subprocess_run(monkeypatch: pytest.MonkeyPatch, handler: Any) -> None:
    """Patch init-actions ``subprocess.run`` without intercepting git probes.

    That module uses ``import subprocess``, so setattr on ``.subprocess.run``
    replaces the process-global function. Identity lookups then leak into
    tests that only meant to watch the terminal ``sase init`` argv.
    """
    original = subprocess.run

    def wrapped(*args: Any, **kwargs: Any) -> Any:
        argv = list(args[0] if args else kwargs.get("args") or [])
        if argv[:1] == ["git"]:
            return original(*args, **kwargs)
        return handler(*args, **kwargs)

    monkeypatch.setattr(
        "sase.ace.tui.modals.projects_pane_init_actions.subprocess.run",
        wrapped,
    )


async def test_terminal_valve_suspends_runs_scoped_argv_and_reloads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_panes(monkeypatch)
    async with AcePage() as page:
        submitted = _install_submit(page)
        suspend = _SuspendRecorder()
        monkeypatch.setattr(page.app, "suspend", lambda: suspend)
        run_calls: list[tuple[list[str], dict[str, Any]]] = []

        def fake_run(
            argv: list[str], **kwargs: Any
        ) -> subprocess.CompletedProcess[str]:
            assert suspend.active is True
            run_calls.append((list(argv), kwargs))
            return subprocess.CompletedProcess(list(argv), 0, "", "")

        _patch_init_subprocess_run(monkeypatch, fake_run)
        _center, pane = await _open_projects(page)

        await page.press("i")
        await page.pause()
        args, kwargs, handle = submitted[0]
        payload = _tty_blocked_payload("alpha")
        kwargs["on_complete"](_completion(handle.proc_id, payload))
        await page.expect_modal("InitPlanModal")
        modal = page.app.screen
        assert isinstance(modal, InitPlanModal)
        await page.wait_for(lambda _s: len(modal.query("#init-plan-terminal")) > 0)

        await page.press("t")
        await page.pause()

        assert run_calls == [
            (["sase", "init", "-p", "alpha"], {"cwd": Path.home(), "check": False})
        ]
        assert suspend.enters == 1
        assert suspend.exits == 1
        assert page.app.screen is not modal
        assert len(submitted) == 1
        assert "Returned from terminal init for alpha" in pane._status_message


async def test_terminal_valve_unsupported_suspend_notifies_instead_of_crashing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from textual.app import SuspendNotSupported

    _patch_panes(monkeypatch)
    async with AcePage() as page:
        submitted = _install_submit(page)
        notices: list[tuple[str, str]] = []
        original_notify = page.app.notify

        def capture(message: str, **kwargs: Any) -> None:
            notices.append((message, str(kwargs.get("severity", "information"))))
            original_notify(message, **kwargs)

        page.app.notify = capture  # type: ignore[method-assign]

        def fail_suspend() -> Any:
            raise SuspendNotSupported()

        monkeypatch.setattr(page.app, "suspend", fail_suspend)
        run_calls: list[Any] = []

        def record_run(*a: Any, **kw: Any) -> Any:
            run_calls.append((a, kw))
            argv = list(a[0] if a else kw.get("args") or [])
            return subprocess.CompletedProcess(argv, 1, "", "blocked")

        _patch_init_subprocess_run(monkeypatch, record_run)
        _center, pane = await _open_projects(page)

        await page.press("i")
        await page.pause()
        args, kwargs, handle = submitted[0]
        payload = _tty_blocked_payload("alpha")
        kwargs["on_complete"](_completion(handle.proc_id, payload))
        await page.expect_modal("InitPlanModal")
        modal = page.app.screen
        await page.wait_for(lambda _s: len(modal.query("#init-plan-terminal")) > 0)

        await page.press("t")
        await page.pause()

        assert run_calls == []
        assert any(severity == "error" for _message, severity in notices)
        assert "Could not run" in pane._status_message
