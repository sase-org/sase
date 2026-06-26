"""Tests for the promoted, console-free plugin Rich renderables.

Phase 1 promotes the catalog/detail builders to public functions that return a
``RenderableType`` and never touch a console, so the TUI Updates tab can display
the exact same renderables ``sase plugin list`` / ``show`` print. These tests
pin that contract: the builders return Rich renderables, render to text without
a real terminal, and surface the key fields and the community warning.
"""

from __future__ import annotations

import io

from rich.console import Console

from sase.plugins.catalog import PluginCatalog, PluginCatalogEntry
from sase.plugins.installed import InstalledInfo
from sase.plugins.render import (
    build_catalog_list_panel,
    build_community_warning_panel,
    build_detail_panel,
)


def _entry(
    name: str,
    owner: str = "sase-org",
    *,
    repo: str | None = None,
    installed: bool = False,
) -> PluginCatalogEntry:
    repo = repo if repo is not None else f"sase-{name}"
    return PluginCatalogEntry(
        name=name,
        repo=repo,
        full_name=f"{owner}/{repo}",
        owner=owner,
        description=f"{name} plugin",
        url=f"https://github.com/{owner}/{repo}",
        homepage="",
        topics=("sase-plugin",),
        stars=7,
        archived=False,
        license="MIT",
        updated_at="2026-01-01",
        installed=InstalledInfo(installed=installed, version="1.0.0"),
    )


def _catalog(*entries: PluginCatalogEntry) -> PluginCatalog:
    return PluginCatalog(
        fetched_at=1000.0,
        entries=entries or (_entry("github"), _entry("acme", "acme", repo="acme-x")),
        from_cache=True,
        stale=False,
    )


def _render(renderable: object) -> str:
    console = Console(file=io.StringIO(), width=200, no_color=True)
    console.print(renderable)
    return console.file.getvalue()  # type: ignore[attr-defined]


def test_build_detail_panel_renders_without_printing() -> None:
    entry = _entry("github", installed=True)
    panel = build_detail_panel(entry)
    # Builder is console-free: it returns a renderable, prints nothing itself.
    text = _render(panel)
    assert "github" in text
    assert "sase-org/sase-github" in text
    assert "BUILT-IN" in text


def test_build_community_warning_panel_leads_with_warning() -> None:
    entry = _entry("acme", "acme-corp", repo="acme-x")
    text = _render(build_community_warning_panel(entry))
    assert "COMMUNITY" in text
    assert "acme-corp" in text


def test_build_catalog_list_panel_groups_builtin_and_community() -> None:
    catalog = _catalog()
    text = _render(build_catalog_list_panel(catalog, verbose=True, now=2000.0))
    assert "BUILT-IN" in text
    assert "COMMUNITY" in text
    assert "github" in text
