"""Widget-level tests for the Config Center Plugins tab (Phases 2 & 3).

Phase 2 cases cover the worker-backed catalog load populating the grouped
list, the loading→populated transition, the live filter, and the empty /
error states. Phase 3 cases cover the ``show``-equivalent detail panel
following the highlighted row (including the community warning), the offline
badge / reload, the verbose row columns, and the refresh reload. The catalog
backend is patched with a deterministic fixture so no real ``gh`` / network /
cache is touched. The sibling Config and XPrompts panes are also stubbed so
opening the modal stays cheap and deterministic.
"""

from __future__ import annotations

import io

import pytest
from rich.console import Console

from pathlib import Path

from sase.ace.testing import AcePage
from sase.ace.tui.modals import config_pane as cp
from sase.ace.tui.modals import plugins_browser_pane as pbp
from sase.ace.tui.modals.config_center_modal import ConfigCenterModal
from sase.ace.tui.modals.plugin_action_confirm_modal import (
    PluginActionConfirmModal,
    PluginActionConfirmResult,
    PluginActionVariant,
)
from sase.ace.tui.modals.plugins_browser_pane import PluginsBrowserPane
from sase.plugins.catalog import PluginCatalog, PluginCatalogEntry
from sase.plugins.installed import InstalledInfo
from sase.plugins.latest import LatestInfo
from sase.plugins.operations import (
    InstallNotFound,
    InstallOutcome,
    InstallReady,
    NoPlugins,
    ResolvedSpec,
    UpdateOutcome,
    UpdateReady,
    UpdateUnknown,
)
from sase.uv_tool.detect import NotUvToolInstall, NotUvToolReason
from sase.uv_tool.receipt import Requirement
from sase.uv_tool.runner import ChangeKind, UvChangeSet, UvPackageChange

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


def _patch_catalog_recording(
    monkeypatch: pytest.MonkeyPatch,
    *,
    catalog: PluginCatalog | None = None,
) -> list[dict[str, object]]:
    """Patch the loader and return a list that records each call's kwargs."""
    calls: list[dict[str, object]] = []
    result = pbp._PluginsLoadResult(catalog=catalog, error=None, now=_NOW)

    def _fake(**kwargs: object) -> pbp._PluginsLoadResult:
        calls.append(kwargs)
        return result

    monkeypatch.setattr(pbp, "_load_plugins_catalog", _fake)
    return calls


def _render(renderable: object) -> str:
    console = Console(file=io.StringIO(), width=120, no_color=True)
    console.print(renderable)
    return console.file.getvalue()  # type: ignore[attr-defined]


def _patch_other_panes(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the sibling Config / XPrompts panes cheap and deterministic."""
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


# --- Phase 3: detail panel + refresh / offline / verbose -------------------


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


# --- Phase 4: install action ----------------------------------------------


def _ready_plan(name: str, *, git: bool) -> InstallReady:
    """A deterministic :class:`InstallReady` for *name* from index or git."""
    if git:
        requirement = Requirement.from_spec(
            f"git+https://github.com/sase-org/sase-{name}"
        )
        source = "git"
    else:
        requirement = Requirement.from_spec(f"sase-{name}")
        source = "catalog"
    spec = ResolvedSpec(requirement=requirement, display_name=name, source=source)
    argv = ["uv", "tool", "install", "--with", "sase", "--with", requirement.as_spec()]
    return InstallReady(spec=spec, argv=argv)


def _ready_preview(name: str) -> pbp._InstallPreview:
    """An install preview offering both the index and git source variants."""
    return pbp._InstallPreview(
        index_plan=_ready_plan(name, git=False),
        git_plan=_ready_plan(name, git=True),
    )


def _not_uv_tool() -> NotUvToolInstall:
    """A negative uv-tool probe result (running from a dev venv)."""
    return NotUvToolInstall(
        reason=NotUvToolReason.WRONG_PREFIX,
        sys_prefix=Path("/home/dev/project/.venv"),
        expected_sase_dir=Path("/home/dev/.local/share/uv/tools/sase"),
        receipt_path=Path("/home/dev/.local/share/uv/tools/sase/uv-receipt.toml"),
        uv_path="/usr/bin/uv",
    )


def _highlight(pane: PluginsBrowserPane, name: str) -> None:
    """Move the list highlight onto the row for *name*."""
    from textual.widgets import OptionList

    option_list = pane.query_one("#plugins-list", OptionList)
    for index in range(option_list.option_count):
        if option_list.get_option_at_index(index).id == f"plugin__{name}":
            option_list.highlighted = index
            return
    raise AssertionError(f"plugin row not found: {name}")


def _spy_notify(
    monkeypatch: pytest.MonkeyPatch, pane: PluginsBrowserPane
) -> list[tuple[str, str]]:
    """Record toasts the pane emits as ``(message, severity)`` tuples."""
    messages: list[tuple[str, str]] = []

    def _record(message: str, *, severity: str = "information") -> None:
        messages.append((message, severity))

    monkeypatch.setattr(pane, "_notify", _record)
    return messages


async def test_plugins_pane_install_opens_preview_modal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(monkeypatch, catalog=_catalog())
    monkeypatch.setattr(
        pbp, "_plan_install_preview", lambda name, *, offline: _ready_preview(name)
    )
    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        _highlight(pane, "nvim")
        await page.wait_for(lambda _s: pane._highlighted_name() == "nvim")
        pane.action_install()
        await page.expect_modal("PluginActionConfirmModal")
        modal = page.app.screen
        assert isinstance(modal, PluginActionConfirmModal)
        # Both source variants are offered; index is the default (first).
        assert [v.key for v in modal._variants] == ["index", "git"]
        preview = _render(modal._preview_renderable())
        assert "uv tool install" in preview
        assert "Installs nvim" in preview
        assert "from index" in preview


async def test_plugins_pane_install_hint_only_for_not_installed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(monkeypatch, catalog=_catalog())
    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        _highlight(pane, "nvim")
        await page.wait_for(lambda _s: pane._highlighted_name() == "nvim")
        assert "i install" in pane._hints()
        _highlight(pane, "github")  # already installed
        await page.wait_for(lambda _s: pane._highlighted_name() == "github")
        assert "i install" not in pane._hints()


async def test_plugins_pane_install_already_installed_toasts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(monkeypatch, catalog=_catalog())
    planned: list[int] = []
    monkeypatch.setattr(pbp, "_plan_install_preview", lambda *a, **k: planned.append(1))
    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        messages = _spy_notify(monkeypatch, pane)
        _highlight(pane, "github")  # installed
        pane.action_install()
        await page.pause()
        assert not planned  # short-circuited before planning
        assert messages and "already installed" in messages[0][0]


async def test_plugins_pane_install_disabled_when_not_uv_tool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(monkeypatch, catalog=_catalog())
    planned: list[int] = []
    monkeypatch.setattr(pbp, "_plan_install_preview", lambda *a, **k: planned.append(1))
    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        pane._uv_tool = _not_uv_tool()
        messages = _spy_notify(monkeypatch, pane)
        _highlight(pane, "nvim")
        pane.action_install()
        await page.pause()
        assert pane._plan_worker is None
        assert not planned
        assert messages and messages[0][1] == "warning"
        assert "uv tool install" in messages[0][0]
        # Affordances surface the disabled state.
        assert "i install" not in pane._hints()
        assert "unavailable" in pane._summary_text().plain


async def test_plugins_pane_install_not_found_toasts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(monkeypatch, catalog=_catalog())
    preview = pbp._InstallPreview(
        index_plan=InstallNotFound(query="nvim", suggestions=())
    )
    monkeypatch.setattr(pbp, "_plan_install_preview", lambda name, *, offline: preview)
    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        messages = _spy_notify(monkeypatch, pane)
        _highlight(pane, "nvim")
        pane.action_install()
        await page.wait_for(lambda _s: bool(messages))
        message, severity = messages[0]
        assert "No plugin named 'nvim'" in message
        assert severity == "error"


async def test_plugins_pane_install_confirm_executes_and_refreshes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    calls = _patch_catalog_recording(monkeypatch, catalog=_catalog())
    monkeypatch.setattr(
        pbp, "_plan_install_preview", lambda name, *, offline: _ready_preview(name)
    )
    executed: list[InstallReady] = []

    def _fake_execute(plan: InstallReady, **_kw: object) -> InstallOutcome:
        executed.append(plan)
        return InstallOutcome(
            plan=plan,
            change_set=UvChangeSet(
                changes=(
                    UvPackageChange(
                        name="sase-nvim", kind=ChangeKind.ADDED, new_version="2.0.0"
                    ),
                )
            ),
            groups=(),
            elapsed=1.5,
        )

    monkeypatch.setattr(pbp, "execute_install", _fake_execute)
    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        initial = len(calls)
        _highlight(pane, "nvim")
        await page.wait_for(lambda _s: pane._highlighted_name() == "nvim")
        pane.action_install()
        await page.expect_modal("PluginActionConfirmModal")
        modal = page.app.screen
        assert isinstance(modal, PluginActionConfirmModal)
        modal.action_confirm()  # accept the default index variant
        # The tracked task runs execute_install, then refreshes the catalog.
        await page.wait_for(lambda _s: bool(executed) and len(calls) > initial)
        assert executed[0].spec.display_name == "nvim"
        assert executed[0].spec.source == "catalog"


async def test_plugins_pane_install_git_variant_executed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(monkeypatch, catalog=_catalog())
    monkeypatch.setattr(
        pbp, "_plan_install_preview", lambda name, *, offline: _ready_preview(name)
    )
    executed: list[InstallReady] = []

    def _fake_execute(plan: InstallReady, **_kw: object) -> InstallOutcome:
        executed.append(plan)
        return InstallOutcome(
            plan=plan, change_set=UvChangeSet(), groups=(), elapsed=0.2
        )

    monkeypatch.setattr(pbp, "execute_install", _fake_execute)
    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        _highlight(pane, "nvim")
        await page.wait_for(lambda _s: pane._highlighted_name() == "nvim")
        pane.action_install()
        await page.expect_modal("PluginActionConfirmModal")
        modal = page.app.screen
        assert isinstance(modal, PluginActionConfirmModal)
        modal.action_toggle_source()  # index -> git
        modal.action_confirm()
        await page.wait_for(lambda _s: bool(executed))
        assert executed[0].spec.source == "git"


async def test_plugin_action_modal_toggle_and_confirm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    variants = [
        PluginActionVariant(
            key="index",
            label="from index",
            argv=("uv", "tool", "install", "sase-nvim"),
            summary="Installs nvim  (from catalog)",
        ),
        PluginActionVariant(
            key="git",
            label="from git",
            argv=("uv", "tool", "install", "git+https://example/sase-nvim"),
            summary="Installs nvim  (from git)",
        ),
    ]
    async with AcePage() as page:
        results: list[PluginActionConfirmResult | None] = []
        modal = PluginActionConfirmModal(
            title="Install nvim", intro="Confirm", variants=variants
        )
        page.app.push_screen(modal, results.append)
        await page.expect_modal("PluginActionConfirmModal")
        assert modal._index == 0
        modal.action_toggle_source()
        assert modal._index == 1
        modal.action_confirm()
        await page.wait_for(lambda _s: bool(results))
        assert results[0] == PluginActionConfirmResult("git")


async def test_plugin_action_modal_cancel_returns_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    variants = [
        PluginActionVariant(
            key="update",
            label="update",
            argv=("uv", "tool", "install", "sase-nvim"),
            summary="Upgrades nvim",
        )
    ]
    async with AcePage() as page:
        results: list[PluginActionConfirmResult | None] = []
        modal = PluginActionConfirmModal(
            title="Update nvim", intro="Confirm", variants=variants
        )
        page.app.push_screen(modal, results.append)
        await page.expect_modal("PluginActionConfirmModal")
        # A single variant offers no source toggle.
        assert len(modal._variants) == 1
        modal.action_cancel()
        await page.wait_for(lambda _s: bool(results))
        assert results[0] is None


# --- Phase 5: update actions (single + all) --------------------------------


def _update_ready(
    targets: tuple[str, ...], *, all_plugins: bool = False
) -> UpdateReady:
    """A deterministic :class:`UpdateReady` upgrading the given plugin(s).

    *targets* are short names; they map to ``sase-<name>`` distribution names
    just like the receipt-resolved CLI targets.
    """
    dist = tuple(f"sase-{name}" for name in targets)
    argv = ["uv", "tool", "install", "--with", "sase"]
    for name in dist:
        argv += ["--upgrade-package", name]
    return UpdateReady(argv=argv, targets=dist, all_plugins=all_plugins)


async def test_plugins_pane_update_opens_preview_modal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(monkeypatch, catalog=_catalog())
    plan = _update_ready(("github",))
    monkeypatch.setattr(
        pbp,
        "_plan_update_preview",
        lambda query, *, all_plugins, offline: pbp._UpdatePreview(plan=plan),
    )
    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        _highlight(pane, "github")  # installed, update available
        await page.wait_for(lambda _s: pane._highlighted_name() == "github")
        pane.action_update()
        await page.expect_modal("PluginActionConfirmModal")
        modal = page.app.screen
        assert isinstance(modal, PluginActionConfirmModal)
        # Update offers a single variant — no index/git source toggle.
        assert [v.key for v in modal._variants] == ["update"]
        preview = _render(modal._preview_renderable())
        assert "--upgrade-package" in preview
        assert "Upgrades sase-github" in preview
        assert "sase core stays pinned" in preview


async def test_plugins_pane_update_hint_gated_on_installed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(monkeypatch, catalog=_catalog())
    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        # Installed + update available: emphasized hint, plus update-all.
        _highlight(pane, "github")
        await page.wait_for(lambda _s: pane._highlighted_name() == "github")
        assert "u update ↑" in pane._hints()
        assert "U update-all" in pane._hints()
        # Installed but current: hint present, not emphasized.
        _highlight(pane, "telegram")
        await page.wait_for(lambda _s: pane._highlighted_name() == "telegram")
        telegram_hints = pane._hints()
        assert "u update" in telegram_hints
        assert "↑" not in telegram_hints
        # Not installed: no single-update hint (install is offered instead).
        _highlight(pane, "nvim")
        await page.wait_for(lambda _s: pane._highlighted_name() == "nvim")
        assert "u update" not in pane._hints()


async def test_plugins_pane_update_not_installed_toasts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(monkeypatch, catalog=_catalog())
    planned: list[int] = []
    monkeypatch.setattr(pbp, "_plan_update_preview", lambda *a, **k: planned.append(1))
    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        messages = _spy_notify(monkeypatch, pane)
        _highlight(pane, "nvim")  # not installed
        pane.action_update()
        await page.pause()
        assert not planned  # short-circuited before planning
        assert messages and "not installed" in messages[0][0]
        assert messages[0][1] == "warning"


async def test_plugins_pane_update_disabled_when_not_uv_tool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(monkeypatch, catalog=_catalog())
    planned: list[int] = []
    monkeypatch.setattr(pbp, "_plan_update_preview", lambda *a, **k: planned.append(1))
    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        pane._uv_tool = _not_uv_tool()
        messages = _spy_notify(monkeypatch, pane)
        _highlight(pane, "github")  # installed + update available
        pane.action_update()
        await page.pause()
        assert pane._update_plan_worker is None
        assert not planned
        assert messages and messages[0][1] == "warning"
        assert "uv tool install" in messages[0][0]
        # Update affordances are dropped from the hints.
        assert "u update" not in pane._hints()
        assert "U update-all" not in pane._hints()
        # Update-all is gated too.
        pane.action_update_all()
        await page.pause()
        assert not planned


async def test_plugins_pane_update_all_no_plugins_toasts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(monkeypatch, catalog=_catalog())
    monkeypatch.setattr(
        pbp,
        "_plan_update_preview",
        lambda query, *, all_plugins, offline: pbp._UpdatePreview(plan=NoPlugins()),
    )
    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        messages = _spy_notify(monkeypatch, pane)
        pane.action_update_all()
        await page.wait_for(lambda _s: bool(messages))
        assert "No plugins are installed" in messages[0][0]


async def test_plugins_pane_update_unknown_toasts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(monkeypatch, catalog=_catalog())
    preview = pbp._UpdatePreview(plan=UpdateUnknown(query="github", suggestions=()))
    monkeypatch.setattr(pbp, "_plan_update_preview", lambda *a, **k: preview)
    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        messages = _spy_notify(monkeypatch, pane)
        _highlight(pane, "github")  # installed → proceeds to plan
        pane.action_update()
        await page.wait_for(lambda _s: bool(messages))
        message, severity = messages[0]
        assert "No plugin named 'github'" in message
        assert severity == "error"


async def test_plugins_pane_update_confirm_executes_and_refreshes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    calls = _patch_catalog_recording(monkeypatch, catalog=_catalog())
    plan = _update_ready(("github",))
    monkeypatch.setattr(
        pbp,
        "_plan_update_preview",
        lambda query, *, all_plugins, offline: pbp._UpdatePreview(plan=plan),
    )
    executed: list[UpdateReady] = []

    def _fake_execute(plan_arg: UpdateReady, **_kw: object) -> UpdateOutcome:
        executed.append(plan_arg)
        return UpdateOutcome(
            plan=plan_arg,
            change_set=UvChangeSet(
                changes=(
                    UvPackageChange(
                        name="sase-github",
                        kind=ChangeKind.UPGRADED,
                        old_version="1.2.0",
                        new_version="1.3.0",
                    ),
                )
            ),
            elapsed=1.0,
        )

    monkeypatch.setattr(pbp, "execute_update", _fake_execute)
    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        initial = len(calls)
        _highlight(pane, "github")
        await page.wait_for(lambda _s: pane._highlighted_name() == "github")
        pane.action_update()
        await page.expect_modal("PluginActionConfirmModal")
        modal = page.app.screen
        assert isinstance(modal, PluginActionConfirmModal)
        modal.action_confirm()
        # The tracked task runs execute_update, then refreshes the catalog.
        await page.wait_for(lambda _s: bool(executed) and len(calls) > initial)
        assert executed[0].targets == ("sase-github",)
        assert not executed[0].all_plugins


async def test_plugins_pane_update_all_executes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(monkeypatch, catalog=_catalog())
    plan = _update_ready(("github", "telegram"), all_plugins=True)
    monkeypatch.setattr(
        pbp,
        "_plan_update_preview",
        lambda query, *, all_plugins, offline: pbp._UpdatePreview(plan=plan),
    )
    executed: list[UpdateReady] = []

    def _fake_execute(plan_arg: UpdateReady, **_kw: object) -> UpdateOutcome:
        executed.append(plan_arg)
        return UpdateOutcome(plan=plan_arg, change_set=UvChangeSet(), elapsed=0.3)

    monkeypatch.setattr(pbp, "execute_update", _fake_execute)
    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        pane.action_update_all()
        await page.expect_modal("PluginActionConfirmModal")
        modal = page.app.screen
        assert isinstance(modal, PluginActionConfirmModal)
        # A single variant; the preview names every installed plugin.
        assert [v.key for v in modal._variants] == ["update"]
        preview = _render(modal._preview_renderable())
        assert "every installed plugin" in preview
        modal.action_confirm()
        await page.wait_for(lambda _s: bool(executed))
        assert executed[0].all_plugins
