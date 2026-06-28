"""Detail, refresh, offline, and verbose-state tests for the Plugins pane."""

from __future__ import annotations

import pytest

from sase.ace.testing import AcePage
from sase.plugins.catalog import PluginCatalog
from sase.updates.incoming_commits import CommitSummary, IncomingCommits
from tests.ace.tui._plugins_browser_pane_helpers import (
    _NOW,
    _catalog,
    _open_plugins_pane,
    _option_labels,
    _patch_catalog,
    _patch_catalog_recording,
    _patch_other_panes,
    _render,
)


async def test_plugins_pane_detail_follows_highlight(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(monkeypatch, catalog=_catalog())
    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        # The first non-header row (github, built-in) is shown on load.
        assert pane._detail_name == "github"
        entry = pane._entry_by_name("github")
        assert entry is not None
        text = _render(pane._detail_renderable(entry))
        assert "github" in text
        assert "BUILT-IN" in text
        assert "GitHub VCS" in text


async def test_plugins_pane_detail_shows_lazy_incoming_commits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(monkeypatch, catalog=_catalog())
    calls: list[object] = []

    def _fake_fetch(*args: object, **_kwargs: object) -> IncomingCommits:
        calls.extend(args)
        return IncomingCommits(
            total=3,
            commits=(
                CommitSummary("abc1234", "Newest plugin change"),
                CommitSummary("def5678", "Older plugin change"),
            ),
            source="github",
        )

    from sase.ace.tui.modals import plugins_browser_pane as pbp

    monkeypatch.setattr(pbp, "_fetch_incoming_commits", _fake_fetch)
    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        await page.wait_for(lambda _s: bool(pane._incoming_commit_cache))
        entry = pane._entry_by_name("github")
        assert entry is not None
        text = _render(pane._detail_renderable(entry))

        assert calls
        assert "↑ 3 incoming commits" in text
        assert "abc1234" in text
        assert "Newest plugin change" in text
        assert "+1 more" in text


async def test_plugins_pane_detail_shows_community_warning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(monkeypatch, catalog=_catalog())
    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        # Navigate down to the lone community plugin (acme).
        pane.action_next_option()
        pane.action_next_option()
        pane.action_next_option()
        await page.wait_for(lambda _s: pane._detail_name == "acme")
        entry = pane._entry_by_name("acme")
        assert entry is not None
        assert entry.is_community
        text = _render(pane._detail_renderable(entry))
        assert "COMMUNITY" in text
        assert "acme-corp" in text


async def test_plugins_pane_offline_toggle_reloads_and_badges(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    calls = _patch_catalog_recording(monkeypatch, catalog=_catalog())
    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        assert calls[-1].get("offline") is False
        pane.action_toggle_offline()
        await page.wait_for(lambda _s: not pane._loading and pane._offline)
        # The reload was issued in offline mode and the header badges it.
        assert calls[-1].get("offline") is True
        assert "OFFLINE" in pane._summary_text()
        assert "(on)" in pane._hints()


async def test_plugins_pane_verbose_toggle_adds_columns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(monkeypatch, catalog=_catalog())
    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        assert not any("★" in label for label in _option_labels(pane))
        pane.action_toggle_verbose()
        await page.wait_for(
            lambda _s: any("★" in label for label in _option_labels(pane))
        )
        labels = _option_labels(pane)
        github_row = next(label for label in labels if "github" in label)
        assert "★" in github_row
        assert "2026-06-01" in github_row


async def test_plugins_pane_refresh_forces_reload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    calls = _patch_catalog_recording(monkeypatch, catalog=_catalog())
    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        # The initial cache-first load does not force a network refresh.
        assert calls[-1].get("refresh") is False
        pane.action_refresh()
        await page.wait_for(lambda _s: not pane._loading and len(calls) >= 2)
        assert calls[-1].get("refresh") is True


async def test_plugins_pane_stale_cache_hint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    stale = PluginCatalog(
        fetched_at=_NOW - 10_000,
        entries=_catalog().entries,
        from_cache=True,
        stale=True,
    )
    _patch_catalog(monkeypatch, catalog=stale)
    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        assert "stale" in pane._summary_text().plain
