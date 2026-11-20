"""Shared helpers for launchable MRU snapshot tests."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest
from textual.app import App, ComposeResult

from sase.ace.tui.actions._launchable_mru import (
    LaunchableMruMixin,
    init_launchable_mru_state,
)
from sase.ace.tui.launchable_mru import LaunchableMruSnapshot
from tests.conftest import redirect_sase_home


def seed_mru(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, entries: list[str]
) -> Path:
    from sase.legacy_xprompt_names import VCS_MACRO_MRU_FILENAME

    sase_home = redirect_sase_home(monkeypatch, tmp_path / ".sase")
    workspace = tmp_path / "ws"
    workspace.mkdir(exist_ok=True)
    mru_file = sase_home / VCS_MACRO_MRU_FILENAME
    mru_file.write_text(json.dumps({"entries": entries}))
    monkeypatch.setattr(
        "sase.macro.loader.get_known_project_workspaces",
        lambda *a, **k: {"foo": workspace, "bar": workspace},
    )
    monkeypatch.setattr(
        "sase.ace.patch.cache.find_all_patches_cached",
        lambda *a, **k: [],
    )
    return mru_file


class StubHost(LaunchableMruMixin):
    """Minimal mixin host: immediate publish, no timers."""

    def __init__(self) -> None:
        init_launchable_mru_state(self)
        self._launchable_mru_tick_timer = object()
        self.build_calls = 0

    def call_from_thread(self, callback: Any, *args: Any) -> Any:
        return callback(*args)

    def set_interval(self, *args: Any, **kwargs: Any) -> object:
        raise AssertionError("ticks are armed once in startup, not in unit tests")


async def wait_for(
    predicate: Any, *, timeout: float = 10.0, step: float = 0.01
) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while not predicate():
        assert asyncio.get_running_loop().time() < deadline, "timed out"
        await asyncio.sleep(step)


class SnapshotApp(App):
    """Bare host app serving a canned snapshot like ``AceApp`` does."""

    ENABLE_COMMAND_PALETTE = False

    def __init__(self, snapshot: LaunchableMruSnapshot) -> None:
        super().__init__()
        self._snapshot = snapshot
        self.refresh_requests: list[str] = []
        self.identity_warm_requests: list[str] = []

    def compose(self) -> ComposeResult:
        from sase.ace.tui.widgets.prompt_text_area import PromptTextArea

        yield PromptTextArea()

    def peek_launchable_mru_snapshot(self) -> LaunchableMruSnapshot:
        return self._snapshot

    def request_launchable_mru_refresh(
        self, *, reason: str, force: bool = False
    ) -> bool:
        self.refresh_requests.append(reason)
        return True

    def request_macro_project_identity_warm(self) -> bool:
        """Record one warm request without doing main-thread I/O."""
        self.identity_warm_requests.append("warm")
        return True


def ready_snapshot(rings: list[str], generation: int = 1) -> LaunchableMruSnapshot:
    return LaunchableMruSnapshot(
        state="ready",
        pairs=tuple((entry, entry) for entry in rings),
        generation=generation,
    )
