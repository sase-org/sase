"""Cached open behavior for the Admin Center Updates tab.

Opening the tab never refreshes from the network: the first open builds from
local caches (``cache_only=True``) and later opens reuse the in-memory
inventory with no worker at all. Only ``r`` refreshes from the network.
"""

from __future__ import annotations

import dataclasses

import pytest
from textual.widgets import OptionList

from sase.ace.testing import AcePage
from sase.ace.tui.modals import plugins_browser_pane as pbp
from sase.ace.tui.modals.config_center_session import AdminCenterSessionState
from sase.ace.tui.modals.plugins_browser_loading import is_session_memo_usable
from sase.plugins.latest import LatestInfo
from sase.plugins.render_common import humanize_age
from sase.updates import UpdateStatus
from tests.ace.tui._plugins_browser_pane_helpers import (
    _catalog,
    _core_versions,
    _open_plugins_pane,
    _patch_catalog,
    _patch_catalog_recording,
    _patch_other_panes,
)


def _highlighted_id(pane: pbp.PluginsBrowserPane) -> str | None:
    option_list = pane.query_one("#updates-list", OptionList)
    if option_list.highlighted is None:
        return None
    return option_list.get_option_at_index(option_list.highlighted).id


async def _reopen(page: AcePage, state: AdminCenterSessionState):
    page.app.pop_screen()
    await page.expect_no_modal()
    return await _open_plugins_pane(page, session_state=state)


async def test_first_open_loads_cache_only_without_refresh(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    calls = _patch_catalog_recording(monkeypatch, catalog=_catalog())
    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        assert len(calls) == 1
        assert calls[0].get("refresh") is False
        assert calls[0].get("offline") is False
        assert calls[0].get("cache_only") is True
        assert pane._rows != ()


async def test_reopen_reuses_memo_without_loader_or_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    calls = _patch_catalog_recording(monkeypatch, catalog=_catalog())
    state = AdminCenterSessionState()
    state.updates.rows.record("plugin:telegram", 0)
    async with AcePage() as page:
        first = await _open_plugins_pane(page, session_state=state)
        assert len(calls) == 1
        first_highlight = _highlighted_id(first)
        assert first_highlight == "updates-row__plugin:telegram"
        assert state.updates.inventory is not None

        second = await _reopen(page, state)
        assert len(calls) == 1
        assert second._worker is None
        assert second._rows == first._rows
        assert _highlighted_id(second) == first_highlight


async def test_reopen_after_newer_automatic_status_reloads_cache_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    calls = _patch_catalog_recording(monkeypatch, catalog=_catalog())
    state = AdminCenterSessionState()
    async with AcePage() as page:
        await _open_plugins_pane(page, session_state=state)
        assert len(calls) == 1
        assert state.updates.inventory is not None
        state.updates.inventory = dataclasses.replace(
            state.updates.inventory, checked_at=100.0
        )
        page.app._automatic_update_status = UpdateStatus(
            checked_at=110.0, components=()
        )

        await _reopen(page, state)
        assert len(calls) == 2
        assert calls[-1].get("refresh") is False
        assert calls[-1].get("cache_only") is True


async def test_refresh_reloads_from_network_and_clears_incoming_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.updates.incoming_commits import IncomingCommits

    _patch_other_panes(monkeypatch)
    calls = _patch_catalog_recording(monkeypatch, catalog=_catalog())
    state = AdminCenterSessionState()
    async with AcePage() as page:
        pane = await _open_plugins_pane(page, session_state=state)
        assert len(calls) == 1
        assert state.updates.inventory is not None
        # Mark the memo so the refresh visibly rewrites it (the recording
        # stub returns one shared result object, so identity cannot change).
        state.updates.inventory = dataclasses.replace(
            state.updates.inventory, checked_at=50.0
        )
        state.updates.incoming_commit_cache[("git", "root", "a", "b")] = (
            IncomingCommits(total=0, commits=(), source="git")
        )

        pane.action_refresh()
        await page.wait_for(lambda _s: not pane._loading and len(calls) >= 2)

        assert calls[-1].get("refresh") is True
        assert calls[-1].get("cache_only") is False
        assert ("git", "root", "a", "b") not in state.updates.incoming_commit_cache
        assert state.updates.inventory is not None
        assert state.updates.inventory.checked_at is None


async def test_offline_toggle_load_does_not_overwrite_memo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    calls = _patch_catalog_recording(monkeypatch, catalog=_catalog())
    state = AdminCenterSessionState()
    async with AcePage() as page:
        pane = await _open_plugins_pane(page, session_state=state)
        assert len(calls) == 1
        memo = state.updates.inventory
        assert memo is not None

        pane.action_toggle_offline()
        await page.wait_for(lambda _s: not pane._loading and pane._offline)

        assert calls[-1].get("offline") is True
        assert state.updates.inventory is memo


async def test_mutation_completion_after_unmount_invalidates_memo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from datetime import datetime

    from sase.ace.tui.actions.proc_actions import TrackedProcCompletion
    from sase.ace.tui.proc_observer import ObservedProc

    _patch_other_panes(monkeypatch)
    calls = _patch_catalog_recording(monkeypatch, catalog=_catalog())
    state = AdminCenterSessionState()
    async with AcePage() as page:
        pane = await _open_plugins_pane(page, session_state=state)
        assert len(calls) == 1
        assert state.updates.inventory is not None
        page.app.pop_screen()
        await page.expect_no_modal()

        pane._handle_code_update_completion(
            TrackedProcCompletion(
                proc_info=ObservedProc(
                    proc_id="session-test",
                    proc_type="sase-update",
                    cl_name="",
                    project_file="",
                    status="done",
                    message="done",
                    started_at=datetime(2026, 8, 21, 12, 0, 0),
                    display_name="sase-update",
                ),
                success=True,
                message="done",
                output="",
                payload=None,
            ),
            failure_prefix="sase update failed",
        )

        assert state.updates.inventory is None
        await _open_plugins_pane(page, session_state=state)
        assert len(calls) == 2


async def test_lazy_plugin_latest_survives_reopen(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog_recording(monkeypatch, catalog=_catalog())
    state = AdminCenterSessionState()
    async with AcePage() as page:
        pane = await _open_plugins_pane(page, session_state=state)
        pane._apply_plugin_latest(
            "github",
            LatestInfo(checked=True, version="9.9.9", source="index"),
        )
        assert pane._rows_by_key["plugin:github"].latest_version == "9.9.9"

        second = await _reopen(page, state)
        assert second._rows_by_key["plugin:github"].latest_version == "9.9.9"


async def test_restored_memo_skips_indicator_and_editable_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    status = UpdateStatus(checked_at=100.0, components=())
    _patch_catalog(
        monkeypatch,
        catalog=_catalog(),
        core_versions=_core_versions(),
        update_status=status,
        fresh_editable_roots=frozenset({"/repo/shared"}),
    )
    pushed: list[object] = []
    state = AdminCenterSessionState()
    async with AcePage() as page:
        monkeypatch.setattr(
            page.app,
            "_schedule_updates_indicator_revalidation",
            pushed.append,
        )
        first = await _open_plugins_pane(page, session_state=state)
        assert pushed != []
        assert first._fresh_editable_roots_evidence is not None
        assert state.updates.inventory is not None
        pushed.clear()

        second = await _reopen(page, state)
        assert pushed == []
        assert second._fresh_editable_roots_evidence is None


async def test_header_age_label_prefers_checked_at(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog_recording(monkeypatch, catalog=_catalog())
    state = AdminCenterSessionState()
    async with AcePage() as page:
        await _open_plugins_pane(page, session_state=state)
        assert state.updates.inventory is not None
        state.updates.inventory = dataclasses.replace(
            state.updates.inventory, checked_at=100.0
        )
        monkeypatch.setattr(pbp, "_clock", lambda: 4600.0)

        second = await _reopen(page, state)
        assert second._checked_at == 100.0
        assert second._cache_age_label() == humanize_age(4500.0)


def test_is_session_memo_usable_prefers_newer_periodic_data() -> None:
    assert is_session_memo_usable(None, None) is False
    memo = pbp._PluginsLoadResult(catalog=None, error=None, now=100.0, checked_at=100.0)
    assert is_session_memo_usable(memo, None) is True
    assert (
        is_session_memo_usable(memo, UpdateStatus(checked_at=90.0, components=()))
        is True
    )
    assert (
        is_session_memo_usable(memo, UpdateStatus(checked_at=110.0, components=()))
        is False
    )
    assert (
        is_session_memo_usable(
            dataclasses.replace(memo, checked_at=None),
            UpdateStatus(checked_at=110.0, components=()),
        )
        is False
    )
