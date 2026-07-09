"""Tests for the ``sase plugin show`` parser, JSON payload, and rendering."""

from __future__ import annotations

import argparse
import io
import json
from typing import Any

from rich.console import Console

from sase.main.parser import create_parser
from sase.plugins.catalog import PluginCatalog, PluginCatalogEntry
from sase.plugins.cli_show import (
    SHOW_JSON_SCHEMA_VERSION,
    handle_plugin_show_command,
)
from sase.plugins.installed import InstalledInfo
from sase.plugins.latest import LatestInfo

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
    topics: tuple[str, ...] = ("sase--plugin",),
    updated_at: str = "",
    license: str = "",
    homepage: str = "",
    latest: LatestInfo | None = None,
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
        latest=latest or LatestInfo.unknown(),
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
                description="GitHub VCS and workspace support.",
                installed=True,
                version="0.4.1",
                groups=("sase_vcs", "sase_workspace"),
                latest=LatestInfo(checked=True, version="0.4.1", source="index"),
                stars=12,
                updated_at="2026-06-20",
                license="MIT",
                homepage="https://sase.dev/plugins/github",
                topics=("sase--plugin", "github", "vcs"),
            ),
            _entry(
                "telegram",
                "sase-org",
                repo="sase-telegram",
                description="Telegram chat integration",
                latest=LatestInfo(checked=True, version="0.2.0", source="index"),
            ),
            _entry(
                "acme-jira",
                "acme-corp",
                repo="acme-jira",
                description="Jira sync for SASE",
                stars=3,
            ),
        )
    )


def _show(catalog: PluginCatalog, plugin_name: str) -> tuple[int, str]:
    """Render the human view; return the exit code and captured console text."""
    args = argparse.Namespace(
        plugin_subcommand="show",
        plugin_name=plugin_name,
        json=False,
        offline=False,
        refresh=False,
    )
    console = Console(file=io.StringIO(), width=200, no_color=True)
    code = handle_plugin_show_command(
        args,
        console=console,
        load_fn=lambda *, refresh, offline: catalog,
        enrich_fn=lambda catalog, **_kwargs: catalog,
        now=1000.0,
    )
    return code, console.file.getvalue()  # type: ignore[attr-defined]


def _show_json(
    catalog: PluginCatalog, plugin_name: str, capsys: Any
) -> tuple[int, dict[str, Any]]:
    """Run the ``--json`` path; return the exit code and the parsed payload."""
    args = argparse.Namespace(
        plugin_subcommand="show",
        plugin_name=plugin_name,
        json=True,
        offline=False,
        refresh=False,
    )
    code = handle_plugin_show_command(
        args,
        load_fn=lambda *, refresh, offline: catalog,
        enrich_fn=lambda catalog, **_kwargs: catalog,
        now=1000.0,
    )
    return code, json.loads(capsys.readouterr().out)


# --------------------------------------------------------------------------- #
# Parser
# --------------------------------------------------------------------------- #


def test_show_parses_positional_and_flags() -> None:
    short = create_parser().parse_args(["plugin", "show", "github", "-j", "-o", "-r"])
    long = create_parser().parse_args(
        ["plugin", "show", "github", "--json", "--offline", "--refresh"]
    )

    for ns in (short, long):
        assert ns.command == "plugin"
        assert ns.plugin_subcommand == "show"
        assert ns.plugin_name == "github"
        assert ns.json is True
        assert ns.offline is True
        assert ns.refresh is True


def test_show_requires_plugin_name() -> None:
    import pytest

    with pytest.raises(SystemExit):
        create_parser().parse_args(["plugin", "show"])


# --------------------------------------------------------------------------- #
# Rendering — found
# --------------------------------------------------------------------------- #


def test_show_builtin_renders_official_detail() -> None:
    code, out = _show(_sample_catalog(), "github")

    assert code == 0
    assert "github · sase-org/sase-github" in out
    assert "BUILT-IN (official)" in out
    assert "GitHub VCS and workspace support." in out
    assert "Latest" in out
    assert "v0.4.1" in out
    assert "up to date" in out
    assert "sase_vcs" in out
    assert "https://github.com/sase-org/sase-github" in out
    assert "https://sase.dev/plugins/github" in out
    assert "MIT" in out
    # The community warning must NOT appear for a built-in plugin.
    assert "COMMUNITY PLUGIN" not in out


def test_show_community_leads_with_warning_panel() -> None:
    code, out = _show(_sample_catalog(), "acme-jira")

    assert code == 0
    assert "COMMUNITY PLUGIN" in out
    assert "acme-corp" in out
    assert "not the official `sase-org` org" in out
    assert "Review its source before installing" in out
    assert "COMMUNITY (third-party)" in out


def test_show_installed_marks_check_and_groups() -> None:
    code, out = _show(_sample_catalog(), "github")

    assert code == 0
    assert "✓" in out
    assert "v0.4.1" in out
    assert "sase_vcs, sase_workspace" in out


def test_show_not_installed_marks_cross_and_hint() -> None:
    code, out = _show(_sample_catalog(), "telegram")

    assert code == 0
    assert "✗" in out
    assert "not installed" in out
    assert "sase plugin install telegram" in out


def test_show_footer_has_cache_age_and_refresh_command() -> None:
    code, out = _show(_sample_catalog(), "github")

    assert code == 0
    assert "Cached" in out
    assert "sase plugin show github --refresh" in out


def test_show_warnings_surface_at_top() -> None:
    catalog = _catalog(
        (_entry("github", "sase-org", repo="sase-github"),),
        warnings=("showing stale cached plugin data: could not refresh",),
    )
    code, out = _show(catalog, "github")

    assert code == 0
    assert "could not refresh" in out


def test_show_update_available_includes_action_hint() -> None:
    catalog = _catalog(
        (
            _entry(
                "github",
                "sase-org",
                repo="sase-github",
                installed=True,
                version="0.4.1",
                latest=LatestInfo(checked=True, version="0.5.0", source="index"),
            ),
        )
    )
    code, out = _show(catalog, "github")

    assert code == 0
    assert "Latest" in out
    assert "v0.5.0" in out
    assert "↑ update available" in out
    assert "sase plugin update github" in out


def test_show_editable_install_skips_version_comparison() -> None:
    catalog = _catalog(
        (
            _entry(
                "devkit",
                "sase-org",
                repo="sase-devkit",
                installed=True,
                version="0.1.0",
                latest=LatestInfo(
                    checked=True,
                    source="editable",
                    error="non-index install",
                ),
            ),
        )
    )
    code, out = _show(catalog, "devkit")

    assert code == 0
    assert "editable" in out
    assert "dev" in out
    assert "update available" not in out


def test_show_editable_update_available_uses_dev_versions_and_sase_update() -> None:
    catalog = _catalog(
        (
            _entry(
                "devkit",
                "sase-org",
                repo="sase-devkit",
                installed=True,
                version="0.1.0",
                latest=LatestInfo(
                    checked=True,
                    version="0.1.0+3.gdef456abc",
                    source="editable",
                    install_type="editable",
                    current_version="0.1.0+1.gabc123def",
                    update_available=True,
                    state="update_available",
                    reason="behind upstream by 2 commit(s)",
                ),
            ),
        )
    )
    code, out = _show(catalog, "devkit")

    assert code == 0
    assert "v0.1.0+1.gabc123def" in out
    assert "v0.1.0+3.gdef456abc" in out
    assert "dev update available" in out
    assert "sase update" in out


def test_show_offline_unknown_latest_has_hint() -> None:
    catalog = _catalog(
        (
            _entry(
                "github",
                "sase-org",
                repo="sase-github",
                installed=True,
                version="0.4.1",
                latest=LatestInfo(checked=True, source="unknown", error="offline"),
            ),
        )
    )
    code, out = _show(catalog, "github")

    assert code == 0
    assert "unknown" in out
    assert "without `--offline`" in out


# --------------------------------------------------------------------------- #
# Name matching across short / repo / full forms
# --------------------------------------------------------------------------- #


def test_show_matches_short_repo_and_full_name(capsys: Any) -> None:
    catalog = _sample_catalog()

    for query in ("github", "sase-github", "sase-org/sase-github", "GITHUB"):
        code, payload = _show_json(catalog, query, capsys)
        assert code == 0
        assert payload["plugin"]["name"] == "github"


# --------------------------------------------------------------------------- #
# Not found
# --------------------------------------------------------------------------- #


def test_show_not_found_returns_one_with_suggestions() -> None:
    code, out = _show(_sample_catalog(), "githubb")

    assert code == 1
    assert "No plugin named 'githubb'" in out
    assert "Did you mean" in out
    assert "github" in out


def test_show_not_found_without_suggestions_points_to_list() -> None:
    code, out = _show(_sample_catalog(), "zzzzzzzz")

    assert code == 1
    assert "No plugin named 'zzzzzzzz'" in out
    assert "sase plugin list" in out


# --------------------------------------------------------------------------- #
# JSON payload
# --------------------------------------------------------------------------- #


def test_show_json_shape_is_stable(capsys: Any) -> None:
    code, payload = _show_json(_sample_catalog(), "github", capsys)

    assert code == 0
    assert payload["schema_version"] == SHOW_JSON_SCHEMA_VERSION
    assert payload["found"] is True
    assert payload["query"] == "github"
    assert payload["from_cache"] is True
    assert payload["stale"] is False
    assert payload["cache_age_seconds"] == 0.0

    plugin = payload["plugin"]
    assert plugin["name"] == "github"
    assert plugin["kind"] == "builtin"
    assert plugin["full_name"] == "sase-org/sase-github"
    assert plugin["install_type"] is None
    assert plugin["current_version"] == "0.4.1"
    assert plugin["installed"] == {
        "installed": True,
        "version": "0.4.1",
        "entry_point_groups": ["sase_vcs", "sase_workspace"],
    }
    assert plugin["latest"] == {
        "checked": True,
        "version": "0.4.1",
        "source": "index",
        "update_available": False,
        "state": None,
        "reason": None,
        "error": None,
    }


def test_show_json_community_kind(capsys: Any) -> None:
    code, payload = _show_json(_sample_catalog(), "acme-jira", capsys)

    assert code == 0
    assert payload["plugin"]["kind"] == "community"


def test_show_json_not_found_payload(capsys: Any) -> None:
    args = argparse.Namespace(
        plugin_subcommand="show",
        plugin_name="githubb",
        json=True,
        offline=False,
        refresh=False,
    )
    code = handle_plugin_show_command(
        args,
        load_fn=lambda *, refresh, offline: _sample_catalog(),
        enrich_fn=lambda catalog, **_kwargs: catalog,
        now=1000.0,
    )

    assert code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["found"] is False
    assert payload["plugin"] is None
    assert payload["query"] == "githubb"
    assert "github" in payload["suggestions"]


# --------------------------------------------------------------------------- #
# refresh threading + loader error
# --------------------------------------------------------------------------- #


def test_show_refresh_flag_is_threaded_to_loader() -> None:
    seen: list[bool] = []

    def _load(*, refresh: bool, offline: bool) -> PluginCatalog:
        seen.append(refresh)
        return _sample_catalog()

    args = argparse.Namespace(
        plugin_subcommand="show",
        plugin_name="github",
        json=True,
        offline=False,
        refresh=True,
    )
    handle_plugin_show_command(
        args,
        load_fn=_load,
        enrich_fn=lambda catalog, **_kwargs: catalog,
        now=1000.0,
    )

    assert seen == [True]


def test_show_loader_error_returns_exit_code_one(capsys: Any) -> None:
    from sase.plugins.github_source import GhNotFoundError

    def _load(*, refresh: bool, offline: bool) -> PluginCatalog:
        raise GhNotFoundError()

    args = argparse.Namespace(
        plugin_subcommand="show",
        plugin_name="github",
        json=False,
        offline=False,
        refresh=False,
    )
    code = handle_plugin_show_command(args, load_fn=_load, now=1000.0)

    assert code == 1
    assert "gh" in capsys.readouterr().err.lower()


def test_show_offline_flag_is_threaded_to_loader_and_enricher() -> None:
    seen_load: list[tuple[bool, bool]] = []
    seen_enrich: list[tuple[bool, bool]] = []

    def _load(*, refresh: bool, offline: bool) -> PluginCatalog:
        seen_load.append((refresh, offline))
        return _sample_catalog()

    def _enrich(
        catalog: PluginCatalog, *, offline: bool, refresh: bool
    ) -> PluginCatalog:
        seen_enrich.append((refresh, offline))
        return catalog

    args = argparse.Namespace(
        plugin_subcommand="show",
        plugin_name="github",
        json=True,
        offline=True,
        refresh=False,
    )
    handle_plugin_show_command(args, load_fn=_load, enrich_fn=_enrich, now=1000.0)

    assert seen_load == [(False, True)]
    assert seen_enrich == [(False, True)]
