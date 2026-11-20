"""Tests for macro project identity warming during prompt assistance."""

from __future__ import annotations

from typing import Any

import pytest
from textual.app import App, ComposeResult

from sase.ace.tui.launchable_mru import LaunchableMruSnapshot
from tests.ace.tui._launchable_mru_test_helpers import (
    SnapshotApp,
    StubHost,
    ready_snapshot,
    wait_for,
)


def _seed_identity_alias(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[dict[str, str], Any]:
    """Seed a ``docs -> widgets`` identity behind the loader entry points."""
    from sase.macro import project_identity as identity
    from sase.project_display_names import ProjectDisplaySnapshot

    alias_map = {"docs": "gh_acme__widgets"}
    snapshot = ProjectDisplaySnapshot({"gh_acme__widgets": "widgets", "plain": "plain"})
    monkeypatch.setattr(identity, "load_project_alias_map", lambda: dict(alias_map))
    monkeypatch.setattr(identity, "load_project_display_snapshot", lambda: snapshot)
    return alias_map, snapshot


async def test_cold_identity_press_coalesces_warm_while_in_flight(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Repeated cold presses start exactly one identity warm."""
    import threading

    import sase.macro.project_identity as identity

    identity.invalidate_macro_project_identity()
    try:
        release = threading.Event()
        calls = 0
        real_warm = identity.warm_macro_project_identity

        def _blocking_warm() -> None:
            nonlocal calls
            calls += 1
            assert release.wait(timeout=10.0)
            real_warm()

        monkeypatch.setattr(identity, "warm_macro_project_identity", _blocking_warm)
        host = StubHost()
        assert host.request_macro_project_identity_warm() is True
        await wait_for(lambda: calls >= 1)
        assert host._macro_identity_warm_in_flight
        for _ in range(5):
            assert host.request_macro_project_identity_warm() is True
        release.set()
        await wait_for(lambda: calls == 1 and not host._macro_identity_warm_in_flight)
        assert calls == 1
    finally:
        try:
            release.set()
        except Exception:  # noqa: BLE001 - release is best-effort.
            pass
        identity.invalidate_macro_project_identity()
        from sase.ace.tui.util.pump_tasks import cancel_pump_free_tasks

        try:
            cancel_pump_free_tasks(host)
        except Exception:  # noqa: BLE001 - teardown is best-effort.
            pass


async def test_warm_identity_resolves_aliased_project(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """After the warm, an aliased ``#gh:`` ref resolves canonically."""
    from sase.ace.tui.widgets.prompt_text_area import PromptTextArea
    from sase.macro import project_identity as identity

    _seed_identity_alias(monkeypatch)
    identity.invalidate_macro_project_identity()
    try:
        assert not identity.macro_project_identity_ready()
        identity.warm_macro_project_identity()
        assert identity.macro_project_identity_ready()
        assert identity.canonical_macro_project("docs") == "widgets"

        app = SnapshotApp(ready_snapshot(["#gh:docs", "#git:plain"]))
        async with app.run_test() as pilot:
            ta = app.query_one(PromptTextArea)
            ta.load_text("#gh:docs ")
            ta.move_cursor(ta._location_from_absolute(len("#gh:docs ")))
            ta.focus()
            await pilot.pause()
            assert ta._macro_arg_assist_project_from_text() == "widgets"
            assert app.identity_warm_requests == []
    finally:
        identity.invalidate_macro_project_identity()


async def test_cold_identity_project_falls_back_to_global_namespace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A cold press with the hook returns ``None`` instead of the raw ref."""
    from sase.ace.tui.widgets.prompt_text_area import PromptTextArea
    from sase.macro import project_identity as identity

    _seed_identity_alias(monkeypatch)
    identity.invalidate_macro_project_identity()
    try:
        app = SnapshotApp(ready_snapshot(["#gh:docs", "#git:plain"]))
        async with app.run_test() as pilot:
            ta = app.query_one(PromptTextArea)
            ta.load_text("#gh:docs ")
            ta.move_cursor(ta._location_from_absolute(len("#gh:docs ")))
            ta.focus()
            await pilot.pause()
            assert not identity.macro_project_identity_ready()
            assert ta._macro_arg_assist_project_from_text() is None
            assert app.identity_warm_requests, "cold path must request a warm"
    finally:
        identity.invalidate_macro_project_identity()


class _BareSnapshotApp(App):
    """Host without the identity-warm hook (bare-host fallback)."""

    ENABLE_COMMAND_PALETTE = False

    def __init__(self, snapshot: LaunchableMruSnapshot) -> None:
        super().__init__()
        self._snapshot = snapshot

    def compose(self) -> ComposeResult:
        from sase.ace.tui.widgets.prompt_text_area import PromptTextArea

        yield PromptTextArea()

    def peek_launchable_mru_snapshot(self) -> LaunchableMruSnapshot:
        return self._snapshot

    def request_launchable_mru_refresh(
        self, *, reason: str, force: bool = False
    ) -> bool:
        return True


async def test_bare_host_without_hook_canonicalizes_synchronously(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A host without the hook keeps the synchronous canonicalization."""
    from sase.ace.tui.widgets.prompt_text_area import PromptTextArea
    from sase.macro import project_identity as identity

    _seed_identity_alias(monkeypatch)
    identity.invalidate_macro_project_identity()
    try:
        app = _BareSnapshotApp(ready_snapshot(["#gh:docs", "#git:plain"]))
        async with app.run_test() as pilot:
            ta = app.query_one(PromptTextArea)
            ta.load_text("#gh:docs ")
            ta.move_cursor(ta._location_from_absolute(len("#gh:docs ")))
            ta.focus()
            await pilot.pause()
            assert ta._macro_arg_assist_project_from_text() == "widgets"
            assert identity.macro_project_identity_ready()
    finally:
        identity.invalidate_macro_project_identity()


async def test_teardown_with_warm_in_flight_leaves_no_tasks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cancelling at teardown drops an in-flight identity warm cleanly."""
    import threading

    import sase.macro.project_identity as identity
    from sase.ace.tui.util.pump_tasks import cancel_pump_free_tasks

    identity.invalidate_macro_project_identity()
    host = StubHost()
    release = threading.Event()
    started = threading.Event()
    real_warm = identity.warm_macro_project_identity

    def _blocking_warm() -> None:
        started.set()
        assert release.wait(timeout=10.0)
        real_warm()

    monkeypatch.setattr(identity, "warm_macro_project_identity", _blocking_warm)
    try:
        assert host.request_macro_project_identity_warm() is True
        await wait_for(lambda: started.is_set())
        await wait_for(lambda: host._macro_identity_warm_in_flight)
        cancel_pump_free_tasks(host)
        release.set()
        await wait_for(lambda: not host._macro_identity_warm_in_flight)
        tasks = getattr(host, "_macro_identity_warm_tasks", set())
        assert len(tuple(tasks)) == 0
    finally:
        try:
            release.set()
        except Exception:  # noqa: BLE001 - release is best-effort.
            pass
        identity.invalidate_macro_project_identity()
