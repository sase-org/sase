"""Pre-install command preview (phase sase-1if.6).

Covers reading an uninstalled plugin's declared ``sase_commands`` from its
upstream ``pyproject.toml`` with a cache, exposing the preview in plugin JSON
and the install dry run, and flagging collisions before install. Every test
uses a fake ``gh`` runner or a seeded cache: no test touches the network.
"""

from __future__ import annotations

import argparse
import io
import json
from pathlib import Path
from typing import Any

from rich.console import Console

import pytest

from sase.plugins.catalog import PluginCatalog, PluginCatalogEntry
from sase.plugins.cli_install import handle_plugin_install_command
from sase.plugins.cli_list import _build_list_json
from sase.plugins.cli_show import _build_show_json
from sase.plugins.declared_commands import (
    DeclaredCommands,
    attach_declared_previews,
    declared_commands_json,
    declared_problems,
    _fetch_upstream_pyproject,
    _get_declared_commands,
    get_declared_commands_for_entry,
    _parse_declared_commands,
    _read_declared_cache,
    _write_declared_cache,
)
from sase.plugins.installed import InstalledInfo
from sase.plugins.json_payload import plugin_entry_json
from sase.plugins.latest import LatestInfo
from sase.plugins.pypi_source import ProjectAvailability
from sase.uv_tool.detect import UvToolInstall


def _entry(
    name: str,
    *,
    owner: str = "sase-org",
    installed: bool = False,
    updated_at: str = "2026-10-01T00:00:00Z",
) -> PluginCatalogEntry:
    repo = f"sase-{name}"
    return PluginCatalogEntry(
        name=name,
        repo=repo,
        full_name=f"{owner}/{repo}",
        owner=owner,
        description="desc",
        url=f"https://github.com/{owner}/{repo}",
        homepage="",
        topics=("sase--plugin",),
        stars=0,
        archived=False,
        license="MIT",
        updated_at=updated_at,
        installed=InstalledInfo(installed=installed),
        latest=LatestInfo.unknown(),
    )


def _catalog(*entries: PluginCatalogEntry) -> PluginCatalog:
    return PluginCatalog(
        fetched_at=1000.0,
        entries=entries or (_entry("listen"),),
        from_cache=True,
        stale=False,
    )


_LISTEN_TOML = """\
[project]
name = "sase-listen"
version = "0.1.2"

[project.entry-points.sase_commands]
listen = "sase_listen.sase_command:main"
"""

_PLAIN_TOML = """\
[project]
name = "sase-jira"
version = "0.2.0"
"""

_DYNAMIC_TOML = """\
[project]
name = "sase-dyn"
dynamic = ["entry-points"]
"""


def _fetch(toml_by_full_name: dict[str, str | None]) -> Any:
    """A fake ``fetch_fn``: canned pyproject text per full name (None = miss)."""

    def _run(full_name: str) -> str | None:
        return toml_by_full_name.get(full_name)

    return _run


def _isolated_cache(
    seed: dict[str, Any] | None = None,
) -> tuple[Any, Any]:
    """In-memory declared-cache read/write fakes."""
    from sase.plugins.declared_commands import _CachedDeclared

    store: dict[str, Any] = {}
    if seed is not None:
        for key, row in seed.items():
            store[key] = _CachedDeclared(
                status=row["status"],
                names=tuple(row.get("names", ())),
                source=row.get("source"),
                updated_at=row.get("updated_at", ""),
                fetched_at=row.get("fetched_at", 1000.0),
            )

    def _read() -> dict[str, Any]:
        return dict(store)

    def _write(entries: dict[str, Any]) -> None:
        store.clear()
        store.update(entries)

    return _read, _write


# --------------------------------------------------------------------------- #
# Parsing
# --------------------------------------------------------------------------- #


def test_parse_declared_names() -> None:
    declared = _parse_declared_commands(_LISTEN_TOML)
    assert declared.status == "declared"
    assert declared.names == ("listen",)
    assert declared.source == "pyproject:project.entry-points.sase_commands"


def test_parse_no_entry_points_is_none() -> None:
    declared = _parse_declared_commands(_PLAIN_TOML)
    assert declared == DeclaredCommands(status="none", names=(), source=None)


def test_parse_missing_project_table_is_none() -> None:
    declared = _parse_declared_commands("[tool.ruff]\nline-length = 100\n")
    assert declared.status == "none"


def test_parse_dynamic_entry_points_raises() -> None:
    with pytest.raises(ValueError, match="dynamic entry-points"):
        _parse_declared_commands(_DYNAMIC_TOML)


def test_parse_garbage_raises() -> None:
    with pytest.raises(ValueError, match="cannot parse"):
        _parse_declared_commands("not [ valid = toml {{{")


# --------------------------------------------------------------------------- #
# Fake gh runner
# --------------------------------------------------------------------------- #


def _gh_runner(stdout: str = "", *, returncode: int = 0) -> Any:
    """A fake ``gh`` subprocess runner returning canned stdout."""

    def _run(args: Any, **kwargs: Any) -> Any:
        assert list(args)[1:3] == ["api", "-H"]
        assert "Accept: application/vnd.github.raw" in list(args)
        assert any(str(part).startswith("repos/sase-org/sase-listen/") for part in args)
        import subprocess

        return subprocess.CompletedProcess(
            list(args), returncode, stdout=stdout, stderr=""
        )

    return _run


def test_fetch_upstream_pyproject_uses_raw_media_type() -> None:
    text = _fetch_upstream_pyproject(
        "sase-org/sase-listen", run_fn=_gh_runner(_LISTEN_TOML)
    )
    assert text == _LISTEN_TOML


def test_fetch_upstream_pyproject_failure_is_none() -> None:
    assert (
        _fetch_upstream_pyproject(
            "sase-org/sase-listen", run_fn=_gh_runner("", returncode=1)
        )
        is None
    )

    def _missing(*args: Any, **kwargs: Any) -> Any:
        raise FileNotFoundError("no such file or directory: 'gh'")

    assert _fetch_upstream_pyproject("sase-org/sase-listen", run_fn=_missing) is None


def test_end_to_end_declared_through_fake_gh() -> None:
    read_fn, write_fn = _isolated_cache()
    declared = _get_declared_commands(
        "sase-org/sase-listen",
        updated_at="2026-10-01T00:00:00Z",
        fetch_fn=lambda full_name: _fetch_upstream_pyproject(
            full_name, run_fn=_gh_runner(_LISTEN_TOML)
        ),
        read_cache_fn=read_fn,
        write_cache_fn=write_fn,
        clock=lambda: 2000.0,
    )
    assert declared.status == "declared"
    assert declared.names == ("listen",)


# --------------------------------------------------------------------------- #
# Fetch + cache
# --------------------------------------------------------------------------- #


def test_get_declared_commands_declared_and_cached() -> None:
    read_fn, write_fn = _isolated_cache()
    fetch = _fetch({"sase-org/sase-listen": _LISTEN_TOML})
    first = _get_declared_commands(
        "sase-org/sase-listen",
        updated_at="2026-10-01T00:00:00Z",
        fetch_fn=fetch,
        read_cache_fn=read_fn,
        write_cache_fn=write_fn,
        clock=lambda: 2000.0,
    )
    assert first.status == "declared"
    assert first.names == ("listen",)

    seen: list[str] = []

    def _boom(_full_name: str) -> str | None:
        seen.append(_full_name)
        raise AssertionError("cache hit must not refetch")

    second = _get_declared_commands(
        "sase-org/sase-listen",
        updated_at="2026-10-01T00:00:00Z",
        fetch_fn=_boom,
        read_cache_fn=read_fn,
        write_cache_fn=write_fn,
        clock=lambda: 2000.0,
    )
    assert second == first
    assert seen == []


def test_get_declared_commands_missing_file_is_unknown() -> None:
    read_fn, write_fn = _isolated_cache()
    declared = _get_declared_commands(
        "sase-org/sase-gone",
        fetch_fn=_fetch({}),
        read_cache_fn=read_fn,
        write_cache_fn=write_fn,
    )
    assert declared == DeclaredCommands(status="unknown", names=(), source=None)


def test_get_declared_commands_parse_error_is_unknown() -> None:
    read_fn, write_fn = _isolated_cache()
    declared = _get_declared_commands(
        "sase-org/sase-broken",
        fetch_fn=_fetch({"sase-org/sase-broken": "not [ valid {{{"}),
        read_cache_fn=read_fn,
        write_cache_fn=write_fn,
    )
    assert declared.status == "unknown"


def test_get_declared_commands_dynamic_is_unknown() -> None:
    read_fn, write_fn = _isolated_cache()
    declared = _get_declared_commands(
        "sase-org/sase-dyn",
        fetch_fn=_fetch({"sase-org/sase-dyn": _DYNAMIC_TOML}),
        read_cache_fn=read_fn,
        write_cache_fn=write_fn,
    )
    assert declared.status == "unknown"


def test_get_declared_commands_offline_never_fetches() -> None:
    read_fn, write_fn = _isolated_cache()

    def _boom(_full_name: str) -> str | None:
        raise AssertionError("offline must not fetch")

    declared = _get_declared_commands(
        "sase-org/sase-listen",
        offline=True,
        fetch_fn=_boom,
        read_cache_fn=read_fn,
        write_cache_fn=write_fn,
    )
    assert declared.status == "unknown"


def test_get_declared_commands_invalidated_on_updated_at() -> None:
    read_fn, write_fn = _isolated_cache()
    fetch = _fetch({"sase-org/sase-listen": _LISTEN_TOML})
    first = _get_declared_commands(
        "sase-org/sase-listen",
        updated_at="2026-09-01T00:00:00Z",
        fetch_fn=fetch,
        read_cache_fn=read_fn,
        write_cache_fn=write_fn,
        clock=lambda: 2000.0,
    )
    assert first.status == "declared"

    calls: list[str] = []

    def _watch(full_name: str) -> str | None:
        calls.append(full_name)
        return _PLAIN_TOML

    second = _get_declared_commands(
        "sase-org/sase-listen",
        updated_at="2026-10-01T00:00:00Z",
        fetch_fn=_watch,
        read_cache_fn=read_fn,
        write_cache_fn=write_fn,
        clock=lambda: 2000.0,
    )
    assert calls == ["sase-org/sase-listen"]
    assert second.status == "none"


def test_get_declared_commands_expires_after_ttl() -> None:
    from sase.plugins.declared_commands import DECLARED_CACHE_TTL_SECONDS

    read_fn, write_fn = _isolated_cache(
        seed={
            "sase-org/sase-listen": {
                "status": "declared",
                "names": ["listen"],
                "source": "pyproject:project.entry-points.sase_commands",
                "updated_at": "2026-10-01T00:00:00Z",
                "fetched_at": 1000.0,
            }
        },
    )
    calls: list[str] = []

    def _watch(full_name: str) -> str | None:
        calls.append(full_name)
        return _PLAIN_TOML

    declared = _get_declared_commands(
        "sase-org/sase-listen",
        updated_at="2026-10-01T00:00:00Z",
        fetch_fn=_watch,
        read_cache_fn=read_fn,
        write_cache_fn=write_fn,
        clock=lambda: 1000.0 + DECLARED_CACHE_TTL_SECONDS + 1.0,
    )
    assert calls == ["sase-org/sase-listen"]
    assert declared.status == "none"


def test_declared_cache_round_trip_on_disk(tmp_path: Path) -> None:
    path = tmp_path / "declared_commands_cache.json"
    fetch = _fetch({"sase-org/sase-listen": _LISTEN_TOML})
    declared = _get_declared_commands(
        "sase-org/sase-listen",
        updated_at="2026-10-01T00:00:00Z",
        fetch_fn=fetch,
        read_cache_fn=lambda: _read_declared_cache(path),
        write_cache_fn=lambda entries: _write_declared_cache(entries, path=path),
        clock=lambda: 2000.0,
    )
    assert declared.status == "declared"
    assert path.exists()
    cached = _read_declared_cache(path)
    assert cached["sase-org/sase-listen"].names == ("listen",)


def test_installed_entry_reports_unknown() -> None:
    def _boom(_full_name: str) -> str | None:
        raise AssertionError("installed entries must not fetch")

    declared = get_declared_commands_for_entry(
        _entry("listen", installed=True), fetch_fn=_boom
    )
    assert declared.status == "unknown"


# --------------------------------------------------------------------------- #
# Collisions before consent
# --------------------------------------------------------------------------- #


def test_declared_problems_flags_shadowed_and_conflict() -> None:
    problems = declared_problems(
        ("listen", "bead", "ok-name"),
        command_owners={"listen": "sase-listen"},
        reserved_names=frozenset({"bead"}),
    )
    by_name = {problem.name: problem for problem in problems}
    assert set(by_name) == {"listen", "bead"}
    assert by_name["listen"].kind == "conflict"
    assert "sase-listen" in by_name["listen"].detail
    assert "both would be disabled" in by_name["listen"].detail
    assert by_name["bead"].kind == "shadowed"
    assert "would be shadowed" in by_name["bead"].detail


def test_declared_problems_flags_invalid_names() -> None:
    problems = declared_problems(
        ("Bad Name",), command_owners={}, reserved_names=frozenset()
    )
    assert len(problems) == 1
    assert problems[0].kind == "shadowed"


def test_declared_problems_clean_names_have_none() -> None:
    assert (
        declared_problems(
            ("listen",), command_owners={}, reserved_names=frozenset({"bead"})
        )
        == ()
    )


# --------------------------------------------------------------------------- #
# JSON surfaces
# --------------------------------------------------------------------------- #


def test_declared_commands_json_shape() -> None:
    payload = declared_commands_json(
        DeclaredCommands(
            status="declared",
            names=("listen",),
            source="pyproject:project.entry-points.sase_commands",
        ),
        declared_problems(
            ("listen",),
            command_owners={"listen": "sase-listen"},
            reserved_names=frozenset(),
        ),
    )
    assert payload["status"] == "declared"
    assert payload["names"] == ["listen"]
    assert payload["source"] == "pyproject:project.entry-points.sase_commands"
    assert len(payload["problems"]) == 1
    assert payload["problems"][0]["problem"] == "conflict"


def test_declared_commands_json_none_is_unknown() -> None:
    assert declared_commands_json(None) == {
        "status": "unknown",
        "names": [],
        "source": None,
        "problems": [],
    }


def test_plugin_entry_json_includes_declared_preview() -> None:
    entry = _entry("listen")
    payload = plugin_entry_json(
        entry,
        declared_commands=DeclaredCommands(
            status="declared",
            names=("listen",),
            source="pyproject:project.entry-points.sase_commands",
        ),
        command_owners={},
        reserved_names=frozenset(),
    )
    assert payload["declared_commands"]["status"] == "declared"
    assert payload["declared_commands"]["names"] == ["listen"]
    assert payload["declared_commands"]["problems"] == []


def test_plugin_entry_json_defaults_to_unknown() -> None:
    payload = plugin_entry_json(_entry("listen"))
    assert payload["declared_commands"]["status"] == "unknown"
    assert payload["declared_commands"]["names"] == []
    assert payload["declared_commands"]["problems"] == []


def test_show_json_attaches_preview() -> None:
    catalog = _catalog(_entry("listen"))
    payload = _build_show_json(
        catalog,
        catalog.entries[0],
        "listen",
        now=1000.0,
        declared_fn=lambda entry, **_: DeclaredCommands(
            status="declared",
            names=("listen",),
            source="pyproject:project.entry-points.sase_commands",
        ),
    )
    assert payload["plugin"]["declared_commands"]["status"] == "declared"
    assert payload["plugin"]["declared_commands"]["names"] == ["listen"]


def test_list_json_attaches_previews() -> None:
    catalog = _catalog(_entry("listen"), _entry("jira", installed=True))
    payload = _build_list_json(
        catalog,
        now=1000.0,
        declared_map_fn=lambda entries, **_: {
            "sase-org/sase-listen": DeclaredCommands(
                status="declared",
                names=("listen",),
                source="pyproject:project.entry-points.sase_commands",
            )
        },
    )
    by_name = {item["name"]: item for item in payload["entries"]}
    assert by_name["listen"]["declared_commands"]["status"] == "declared"
    assert by_name["jira"]["declared_commands"]["status"] == "unknown"


def test_attach_declared_previews_skips_installed_and_offline() -> None:
    def _boom(_full_name: str) -> str | None:
        raise AssertionError("installed/offline entries must not fetch")

    assert (
        attach_declared_previews((_entry("listen", installed=True),), fetch_fn=_boom)
        == {}
    )
    assert (
        attach_declared_previews((_entry("listen"),), offline=True, fetch_fn=_boom)
        == {}
    )


def test_attach_declared_previews_batch() -> None:
    previews = attach_declared_previews(
        (_entry("listen"), _entry("jira", installed=True)),
        fetch_fn=_fetch({"sase-org/sase-listen": _LISTEN_TOML}),
        read_cache_fn=dict,
        write_cache_fn=lambda _entries: None,
    )
    assert previews["sase-org/sase-listen"].status == "declared"
    assert "sase-org/sase-jira" not in previews


# --------------------------------------------------------------------------- #
# Install dry run
# --------------------------------------------------------------------------- #


def _install_args(plugin: str, *, as_json: bool) -> argparse.Namespace:
    return argparse.Namespace(
        plugin_subcommand="install",
        plugin=plugin,
        git=False,
        refresh=False,
        dry_run=True,
        json=as_json,
    )


def _uv_install(tmp_path: Path) -> UvToolInstall:
    sase_dir = tmp_path / "sase"
    sase_dir.mkdir(parents=True, exist_ok=True)
    receipt = sase_dir / "uv-receipt.toml"
    receipt.write_text('[tool]\nrequirements = [{ name = "sase" }]\n', encoding="utf-8")
    return UvToolInstall(
        uv_path="/usr/bin/uv",
        tool_dir=tmp_path,
        sase_dir=sase_dir,
        receipt_path=receipt,
    )


def _available(_dist_name: str) -> ProjectAvailability:
    return ProjectAvailability.AVAILABLE


def test_install_dry_run_panel_shows_new_command(tmp_path: Path) -> None:
    out = Console(file=io.StringIO(), width=200, no_color=True)
    code = handle_plugin_install_command(
        _install_args("listen", as_json=False),
        console=out,
        load_fn=lambda *, refresh: _catalog(_entry("listen")),
        probe_fn=lambda: _uv_install(tmp_path),
        availability_fn=_available,
        declared_fn=lambda entry, **_: DeclaredCommands(
            status="declared",
            names=("listen",),
            source="pyproject:project.entry-points.sase_commands",
        ),
    )
    assert code == 0
    text = out.file.getvalue()  # type: ignore[attr-defined]
    assert "Adds command" in text
    assert "❯ sase listen" in text


def test_install_dry_run_panel_shows_collision_warning(tmp_path: Path) -> None:
    out = Console(file=io.StringIO(), width=200, no_color=True)
    code = handle_plugin_install_command(
        _install_args("bead", as_json=False),
        console=out,
        load_fn=lambda *, refresh: _catalog(_entry("bead")),
        probe_fn=lambda: _uv_install(tmp_path),
        availability_fn=_available,
        declared_fn=lambda entry, **_: DeclaredCommands(
            status="declared",
            names=("bead",),
            source="pyproject:project.entry-points.sase_commands",
        ),
    )
    assert code == 0
    text = out.file.getvalue()  # type: ignore[attr-defined]
    assert "❯ sase bead" in text
    assert "would be shadowed" in text


def test_install_dry_run_panel_renders_nothing_when_unknown(tmp_path: Path) -> None:
    out = Console(file=io.StringIO(), width=200, no_color=True)
    code = handle_plugin_install_command(
        _install_args("listen", as_json=False),
        console=out,
        load_fn=lambda *, refresh: _catalog(_entry("listen")),
        probe_fn=lambda: _uv_install(tmp_path),
        availability_fn=_available,
        declared_fn=lambda entry, **_: None,
    )
    assert code == 0
    text = out.file.getvalue()  # type: ignore[attr-defined]
    assert "Adds command" not in text
    assert "❯ sase" not in text


def test_install_dry_run_json_includes_preview(tmp_path: Path, capsys: Any) -> None:
    code = handle_plugin_install_command(
        _install_args("listen", as_json=True),
        load_fn=lambda *, refresh: _catalog(_entry("listen")),
        probe_fn=lambda: _uv_install(tmp_path),
        availability_fn=_available,
        declared_fn=lambda entry, **_: DeclaredCommands(
            status="declared",
            names=("listen",),
            source="pyproject:project.entry-points.sase_commands",
        ),
    )
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["dry_run"] is True
    assert payload["declared_commands"]["status"] == "declared"
    assert payload["declared_commands"]["names"] == ["listen"]
