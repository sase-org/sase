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
from sase.plugins.github_source import GH_SEARCH_QUERY
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
                description="GitHub VCS & PR workflows",
                installed=True,
                version="0.4.1",
                groups=("sase_vcs", "sase_workspace"),
                latest=LatestInfo(checked=True, version="0.4.1", source="index"),
                stars=12,
                updated_at="2026-06-20",
                license="MIT",
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
            ),
        )
    )


def _render(catalog: PluginCatalog, *, verbose: bool = False) -> str:
    args = argparse.Namespace(
        plugin_subcommand="list",
        json=False,
        offline=False,
        refresh=False,
        verbose=verbose,
    )
    console = Console(file=io.StringIO(), width=200, no_color=True)
    code = handle_plugin_list_command(
        args,
        console=console,
        load_fn=lambda *, refresh, offline: catalog,
        enrich_fn=lambda catalog, **_kwargs: catalog,
        now=1000.0,
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
    assert ns.offline is False
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
    short = create_parser().parse_args(["plugin", "list", "-j", "-o", "-r", "-v", "-A"])
    long = create_parser().parse_args(
        [
            "plugin",
            "list",
            "--json",
            "--offline",
            "--refresh",
            "--verbose",
            "--all-latest",
        ]
    )

    for ns in (short, long):
        assert ns.plugin_subcommand == "list"
        assert ns.json is True
        assert ns.offline is True
        assert ns.refresh is True
        assert ns.verbose is True
        assert ns.all_latest is True


def test_list_all_latest_defaults_off() -> None:
    ns = create_parser().parse_args(["plugin", "list"])

    assert ns.all_latest is False


# --------------------------------------------------------------------------- #
# JSON payload
# --------------------------------------------------------------------------- #


def test_list_json_schema_version_is_pinned_to_dev_schema() -> None:
    assert LIST_JSON_SCHEMA_VERSION == 3


def test_json_payload_shape_is_stable() -> None:
    payload = _build_list_json(_sample_catalog(), now=1000.0 + 7200)

    assert payload["schema_version"] == LIST_JSON_SCHEMA_VERSION
    assert payload["query"] == GH_SEARCH_QUERY
    assert payload["from_cache"] is True
    assert payload["stale"] is False
    assert payload["cache_age_seconds"] == 7200.0
    assert payload["counts"] == {
        "builtin": 2,
        "community": 1,
        "installed": 1,
        "total": 3,
        "updates_available": 0,
    }

    github = next(e for e in payload["entries"] if e["name"] == "github")
    assert github["kind"] == "builtin"
    assert github["full_name"] == "sase-org/sase-github"
    assert github["install_type"] is None
    assert github["current_version"] == "0.4.1"
    assert github["installed"] == {
        "installed": True,
        "version": "0.4.1",
        "entry_point_groups": ["sase_vcs", "sase_workspace"],
    }
    assert github["latest"] == {
        "checked": True,
        "version": "0.4.1",
        "source": "index",
        "update_available": False,
        "state": None,
        "reason": None,
        "error": None,
    }

    jira = next(e for e in payload["entries"] if e["name"] == "acme-jira")
    assert jira["kind"] == "community"
    assert jira["installed"]["installed"] is False


def test_json_payload_includes_editable_dev_update_fields() -> None:
    catalog = _catalog(
        (
            _entry(
                "github",
                "sase-org",
                repo="sase-github",
                installed=True,
                version="0.4.1+1.gaaaaaaaaa",
                latest=LatestInfo(
                    checked=True,
                    version="0.4.1+2.gbbbbbbbbb",
                    source="editable",
                    install_type="editable",
                    current_version="0.4.1+1.gaaaaaaaaa",
                    update_available=True,
                    state="update_available",
                    reason="behind upstream by 1 commit(s)",
                ),
            ),
        )
    )

    payload = _build_list_json(catalog, now=1000.0)

    assert payload["schema_version"] == 3
    assert payload["counts"]["updates_available"] == 1
    entry = payload["entries"][0]
    assert entry["install_type"] == "editable"
    assert entry["current_version"] == "0.4.1+1.gaaaaaaaaa"
    assert entry["latest"] == {
        "checked": True,
        "version": "0.4.1+2.gbbbbbbbbb",
        "source": "editable",
        "update_available": True,
        "state": "update_available",
        "reason": "behind upstream by 1 commit(s)",
        "error": None,
    }


def test_json_output_path_is_valid_json(capsys: Any) -> None:
    args = argparse.Namespace(
        plugin_subcommand="list",
        json=True,
        offline=False,
        refresh=False,
        verbose=False,
    )
    code = handle_plugin_list_command(
        args,
        load_fn=lambda *, refresh, offline: _sample_catalog(),
        enrich_fn=lambda catalog, **_kwargs: catalog,
        now=1000.0,
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
    assert "latest v0.2.0" in out
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
        plugin_subcommand="list",
        json=False,
        offline=False,
        refresh=False,
        verbose=False,
    )
    console = Console(file=io.StringIO(), width=200, no_color=True)
    handle_plugin_list_command(
        args,
        console=console,
        load_fn=lambda *, refresh, offline: catalog,
        enrich_fn=lambda catalog, **_kwargs: catalog,
        now=1000.0,
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
                topics=("sase--plugin", "vcs"),
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


def test_render_marks_update_available_with_transition_and_cta() -> None:
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
    out = _render(catalog)

    assert "v0.4.1 → v0.5.0" in out
    assert "↑" in out
    assert "1 update available" in out
    assert "sase plugin update --all" in out


def test_render_installed_editable_uses_source_label() -> None:
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
    out = _render(catalog)

    assert "dev" in out
    assert "sase plugin update --all" not in out


def test_render_editable_update_available_uses_dev_versions_and_sase_update() -> None:
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
    out = _render(catalog)

    assert "v0.1.0+1.gabc123def → v0.1.0+3.gdef456abc" in out
    assert "dev" in out
    assert "↑" in out
    assert "sase update" in out
    assert "sase plugin update --all" not in out


# --------------------------------------------------------------------------- #
# refresh threading
# --------------------------------------------------------------------------- #


def test_refresh_flag_is_threaded_to_loader() -> None:
    seen: list[bool] = []

    def _load(*, refresh: bool, offline: bool) -> PluginCatalog:
        seen.append(refresh)
        return _sample_catalog()

    args = argparse.Namespace(
        plugin_subcommand="list",
        json=True,
        offline=False,
        refresh=True,
        verbose=False,
    )
    handle_plugin_list_command(
        args,
        load_fn=_load,
        enrich_fn=lambda catalog, **_kwargs: catalog,
        now=1000.0,
    )

    assert seen == [True]


def test_no_refresh_flag_passes_false_to_loader() -> None:
    seen: list[bool] = []

    def _load(*, refresh: bool, offline: bool) -> PluginCatalog:
        seen.append(refresh)
        return _sample_catalog()

    args = argparse.Namespace(
        plugin_subcommand="list",
        json=True,
        offline=False,
        refresh=False,
        verbose=False,
    )
    handle_plugin_list_command(
        args,
        load_fn=_load,
        enrich_fn=lambda catalog, **_kwargs: catalog,
        now=1000.0,
    )

    assert seen == [False]


def test_loader_error_returns_exit_code_one(capsys: Any) -> None:
    from sase.plugins.github_source import GhNotFoundError

    def _load(*, refresh: bool, offline: bool) -> PluginCatalog:
        raise GhNotFoundError()

    args = argparse.Namespace(
        plugin_subcommand="list",
        json=False,
        offline=False,
        refresh=False,
        verbose=False,
    )
    code = handle_plugin_list_command(args, load_fn=_load, now=1000.0)

    assert code == 1
    assert "gh" in capsys.readouterr().err.lower()


def test_offline_flag_is_threaded_to_loader_and_enricher() -> None:
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
        plugin_subcommand="list",
        json=True,
        offline=True,
        refresh=False,
        verbose=False,
    )
    handle_plugin_list_command(args, load_fn=_load, enrich_fn=_enrich, now=1000.0)

    assert seen_load == [(False, True)]
    assert seen_enrich == [(False, True)]


def test_all_latest_flag_is_threaded_to_enricher() -> None:
    seen_scope: list[str | None] = []

    def _enrich(
        catalog: PluginCatalog,
        *,
        offline: bool,
        refresh: bool,
        scope: str | None = None,
    ) -> PluginCatalog:
        seen_scope.append(scope)
        return catalog

    args = argparse.Namespace(
        plugin_subcommand="list",
        json=True,
        offline=False,
        refresh=False,
        verbose=False,
        all_latest=True,
    )
    handle_plugin_list_command(
        args,
        load_fn=lambda *, refresh, offline: _sample_catalog(),
        enrich_fn=_enrich,
        now=1000.0,
    )

    assert seen_scope == ["all"]


def test_list_default_does_not_force_all_scope() -> None:
    seen_scope: list[str | None] = []

    def _enrich(
        catalog: PluginCatalog,
        *,
        offline: bool,
        refresh: bool,
        scope: str | None = None,
    ) -> PluginCatalog:
        seen_scope.append(scope)
        return catalog

    args = argparse.Namespace(
        plugin_subcommand="list",
        json=True,
        offline=False,
        refresh=False,
        verbose=False,
        all_latest=False,
    )
    handle_plugin_list_command(
        args,
        load_fn=lambda *, refresh, offline: _sample_catalog(),
        enrich_fn=_enrich,
        now=1000.0,
    )

    assert seen_scope == [None]
