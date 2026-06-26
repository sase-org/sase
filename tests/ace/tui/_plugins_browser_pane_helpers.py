"""Shared fixtures for Config Center Plugins tab tests."""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from rich.console import Console
from textual.widgets import OptionList

from sase.ace.testing import AcePage
from sase.ace.tui.modals import config_pane as cp
from sase.ace.tui.modals import plugins_browser_pane as pbp
from sase.ace.tui.modals.config_center_modal import ConfigCenterModal
from sase.ace.tui.modals.plugins_browser_pane import PluginsBrowserPane
from sase.plugins.catalog import PluginCatalog, PluginCatalogEntry
from sase.plugins.installed import InstalledInfo
from sase.plugins.latest import LatestInfo
from sase.plugins.operations import InstallReady, ResolvedSpec, UpdateReady
from sase.uv_tool.detect import NotUvToolInstall, NotUvToolReason
from sase.uv_tool.receipt import Requirement

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
    """Keep the sibling Config / Projects / XPrompts panes cheap & deterministic."""
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
    monkeypatch.setattr(
        "sase.ace.tui.modals.projects_pane.list_project_records",
        lambda *_a, **_kw: [],
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
    option_list = pane.query_one("#plugins-list", OptionList)
    labels: list[str] = []
    for index in range(option_list.option_count):
        opt = option_list.get_option_at_index(index)
        prompt = opt.prompt
        labels.append(prompt.plain if hasattr(prompt, "plain") else str(prompt))
    return labels


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
