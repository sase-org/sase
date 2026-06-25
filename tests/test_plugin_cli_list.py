"""Tests for the ``sase plugin list`` parser, JSON payload, and rendering."""

from __future__ import annotations

import argparse
import io
import json
from typing import Any

from rich.console import Console

from sase.main.parser import create_parser, default_list_delegation_notice
from sase.plugins.catalog import PluginCatalog, PluginCatalogEntry
from sase.plugins.cli_list import (
    LIST_JSON_SCHEMA_VERSION,
    _build_list_json,
    handle_plugin_list_command,
)
from sase.plugins.installed import InstalledInfo

# --------------------------------------------------------------------------- #
# Fixtures / builders
# --------------------------------------------------------------------------- #


def _entry(
    name: str,
    owner: str,
    *,
    repo: str | None = None,
    description: str = "",
    installed: bool = False,
    version: str | None = None,
    groups: tuple[str, ...] = (),
    stars: int = 0,
    archived: bool = False,
    topics: tuple[str, ...] = ("sase-plugin",),
    updated_at: str = "",
    license: str = "",
    homepage: str = "",
) -> PluginCatalogEntry:
    repo = repo if repo is not None else f"sase-{name}"
    return PluginCatalogEntry(
        name=name,
        repo=repo,
        full_name=f"{owner}/{repo}",
        owner=owner,
        description=description,
        url=f"https://github.com/{owner}/{repo}",
        homepage=homepage,
        topics=topics,
        stars=stars,
        archived=archived,
        license=license,
        updated_at=updated_at,
        installed=InstalledInfo(
            installed=installed, version=version, entry_point_groups=groups
        ),
    )


def _catalog(
    entries: tuple[PluginCatalogEntry, ...],
    *,
    fetched_at: float = 1000.0,
    from_cache: bool = True,
    stale: bool = False,
    warnings: tuple[str, ...] = (),
) -> PluginCatalog:
    return PluginCatalog(
        fetched_at=fetched_at,
        entries=entries,
        from_cache=from_cache,
        stale=stale,
        warnings=warnings,
    )


def _sample_catalog() -> PluginCatalog:
    return _catalog(
        (
            _entry(
                "github",
                "sase-org",
                repo="sase-github",
                description="GitHub VCS & PR workflows",
                installed=True,
                version="0.4.1",
                groups=("sase_vcs", "sase_workspace"),
                stars=12,
                updated_at="2026-06-20",
                license="MIT",
            ),
            _entry(
                "telegram",
                "sase-org",
                repo="sase-telegram",
                description="Telegram chat integration",
            ),
            _entry(
                "acme-jira",
                "acme-corp",
                repo="acme-jira",
                description="Jira sync for SASE",
            ),
        )
    )


def _render(catalog: PluginCatalog, *, verbose: bool = False) -> str:
    args = argparse.Namespace(
        plugin_subcommand="list", json=False, refresh=False, verbose=verbose
    )
    console = Console(file=io.StringIO(), width=200, no_color=True)
    code = handle_plugin_list_command(
        args, console=console, load_fn=lambda *, refresh: catalog, now=1000.0
    )
    assert code == 0
    return console.file.getvalue()  # type: ignore[attr-defined]


# --------------------------------------------------------------------------- #
# Parser
# --------------------------------------------------------------------------- #


def test_bare_plugin_defaults_to_list() -> None:
    ns = create_parser().parse_args(["plugin"])

    assert ns.command == "plugin"
    assert ns.plugin_subcommand == "list"
    assert ns.json is False
    assert ns.refresh is False
    assert ns.verbose is False


def test_bare_plugin_triggers_delegation_notice() -> None:
    ns = create_parser().parse_args(["plugin"])

    notice = default_list_delegation_notice(ns)
    assert notice == (
        "No subcommand provided for 'sase plugin'; delegating to 'sase plugin list'."
    )


def test_explicit_list_has_no_delegation_notice() -> None:
    ns = create_parser().parse_args(["plugin", "list"])

    assert ns.plugin_subcommand == "list"
    assert default_list_delegation_notice(ns) is None


def test_list_accepts_each_flag() -> None:
    short = create_parser().parse_args(["plugin", "list", "-j", "-r", "-v"])
    long = create_parser().parse_args(
        ["plugin", "list", "--json", "--refresh", "--verbose"]
    )

    for ns in (short, long):
        assert ns.plugin_subcommand == "list"
        assert ns.json is True
        assert ns.refresh is True
        assert ns.verbose is True


# --------------------------------------------------------------------------- #
# JSON payload
# --------------------------------------------------------------------------- #


def test_json_payload_shape_is_stable() -> None:
    payload = _build_list_json(_sample_catalog(), now=1000.0 + 7200)

    assert payload["schema_version"] == LIST_JSON_SCHEMA_VERSION
    assert payload["query"] == "topic:sase-plugin"
    assert payload["from_cache"] is True
    assert payload["stale"] is False
    assert payload["cache_age_seconds"] == 7200.0
    assert payload["counts"] == {
        "builtin": 2,
        "community": 1,
        "installed": 1,
        "total": 3,
    }

    github = next(e for e in payload["entries"] if e["name"] == "github")
    assert github["kind"] == "builtin"
    assert github["full_name"] == "sase-org/sase-github"
    assert github["installed"] == {
        "installed": True,
        "version": "0.4.1",
        "entry_point_groups": ["sase_vcs", "sase_workspace"],
    }

    jira = next(e for e in payload["entries"] if e["name"] == "acme-jira")
    assert jira["kind"] == "community"
    assert jira["installed"]["installed"] is False


def test_json_output_path_is_valid_json(capsys: Any) -> None:
    args = argparse.Namespace(
        plugin_subcommand="list", json=True, refresh=False, verbose=False
    )
    code = handle_plugin_list_command(
        args, load_fn=lambda *, refresh: _sample_catalog(), now=1000.0
    )

    assert code == 0
    parsed = json.loads(capsys.readouterr().out)
    assert parsed["counts"]["total"] == 3


# --------------------------------------------------------------------------- #
# Rendering
# --------------------------------------------------------------------------- #


def test_render_has_both_section_labels_and_community_warning() -> None:
    out = _render(_sample_catalog())

    assert "BUILT-IN" in out
    assert "COMMUNITY" in out
    assert "third-party" in out
    assert "review before installing" in out


def test_render_marks_installed_and_available() -> None:
    out = _render(_sample_catalog())

    assert "●" in out  # installed glyph
    assert "○" in out  # available glyph
    assert "v0.4.1" in out
    assert "2 built-in" in out
    assert "1 community" in out
    assert "1 installed" in out


def test_render_footer_shows_cache_age_and_refresh_command() -> None:
    out = _render(_sample_catalog())

    assert "Cached" in out
    assert "sase plugin list --refresh" in out


def test_render_stale_cache_warns_loudly() -> None:
    catalog = _catalog(
        (_entry("github", "sase-org", repo="sase-github"),),
        stale=True,
    )
    args = argparse.Namespace(
        plugin_subcommand="list", json=False, refresh=False, verbose=False
    )
    console = Console(file=io.StringIO(), width=200, no_color=True)
    handle_plugin_list_command(
        args, console=console, load_fn=lambda *, refresh: catalog, now=1000.0
    )
    out = console.file.getvalue()  # type: ignore[attr-defined]

    assert "stale" in out.lower()


def test_render_verbose_adds_stars_and_topics() -> None:
    catalog = _catalog(
        (
            _entry(
                "github",
                "sase-org",
                repo="sase-github",
                stars=12,
                topics=("sase-plugin", "vcs"),
            ),
        )
    )
    out = _render(catalog, verbose=True)

    assert "★ 12" in out
    assert "topics:" in out
    assert "vcs" in out


def test_render_empty_catalog_says_none_found() -> None:
    out = _render(_catalog(()))

    assert "No SASE plugins found" in out


def test_render_warnings_surface_at_top() -> None:
    catalog = _catalog(
        (_entry("github", "sase-org", repo="sase-github"),),
        warnings=("showing stale cached plugin data: could not refresh",),
    )
    out = _render(catalog)

    assert "could not refresh" in out


# --------------------------------------------------------------------------- #
# refresh threading
# --------------------------------------------------------------------------- #


def test_refresh_flag_is_threaded_to_loader() -> None:
    seen: list[bool] = []

    def _load(*, refresh: bool) -> PluginCatalog:
        seen.append(refresh)
        return _sample_catalog()

    args = argparse.Namespace(
        plugin_subcommand="list", json=True, refresh=True, verbose=False
    )
    handle_plugin_list_command(args, load_fn=_load, now=1000.0)

    assert seen == [True]


def test_no_refresh_flag_passes_false_to_loader() -> None:
    seen: list[bool] = []

    def _load(*, refresh: bool) -> PluginCatalog:
        seen.append(refresh)
        return _sample_catalog()

    args = argparse.Namespace(
        plugin_subcommand="list", json=True, refresh=False, verbose=False
    )
    handle_plugin_list_command(args, load_fn=_load, now=1000.0)

    assert seen == [False]


def test_loader_error_returns_exit_code_one(capsys: Any) -> None:
    from sase.plugins.github_source import GhNotFoundError

    def _load(*, refresh: bool) -> PluginCatalog:
        raise GhNotFoundError()

    args = argparse.Namespace(
        plugin_subcommand="list", json=False, refresh=False, verbose=False
    )
    code = handle_plugin_list_command(args, load_fn=_load, now=1000.0)

    assert code == 1
    assert "gh" in capsys.readouterr().err.lower()
