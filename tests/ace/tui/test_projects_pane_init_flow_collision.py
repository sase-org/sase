"""Pilot tests for the duplicate-submission collision guard on init actions."""

from __future__ import annotations

import threading
from typing import Any

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.actions.proc_actions import TrackedProcResult
from tests.ace.tui._projects_pane_init_flow_helpers import _open_projects, _patch_panes


async def test_second_activation_uses_real_collision_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_panes(monkeypatch)
    gate = threading.Event()

    def hang(reporter: object) -> TrackedProcResult[None]:
        del reporter
        gate.wait(timeout=30)
        return TrackedProcResult(success=True, message="done")

    async with AcePage() as page:
        notices: list[str] = []
        original_notify = page.app.notify

        def capture(message: str, **kwargs: Any) -> None:
            notices.append(message)
            original_notify(message, **kwargs)

        page.app.notify = capture  # type: ignore[method-assign]
        _center, pane = await _open_projects(page)
        first = page.app._submit_session_worker(
            "init-check",
            hang,
            exclusive_scopes=("sase-init",),
            duplicate_message="A project initialization is already running.",
        )
        assert first is not None
        await page.pause()
        pane.action_initialize_project()
        await page.wait_for(
            lambda _s: any("already running" in item for item in notices)
        )
        assert pane._status_message == "A project initialization is already running."
        gate.set()
