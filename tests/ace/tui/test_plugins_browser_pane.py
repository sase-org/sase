"""Widget-level tests for the Config Center Plugins tab (Phase 2).

These cover the worker-backed catalog load populating the grouped list, the
loading→populated transition, the live filter, and the empty / error states.
The catalog backend is patched with a deterministic fixture so no real
``gh`` / network / cache is touched. The sibling Settings and XPrompts panes
are also stubbed so opening the modal stays cheap and deterministic.
"""

from __future__ import annotations

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.modals import config_pane as cp
from sase.ace.tui.modals import plugins_browser_pane as pbp
from sase.ace.tui.modals.config_center_modal import ConfigCenterModal
from sase.ace.tui.modals.plugins_browser_pane import PluginsBrowserPane
from sase.plugins.catalog import PluginCatalog, PluginCatalogEntry
from sase.plugins.installed import InstalledInfo
from sase.plugins.latest import LatestInfo

_NOW = 1_700_000_000.0


def _entry(
    name: str,
    *,
    owner: str,
    description: str = "",
    installed: InstalledInfo | None = None,
    latest: LatestInfo | None = None,
    topics: tuple[str, ...] = (),
) -> PluginCatalogEntry:
    repo = f"sase-{name}"
    return PluginCatalogEntry(
        name=name,
        repo=repo,
        full_name=f"{owner}/{repo}",
        owner=owner,
        description=description,
        url=f"https://github.com/{owner}/{repo}",
        homepage="",
        topics=topics,
        stars=0,
        archived=False,
        license="MIT",
        updated_at="2026-06-01",
        installed=installed or InstalledInfo.not_installed(),
        latest=latest or LatestInfo.unknown(),
    )


def _catalog() -> PluginCatalog:
    """A deterministic catalog: 3 built-in + 1 community, 2 installed, 1 update."""
    github = _entry(
        "github",
        owner="sase-org",
        description="GitHub VCS and workspace provider.",
        installed=InstalledInfo(installed=True, version="1.2.0"),
        latest=LatestInfo(checked=True, version="1.3.0", source="index"),
        topics=("sase-plugin", "github"),
    )
    telegram = _entry(
        "telegram",
        owner="sase-org",
        description="Telegram chat integration.",
        installed=InstalledInfo(installed=True, version="0.5.0"),
        latest=LatestInfo(checked=True, version="0.5.0", source="index"),
    )
    nvim = _entry(
        "nvim",
        owner="sase-org",
        description="Neovim editor integration.",
        latest=LatestInfo(checked=True, version="2.0.0", source="index"),
    )
    acme = _entry(
        "acme",
        owner="acme-corp",
        description="Third-party automation helpers.",
        latest=LatestInfo(checked=True, version="0.1.0", source="index"),
    )
    return PluginCatalog(
        fetched_at=_NOW,
        entries=(github, nvim, telegram, acme),
        from_cache=True,
        stale=False,
    )


def _patch_catalog(
    monkeypatch: pytest.MonkeyPatch,
    *,
    catalog: PluginCatalog | None = None,
    error: str | None = None,
) -> None:
    result = pbp._PluginsLoadResult(catalog=catalog, error=error, now=_NOW)
    monkeypatch.setattr(pbp, "_load_plugins_catalog", lambda **_kw: result)


def _patch_other_panes(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the sibling Settings / XPrompts panes cheap and deterministic."""
    result = cp._LoadResult(view=None, error=None, token=("tok", 1))
    monkeypatch.setattr(cp, "_load_config_view", lambda **_kw: result)
    monkeypatch.setattr(
        "sase.ace.tui.modals.xprompt_browser_pane.get_all_prompts",
        lambda project=None: {},
    )
    monkeypatch.setattr(
        "sase.xprompt.loader.get_all_project_local_prompts",
        lambda: {},
    )


async def _open_plugins_pane(page: AcePage) -> PluginsBrowserPane:
    modal = ConfigCenterModal(initial_tab="plugins")
    page.app.push_screen(modal)
    await page.expect_modal("ConfigCenterModal")
    await page.wait_for(lambda _s: bool(modal.query("#plugins")))
    pane = modal.query_one("#plugins", PluginsBrowserPane)
    await page.wait_for(lambda _s: not pane._loading)
    return pane


def _option_labels(pane: PluginsBrowserPane) -> list[str]:
    from textual.widgets import OptionList

    option_list = pane.query_one("#plugins-list", OptionList)
    labels: list[str] = []
    for index in range(option_list.option_count):
        opt = option_list.get_option_at_index(index)
        prompt = opt.prompt
        labels.append(prompt.plain if hasattr(prompt, "plain") else str(prompt))
    return labels


async def test_plugins_pane_loads_and_groups(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(monkeypatch, catalog=_catalog())
    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        # Both section headers and every plugin row are present.
        labels = _option_labels(pane)
        assert any("Built-in" in label for label in labels)
        assert any("Community" in label for label in labels)
        assert any("github" in label for label in labels)
        assert any("acme" in label for label in labels)
        # The status placeholder is hidden and the list is visible.
        assert pane.query_one("#plugins-list").display is True
        assert pane.query_one("#plugins-status").display is False
        # A non-header row is auto-highlighted.
        from textual.widgets import OptionList

        option_list = pane.query_one("#plugins-list", OptionList)
        assert option_list.highlighted is not None
        highlighted = option_list.get_option_at_index(option_list.highlighted)
        assert highlighted.id is not None
        assert not str(highlighted.id).startswith("__header__")


async def test_plugins_pane_summary_counts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(monkeypatch, catalog=_catalog())
    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        summary = pane._summary_text()
        assert "4 plugins" in summary
        assert "2 installed" in summary
        assert "1 updates available" in summary
        assert "just now" in summary


async def test_plugins_pane_shows_update_marker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(monkeypatch, catalog=_catalog())
    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        labels = _option_labels(pane)
        github_row = next(label for label in labels if "github" in label)
        # Installed with an available update: version arrow + update glyph.
        assert "v1.2.0 → v1.3.0" in github_row
        assert "↑" in github_row
        nvim_row = next(label for label in labels if "nvim" in label)
        assert "latest v2.0.0" in nvim_row


async def test_plugins_pane_filter_narrows_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(monkeypatch, catalog=_catalog())
    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        pane.action_focus_filter()
        await page.pause()
        await page.press("g", "i", "t", "h", "u", "b")
        await page.wait_for(
            lambda _s: (
                [e.name for _, _, e_list in pane._grouped for e in e_list] == ["github"]
            )
        )
        labels = _option_labels(pane)
        assert any("github" in label for label in labels)
        assert not any("telegram" in label for label in labels)
        # Cancelling restores the full list.
        pane.cancel_input()
        await page.wait_for(
            lambda _s: any(
                e.name == "telegram" for _, _, lst in pane._grouped for e in lst
            )
        )


async def test_plugins_pane_filter_no_matches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(monkeypatch, catalog=_catalog())
    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        pane.action_focus_filter()
        await page.pause()
        await page.press("z", "z", "z", "z")
        await page.wait_for(lambda _s: not pane._grouped)
        assert pane.query_one("#plugins-status").display is True
        assert "No plugins match" in pane._status_message()


async def test_plugins_pane_empty_catalog(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    empty = PluginCatalog(fetched_at=_NOW, entries=(), from_cache=True, stale=False)
    _patch_catalog(monkeypatch, catalog=empty)
    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        assert pane.query_one("#plugins-status").display is True
        assert pane.query_one("#plugins-list").display is False
        assert "No SASE plugins found." in pane._status_message()


async def test_plugins_pane_error_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(monkeypatch, catalog=None, error="gh not found")
    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        assert pane._error == "gh not found"
        assert pane.query_one("#plugins-status").display is True
        assert "gh not found" in pane._status_message()


async def test_config_center_cycles_three_tabs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(monkeypatch, catalog=_catalog())
    async with AcePage() as page:
        modal = ConfigCenterModal(initial_tab="config")
        page.app.push_screen(modal)
        await page.expect_modal("ConfigCenterModal")
        assert modal._active_tab == "config"
        modal.action_next_center_tab()
        assert modal._active_tab == "plugins"
        modal.action_next_center_tab()
        assert modal._active_tab == "xprompts"
        modal.action_next_center_tab()
        assert modal._active_tab == "config"
        # Wrapping backwards lands on the new Plugins tab between the two.
        modal.action_prev_center_tab()
        assert modal._active_tab == "xprompts"
