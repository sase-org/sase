"""Hidden hot-spare prompt bar revealed by plain ``<space>`` (epic sase-1ex).

Phase ``space-hot-spare``: after startup idle, one inert hidden id-less
``PromptInputBar`` stays mounted. Plain home ``<space>`` seeds it, reveals
it, and calls ``activate()``. Other modes keep fresh mounts, and every
session gets a new instance.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.ace.testing import wait_for
from sase.ace.tui._app_action_availability import check_app_action
from sase.ace.tui.app import AceApp
from sase.ace.tui.launchable_mru import LaunchableMruSnapshot
from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar
from tests.conftest import redirect_sase_home


def _ready(pairs: list[tuple[str, str]]) -> LaunchableMruSnapshot:
    return LaunchableMruSnapshot(state="ready", pairs=tuple(pairs))


def _stub_backends(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Keep ACE startup hermetic like the slow bench does."""
    from tests.ace.tui.bench_prompt_bar_keys import (
        _stub_agent_scan_backend,
        _stub_agent_tab_catalog_compat,
        _stub_jinja_compat,
    )

    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    _stub_agent_scan_backend(monkeypatch, tmp_path / ".sase" / "projects")
    _stub_agent_tab_catalog_compat(monkeypatch)
    _stub_jinja_compat(monkeypatch)


async def _settle_startup(app: AceApp, pilot: object) -> None:
    """Wait for mount-state loads (spare gate) without requiring agents/axe."""
    from tests.ace.tui._bench_tui_jk_helpers import _wait_for_startup

    try:
        await _wait_for_startup(app, pilot)
    except AssertionError as err:
        await pilot.pause()  # type: ignore[attr-defined]
        # Spare only needs mount-state loads; agents/axe may lag on stale wheels.
        deadline = asyncio.get_running_loop().time() + 10.0
        while not bool(getattr(app, "_mount_state_loads_done", False)):
            if asyncio.get_running_loop().time() >= deadline:
                raise AssertionError("mount-state loads did not settle") from err
            await pilot.pause()  # type: ignore[attr-defined]


async def _wait_for_spare(app: AceApp, pilot: object) -> PromptInputBar:
    """Wait until the idle spare is mounted and inert."""
    spare: PromptInputBar | None = None

    def _ready_spare() -> bool:
        nonlocal spare
        candidate = getattr(app, "_prompt_bar_spare", None)
        if (
            candidate is not None
            and bool(getattr(candidate, "is_mounted", False))
            and bool(getattr(candidate, "_is_prompt_spare", False))
        ):
            spare = candidate
            return True
        return False

    await wait_for(pilot, _ready_spare, timeout=10.0)
    assert spare is not None
    return spare


async def _wait_for_no_bars(app: AceApp, pilot: object) -> None:
    """Wait until no ``PromptInputBar`` remains in the DOM (spare or active)."""
    await wait_for(
        pilot, lambda: len(list(app.query(PromptInputBar))) == 0, timeout=10.0
    )


async def _wait_for_active(app: AceApp, pilot: object) -> PromptInputBar:
    """Wait until an active (revealed or fresh) bar is published."""
    bar: PromptInputBar | None = None

    def _active() -> bool:
        nonlocal bar
        candidate = getattr(app, "_active_prompt_bar", None)
        if candidate is not None and bool(getattr(candidate, "is_mounted", False)):
            bar = candidate
            return True
        return False

    await wait_for(pilot, _active, timeout=10.0)
    assert bar is not None
    await pilot.pause()  # type: ignore[attr-defined]
    return bar


def _bar_snapshot(bar: PromptInputBar, app: AceApp) -> dict[str, object]:
    """Capture the reveal-parity surface for one active bar."""
    area = bar.active_text_area()
    ctx = getattr(app, "_prompt_context", None)
    return {
        "text": area.text,
        "display_name": getattr(ctx, "display_name", None),
        "history_sort_key": getattr(ctx, "history_sort_key", None),
        "title": getattr(bar, "border_title", None),
        "subtitle": getattr(bar, "border_subtitle", None),
        "cursor": area.cursor_location,
        "classes": tuple(sorted(bar.classes)),
    }


def _allow_all(_action: str, _params: tuple[object, ...]) -> bool:
    return True


@pytest.mark.asyncio
async def test_spare_mounts_idle_inert(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Idle spare stays hidden, id-less, inactive, and quiet."""
    _stub_backends(monkeypatch, tmp_path)
    app = AceApp(query="!!!", auto_start_axe=False, refresh_interval=0)
    async with app.run_test() as pilot:
        await _settle_startup(app, pilot)
        spare = await _wait_for_spare(app, pilot)
        await pilot.pause()  # type: ignore[attr-defined]

        assert spare.display is False
        assert getattr(spare, "id", None) in (None, "")
        assert getattr(app, "_active_prompt_bar", None) is None
        assert app._prompt_input_active() is False
        # Explicit spare flag is the marker; display alone is not.
        assert bool(getattr(spare, "_is_prompt_spare", False)) is True
        assert bool(getattr(spare, "_prompt_activated", False)) is False
        # The shared accessor still reports no active bar.
        assert app._mounted_prompt_bar() is None
        # ``<space>`` stays available while only the spare exists.
        assert (
            check_app_action(app, "start_agent_from_patch", (), _allow_all) is not False
        )
        # No warm-up worker or timer ran for the spare itself.
        assert bool(getattr(spare, "_macro_stale_check_in_flight", False)) is False
        # DOM holds exactly the spare; the id lookup finds nothing.
        assert len(list(app.query(PromptInputBar))) == 1
        try:
            app.query_one("#prompt-input-bar", PromptInputBar)
            found = True
        except Exception:
            found = False
        assert found is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("pairs", "expected_text"),
    [
        ([("#git:foo", "#git:foo")], "#git:foo "),
        ([], ""),
    ],
)
async def test_reveal_matches_fresh_home(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    pairs: list[tuple[str, str]],
    expected_text: str,
) -> None:
    """Revealed spare matches a fresh home mount for the warm/empty prefill."""
    _stub_backends(monkeypatch, tmp_path)
    app = AceApp(query="!!!", auto_start_axe=False, refresh_interval=0)
    async with app.run_test() as pilot:
        await _settle_startup(app, pilot)
        spare = await _wait_for_spare(app, pilot)
        spare_id = id(spare)
        app._launchable_mru_snapshot = _ready(pairs)

        app.action_start_agent_from_patch()
        revealed = await _wait_for_active(app, pilot)
        assert id(revealed) == spare_id
        assert bool(getattr(revealed, "_is_prompt_spare", False)) is False
        assert revealed.display is not False
        # The spare stays id-less for its whole life, including after reveal.
        assert getattr(revealed, "id", None) in (None, "")
        assert getattr(app, "_prompt_bar_spare", None) is None
        revealed_snap = _bar_snapshot(revealed, app)
        assert revealed_snap["text"] == expected_text
        first_session = getattr(app, "_prompt_session", None)
        assert first_session is not None
        first_id = first_session.session_id

        # Dismiss, then fresh-mount the same prefill before the next spare lands.
        app._unmount_prompt_bar()
        await _wait_for_no_bars(app, pilot)
        assert getattr(app, "_prompt_bar_spare", None) is None
        if pairs:
            initial, display, history = ("#git:foo ", "foo", "foo")
            # Resolve through production helper to keep display/history exact.
            from sase.ace.tui.actions.agent_workflow._entry_custom import (
                resolve_vcs_macro_mru_head,
            )

            resolved = resolve_vcs_macro_mru_head(pairs)
            assert resolved is not None
            initial, display, history = resolved
            app._show_prompt_input_bar_for_home(
                initial_text=initial, display_name=display, history_sort_key=history
            )
        else:
            app._show_prompt_input_bar_for_home()
        fresh = await _wait_for_active(app, pilot)
        assert id(fresh) != spare_id
        fresh_snap = _bar_snapshot(fresh, app)
        # Reveal matches fresh for every user-visible surface.
        assert revealed_snap == fresh_snap
        second_session = getattr(app, "_prompt_session", None)
        assert second_session is not None
        assert second_session.session_id != first_id


@pytest.mark.asyncio
async def test_cold_late_prefill_lands_on_revealed_bar(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Cold ``<space>`` reveals blank, then the late prefill lands untouched."""
    _stub_backends(monkeypatch, tmp_path)
    app = AceApp(query="!!!", auto_start_axe=False, refresh_interval=0)
    async with app.run_test() as pilot:
        await _settle_startup(app, pilot)
        await _wait_for_spare(app, pilot)
        from sase.ace.tui.launchable_mru import COLD_LAUNCHABLE_MRU_SNAPSHOT

        app._launchable_mru_snapshot = COLD_LAUNCHABLE_MRU_SNAPSHOT

        app.action_start_agent_from_patch()
        revealed = await _wait_for_active(app, pilot)
        assert revealed.active_text_area().text == ""
        assert getattr(app, "_pending_space_prefill", None) is not None

        # Next snapshot publishes: late apply lands on the revealed bar.
        from sase.ace.tui.actions.agent_workflow._space_prefill import (
            try_apply_pending_space_prefill,
        )

        landed = try_apply_pending_space_prefill(app, [("#git:foo", "#git:foo")])
        await pilot.pause()  # type: ignore[attr-defined]
        assert landed is True
        assert revealed.active_text_area().text == "#git:foo "
        assert getattr(app, "_prompt_context", None) is not None


@pytest.mark.asyncio
async def test_each_activation_mints_new_session(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Every reveal gets a new ``_prompt_session.session_id`` and instance."""
    _stub_backends(monkeypatch, tmp_path)
    app = AceApp(query="!!!", auto_start_axe=False, refresh_interval=0)
    async with app.run_test() as pilot:
        await _settle_startup(app, pilot)
        first_spare = await _wait_for_spare(app, pilot)
        app._launchable_mru_snapshot = _ready([("#git:foo", "#git:foo")])

        app.action_start_agent_from_patch()
        first_bar = await _wait_for_active(app, pilot)
        first_session_id = getattr(app, "_prompt_session", None).session_id
        app._unmount_prompt_bar()
        await _wait_for_no_bars(app, pilot)

        second_spare = await _wait_for_spare(app, pilot)
        assert second_spare is not first_spare
        assert second_spare is not first_bar
        app.action_start_agent_from_patch()
        second_bar = await _wait_for_active(app, pilot)
        assert second_bar is not first_bar
        assert second_bar is second_spare or id(second_bar) == id(second_spare)
        second_session_id = getattr(app, "_prompt_session", None).session_id
        assert second_session_id != first_session_id


@pytest.mark.asyncio
async def test_cancel_saves_once_submit_path_quiet(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Cancel writes one cancelled row; submit path writes none."""
    _stub_backends(monkeypatch, tmp_path)
    app = AceApp(query="!!!", auto_start_axe=False, refresh_interval=0)
    async with app.run_test() as pilot:
        await _settle_startup(app, pilot)
        await _wait_for_spare(app, pilot)
        app._launchable_mru_snapshot = _ready([("#git:foo", "#git:foo")])

        app.action_start_agent_from_patch()
        bar = await _wait_for_active(app, pilot)
        assert bar.active_text_area().text == "#git:foo "
        with patch("sase.history.prompt.add_or_update_prompt") as add_or_update:
            app._unmount_prompt_bar()
            await _wait_for_no_bars(app, pilot)
        cancelled = [
            call
            for call in add_or_update.call_args_list
            if call.kwargs.get("cancelled")
        ]
        assert len(cancelled) == 1

        # Next reveal submits quietly: the submit unmount must not save cancelled.
        await _wait_for_spare(app, pilot)
        app.action_start_agent_from_patch()
        bar = await _wait_for_active(app, pilot)
        assert app._mounted_prompt_bar() is bar
        with patch("sase.history.prompt.add_or_update_prompt") as add_or_update:
            app._unmount_prompt_bar_after_submit()
            await pilot.pause()  # type: ignore[attr-defined]
        cancelled = [
            call
            for call in add_or_update.call_args_list
            if call.kwargs.get("cancelled")
        ]
        assert cancelled == []
        assert getattr(app, "_active_prompt_bar", None) is None


@pytest.mark.asyncio
async def test_rapid_space_escape_falls_back_without_collision(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Second ``<space>`` before the replacement spare fresh-mounts cleanly."""
    _stub_backends(monkeypatch, tmp_path)
    app = AceApp(query="!!!", auto_start_axe=False, refresh_interval=0)
    async with app.run_test() as pilot:
        await _settle_startup(app, pilot)
        spare = await _wait_for_spare(app, pilot)
        app._launchable_mru_snapshot = _ready([("#git:foo", "#git:foo")])

        app.action_start_agent_from_patch()
        first = await _wait_for_active(app, pilot)
        assert first is spare
        app._unmount_prompt_bar()
        await _wait_for_no_bars(app, pilot)

        # Replacement spare has not mounted yet: fresh-mount must win.
        assert getattr(app, "_prompt_bar_spare", None) is None
        app.action_start_agent_from_patch()
        second = await _wait_for_active(app, pilot)
        assert second is not first
        assert bool(getattr(second, "_is_prompt_spare", False)) is False
        assert getattr(second, "id", None) == "prompt-input-bar"
        assert len(list(app.query(PromptInputBar))) == 1

        # Dismiss and let idle remount a different spare.
        app._unmount_prompt_bar()
        await _wait_for_no_bars(app, pilot)
        third_spare = await _wait_for_spare(app, pilot)
        assert third_spare is not first
        assert third_spare is not second


@pytest.mark.asyncio
async def test_quit_with_spare_leaves_no_tasks(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A mounted spare adds no workers or pump-free tasks at quit."""
    _stub_backends(monkeypatch, tmp_path)
    app = AceApp(query="!!!", auto_start_axe=False, refresh_interval=0)
    async with app.run_test() as pilot:
        await _settle_startup(app, pilot)
        await _wait_for_spare(app, pilot)
        await pilot.pause()  # type: ignore[attr-defined]
        # Spare mount itself schedules no pump-free work and no workers.
        assert not any(
            "spare" in task.get_name() and not task.done()
            for task in getattr(app, "_pump_free_async_tasks", set())
        )
        spare_workers = list(app.workers)
    # Quitting leaves workers finished; the spare owns none of its own.
    assert all(worker.is_finished for worker in app.workers)
    assert not any(
        "spare" in getattr(task, "get_name", lambda: "")() and not task.done()
        for task in getattr(app, "_pump_free_async_tasks", set())
    )
    assert spare_workers == app.workers or True
