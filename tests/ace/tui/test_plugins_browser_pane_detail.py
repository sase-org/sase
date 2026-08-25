"""Detail, refresh, offline, and verbose-state tests for the Plugins pane."""

from __future__ import annotations

from dataclasses import replace

import pytest
from textual.containers import VerticalScroll
from textual.widgets import OptionList

from sase.ace.testing import AcePage
from sase.ace.tui.modals import plugins_browser_pane as pbp
from sase.plugins.catalog import PluginCatalog, PluginCatalogEntry
from sase.plugins.latest import LatestInfo
from sase.updates.incoming_commits import CommitSummary, IncomingCommits
from tests.ace.tui._plugins_browser_pane_helpers import (
    _NOW,
    _catalog,
    _entry,
    _open_plugins_pane,
    _option_labels,
    _patch_catalog,
    _patch_catalog_recording,
    _patch_other_panes,
    _render,
)


def _binding_action(key: str) -> str | None:
    """Action bound to *key* in ``PluginsBrowserPane.BINDINGS``."""
    for binding in pbp.PluginsBrowserPane.BINDINGS:
        if isinstance(binding, tuple):
            bind_key, action = binding[0], binding[1]
        else:
            bind_key, action = binding.key, binding.action
        if bind_key == key:
            return action
    return None


def _disable_incoming_commits(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        pbp,
        "_load_incoming_commits_config",
        lambda: pbp._IncomingCommitsConfig(enabled=False),
    )


def test_incoming_commits_config_loads_confirm_limit() -> None:
    config = pbp._load_incoming_commits_config(
        lambda: {
            "ace": {
                "updates": {
                    "incoming_commits": {
                        "enabled": True,
                        "max_per_repo": 9,
                        "confirm_max_per_repo": 123,
                    }
                }
            }
        }
    )

    assert config.enabled is True
    assert config.max_per_repo == 9
    assert config.confirm_max_per_repo == 123


def test_plugins_pane_binds_detail_scroll_keys() -> None:
    assert _binding_action("ctrl+d") == "scroll_detail_down"
    assert _binding_action("ctrl+u") == "scroll_detail_up"
    assert _binding_action("g") == "scroll_to_top"
    assert _binding_action("G") == "scroll_to_bottom"
    assert _binding_action("shift+g") == "scroll_to_bottom"
    assert _binding_action("a") == "sync_agents"


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


async def test_plugins_pane_short_detail_does_not_require_scroll(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    _disable_incoming_commits(monkeypatch)
    _patch_catalog(monkeypatch, catalog=_catalog())
    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        await page.wait_for(lambda _s: pane._detail_name == "github")
        scroll = pane.query_one("#plugins-detail-scroll", VerticalScroll)

        await page.pause()

        assert scroll.max_scroll_y == 0
        assert "ctrl+d/u scroll" in pane._hints()


async def test_plugins_pane_scroll_keys_move_detail_not_selection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    _disable_incoming_commits(monkeypatch)
    description = "\n".join(f"Long detail line {index}" for index in range(100))
    entry = _entry(
        "github",
        owner="sase-org",
        description=description,
    )
    catalog = PluginCatalog(
        fetched_at=_NOW,
        entries=(entry,),
        from_cache=True,
        stale=False,
    )
    _patch_catalog(monkeypatch, catalog=catalog)

    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        await page.wait_for(lambda _s: pane._detail_name == "github")
        option_list = pane.query_one("#plugins-list", OptionList)
        highlighted_before = option_list.highlighted
        scroll = pane.query_one("#plugins-detail-scroll", VerticalScroll)
        await page.wait_for(lambda _s: scroll.max_scroll_y > 0)

        await page.press("ctrl+d")
        await page.wait_for(lambda _s: scroll.scroll_y > 0)
        after_down = scroll.scroll_y

        await page.press("ctrl+u")
        await page.wait_for(lambda _s: scroll.scroll_y < after_down)

        await page.press("G")
        await page.wait_for(lambda _s: scroll.scroll_y == scroll.max_scroll_y)

        await page.press("g")
        await page.wait_for(lambda _s: scroll.scroll_y == 0)

        assert option_list.highlighted == highlighted_before
        assert option_list.has_focus


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


async def test_plugins_pane_lazy_fetches_highlighted_latest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    _disable_incoming_commits(monkeypatch)
    catalog = PluginCatalog(
        fetched_at=_NOW,
        entries=(
            _entry(
                "nvim",
                owner="sase-org",
                description="Neovim editor integration.",
                latest=LatestInfo.unknown(),
            ),
        ),
        from_cache=True,
        stale=False,
    )
    _patch_catalog(monkeypatch, catalog=catalog)
    calls: list[str] = []

    def _fake_enrich(
        entry: PluginCatalogEntry, **_kwargs: object
    ) -> PluginCatalogEntry:
        calls.append(entry.name)
        return replace(
            entry,
            latest=LatestInfo(checked=True, version="2.0.0", source="index"),
        )

    monkeypatch.setattr(pbp, "_enrich_entry_latest", _fake_enrich)
    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        await page.wait_for(
            lambda _s: (
                (entry := pane._entry_by_name("nvim")) is not None
                and entry.latest.version == "2.0.0"
            )
        )
        entry = pane._entry_by_name("nvim")
        assert calls == ["nvim"]
        assert entry is not None
        assert entry.latest.version == "2.0.0"
        text = _render(pane._detail_renderable(entry))
        assert "2.0.0" in text


async def test_plugins_pane_skips_lazy_latest_when_already_checked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    _disable_incoming_commits(monkeypatch)
    catalog = PluginCatalog(
        fetched_at=_NOW,
        entries=(
            _entry(
                "nvim",
                owner="sase-org",
                description="Neovim editor integration.",
                latest=LatestInfo(checked=True, version="1.2.3", source="index"),
            ),
        ),
        from_cache=True,
        stale=False,
    )
    _patch_catalog(monkeypatch, catalog=catalog)
    monkeypatch.setattr(
        pbp,
        "_enrich_entry_latest",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("already-checked latest must not refetch")
        ),
    )
    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        await page.wait_for(lambda _s: pane._detail_name == "nvim")
        entry = pane._entry_by_name("nvim")
        assert entry is not None
        assert entry.latest.checked is True
        assert entry.latest.version == "1.2.3"
        assert pane._plugin_latest_workers == {}


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
        acme_row = next(label for label in labels if "acme-corp/sase-acme" in label)
        assert "★" in acme_row
        assert "2026-06-01" in acme_row


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
