"""Tests for ``sase plugin update``: parser, single/--all flow, rendering, JSON."""

from __future__ import annotations

import argparse
import io
import json
from pathlib import Path
from typing import Any

from rich.console import Console

from sase.axe.process import AxeStartResult
from sase.main.parser import create_parser
from sase.plugins.catalog import PluginCatalog, PluginCatalogEntry
from sase.plugins.cli_update import (
    UPDATE_PLUGIN_JSON_SCHEMA_VERSION,
    handle_plugin_update_command,
)
from sase.plugins.installed import InstalledInfo
from sase.uv_tool.detect import NotUvToolInstall, NotUvToolReason, UvToolInstall
from sase.uv_tool.errors import UvCommandFailedError
from sase.uv_tool.runner import UvChangeSet, parse_uv_output

# --------------------------------------------------------------------------- #
# Builders
# --------------------------------------------------------------------------- #


def _entry(
    name: str, owner: str = "sase-org", *, repo: str | None = None
) -> PluginCatalogEntry:
    repo = repo if repo is not None else f"sase-{name}"
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
        updated_at="",
        installed=InstalledInfo(),
    )


def _catalog(*entries: PluginCatalogEntry) -> PluginCatalog:
    return PluginCatalog(
        fetched_at=1000.0,
        entries=entries
        or (
            _entry("github"),
            _entry("telegram"),
            _entry("jira", "acme", repo="acme-jira"),
        ),
        from_cache=True,
        stale=False,
    )


_RECEIPT = """
[tool]
requirements = [
    { name = "sase" },
    { name = "sase-github" },
    { name = "sase-telegram" },
]
"""

# A dev receipt: editable entries plus bare index dups of two plugins, exactly
# what `uv tool install sase` records for an editable dev checkout.
_DEV_RECEIPT = """
[tool]
requirements = [
    { name = "sase", editable = "/home/u/sase" },
    { name = "sase-github", editable = "/home/u/sase-github" },
    { name = "sase-telegram", editable = "/home/u/sase-telegram" },
    { name = "sase-github" },
    { name = "sase-telegram" },
]
"""


def _intact_dev_receipt(tmp_path: Path) -> str:
    source_home = tmp_path / "sources"
    for name in ("sase", "sase-github", "sase-telegram"):
        (source_home / name).mkdir(parents=True)
    return _DEV_RECEIPT.replace("/home/u", str(source_home))


def _install(tmp_path: Path, receipt: str = _RECEIPT) -> UvToolInstall:
    sase_dir = tmp_path / "sase"
    sase_dir.mkdir(parents=True, exist_ok=True)
    path = sase_dir / "uv-receipt.toml"
    path.write_text(receipt, encoding="utf-8")
    return UvToolInstall(
        uv_path="/usr/bin/uv",
        tool_dir=tmp_path,
        sase_dir=sase_dir,
        receipt_path=path,
    )


def _not_install() -> NotUvToolInstall:
    return NotUvToolInstall(
        reason=NotUvToolReason.WRONG_PREFIX,
        sys_prefix=Path("/home/u/sase/.venv"),
        expected_sase_dir=Path("/t/sase"),
        receipt_path=Path("/t/sase/uv-receipt.toml"),
        uv_path="/usr/bin/uv",
    )


def _args(
    plugin: str | None = None,
    *,
    all_: bool = False,
    refresh: bool = False,
    dry_run: bool = False,
    json: bool = False,
) -> argparse.Namespace:
    return argparse.Namespace(
        plugin_subcommand="update",
        plugin=plugin,
        all=all_,
        refresh=refresh,
        dry_run=dry_run,
        json=json,
    )


def _console() -> Console:
    return Console(file=io.StringIO(), width=200, no_color=True)


def _text(console: Console) -> str:
    return console.file.getvalue()  # type: ignore[attr-defined]


def _versions(name: str) -> str | None:
    return {"sase-github": "0.4.0", "sase-telegram": "0.1.0"}.get(name)


_UPGRADE_OUTPUT = """\
Resolved 3 packages in 90ms
 - sase-github==0.3.2
 + sase-github==0.4.0
"""


# --------------------------------------------------------------------------- #
# Parser
# --------------------------------------------------------------------------- #


def test_update_parses_positional_and_flags() -> None:
    short = create_parser().parse_args(["plugin", "update", "github", "-n", "-j", "-r"])
    long = create_parser().parse_args(
        ["plugin", "update", "github", "--dry-run", "--json", "--refresh"]
    )
    for ns in (short, long):
        assert ns.plugin_subcommand == "update"
        assert ns.plugin == "github"
        assert ns.all is False
        assert ns.dry_run is True
        assert ns.json is True
        assert ns.refresh is True


def test_update_all_without_plugin_parses() -> None:
    ns = create_parser().parse_args(["plugin", "update", "-a"])
    assert ns.plugin is None
    assert ns.all is True


# --------------------------------------------------------------------------- #
# Single-plugin update
# --------------------------------------------------------------------------- #


def test_update_single_runs_upgrade_package_argv(tmp_path: Path) -> None:
    seen: dict[str, list[str]] = {}

    def _run(argv: list[str]) -> UvChangeSet:
        seen["argv"] = argv
        return parse_uv_output(_UPGRADE_OUTPUT)

    out = _console()
    code = handle_plugin_update_command(
        _args("github"),
        console=out,
        load_fn=lambda *, refresh: _catalog(),
        probe_fn=lambda: _install(tmp_path),
        run_fn=_run,
        version_fn=_versions,
        axe_running_fn=lambda: False,
        clock=lambda: 0.0,
    )
    assert code == 0
    # Full set re-injected; only sase-github gets --upgrade-package (core pinned).
    assert seen["argv"] == [
        "uv",
        "tool",
        "install",
        "--color",
        "never",
        "sase",
        "--with",
        "sase-github",
        "--with",
        "sase-telegram",
        "--upgrade-package",
        "sase-github",
    ]
    text = _text(out)
    assert "0.3.2 → 0.4.0" in text
    assert "Updated 1 plugin" in text


def test_update_resolves_short_name_from_receipt_without_catalog(
    tmp_path: Path,
) -> None:
    def _load(*, refresh: bool) -> PluginCatalog:
        raise AssertionError("catalog must not be loaded for an installed plugin")

    out = _console()
    code = handle_plugin_update_command(
        _args("github"),
        console=out,
        load_fn=_load,
        probe_fn=lambda: _install(tmp_path),
        run_fn=lambda _argv: parse_uv_output(_UPGRADE_OUTPUT),
        version_fn=_versions,
        axe_running_fn=lambda: False,
        clock=lambda: 0.0,
    )
    assert code == 0


def test_update_community_plugin_absent_from_catalog(tmp_path: Path) -> None:
    # A plugin injected via a raw spec but not in the catalog still resolves
    # straight from the receipt.
    receipt = """
[tool]
requirements = [
    { name = "sase" },
    { name = "sase-acme" },
]
"""
    seen: dict[str, list[str]] = {}
    out = _console()
    code = handle_plugin_update_command(
        _args("sase-acme"),
        console=out,
        load_fn=lambda *, refresh: _catalog(),
        probe_fn=lambda: _install(tmp_path, receipt),
        run_fn=lambda argv: (
            seen.update(argv=argv)
            or parse_uv_output("- sase-acme==1.0\n+ sase-acme==1.1\n")
        ),
        version_fn=lambda _n: None,
        axe_running_fn=lambda: False,
        clock=lambda: 0.0,
    )
    assert code == 0
    assert "--upgrade-package" in seen["argv"]
    assert "sase-acme" in seen["argv"]


def test_update_json_payload_is_stable(tmp_path: Path, capsys: Any) -> None:
    clock = iter([10.0, 13.5])
    code = handle_plugin_update_command(
        _args("github", json=True),
        load_fn=lambda *, refresh: _catalog(),
        probe_fn=lambda: _install(tmp_path),
        run_fn=lambda _argv: parse_uv_output(_UPGRADE_OUTPUT),
        version_fn=_versions,
        axe_running_fn=lambda: False,
        clock=lambda: next(clock),
    )
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema_version"] == UPDATE_PLUGIN_JSON_SCHEMA_VERSION
    assert payload["dry_run"] is False
    assert payload["changed"] is True
    assert payload["elapsed_seconds"] == 3.5
    assert payload["counts"] == {"updated": 1, "already_current": 0}
    assert payload["plugins"] == [
        {
            "name": "sase-github",
            "kind": "upgraded",
            "old_version": "0.3.2",
            "new_version": "0.4.0",
        }
    ]
    assert payload["restart"]["status"] == "skipped_not_running"


def test_update_restarts_axe_when_changed(tmp_path: Path) -> None:
    restart_calls = 0
    restart_source = ""

    def _restart(*, desired_state_source: str) -> AxeStartResult:
        nonlocal restart_calls, restart_source
        restart_calls += 1
        restart_source = desired_state_source
        return AxeStartResult(status="started", pid=1357)

    out = _console()
    code = handle_plugin_update_command(
        _args("github"),
        console=out,
        load_fn=lambda *, refresh: _catalog(),
        probe_fn=lambda: _install(tmp_path),
        run_fn=lambda _argv: parse_uv_output(_UPGRADE_OUTPUT),
        version_fn=_versions,
        axe_running_fn=lambda: True,
        restart_axe_fn=_restart,
        clock=lambda: 0.0,
    )

    assert code == 0
    assert restart_calls == 1
    assert restart_source == "sase plugin update"
    assert "Axe restarted (pid 1357)" in _text(out)


def test_update_noop_says_up_to_date(tmp_path: Path) -> None:
    out = _console()
    code = handle_plugin_update_command(
        _args("github"),
        console=out,
        load_fn=lambda *, refresh: _catalog(),
        probe_fn=lambda: _install(tmp_path),
        run_fn=lambda _argv: parse_uv_output("Nothing to upgrade\n"),
        version_fn=_versions,
        axe_running_fn=lambda: (_ for _ in ()).throw(
            AssertionError("axe status must not be checked for a no-op update")
        ),
        clock=lambda: 0.0,
    )
    assert code == 0
    assert "Already up to date" in _text(out)


# --------------------------------------------------------------------------- #
# --all
# --------------------------------------------------------------------------- #


def test_update_all_upgrades_every_injected_plugin(tmp_path: Path) -> None:
    seen: dict[str, list[str]] = {}

    def _run(argv: list[str]) -> UvChangeSet:
        seen["argv"] = argv
        return parse_uv_output(_UPGRADE_OUTPUT)

    out = _console()
    code = handle_plugin_update_command(
        _args(all_=True),
        console=out,
        load_fn=lambda *, refresh: _catalog(),
        probe_fn=lambda: _install(tmp_path),
        run_fn=_run,
        version_fn=_versions,
        axe_running_fn=lambda: False,
        clock=lambda: 0.0,
    )
    assert code == 0
    argv = seen["argv"]
    assert argv.count("--upgrade-package") == 2
    assert "sase-github" in argv
    assert "sase-telegram" in argv
    text = _text(out)
    assert "0.3.2 → 0.4.0" in text
    assert "already current" in text


def test_update_all_dedupes_duplicate_dev_receipt_plugins(tmp_path: Path) -> None:
    seen: dict[str, list[str]] = {}

    def _run(argv: list[str]) -> UvChangeSet:
        seen["argv"] = argv
        return parse_uv_output(_UPGRADE_OUTPUT)

    out = _console()
    code = handle_plugin_update_command(
        _args(all_=True),
        console=out,
        load_fn=lambda *, refresh: _catalog(),
        probe_fn=lambda: _install(tmp_path, _intact_dev_receipt(tmp_path)),
        run_fn=_run,
        version_fn=_versions,
        axe_running_fn=lambda: False,
        clock=lambda: 0.0,
    )
    assert code == 0
    argv = seen["argv"]
    # One --upgrade-package per unique plugin, not one per raw receipt row.
    assert argv.count("--upgrade-package") == 2
    assert argv.count("sase-github") == 1
    assert argv.count("sase-telegram") == 1


def test_update_all_dry_run_json_dedupes_dev_receipt(
    tmp_path: Path, capsys: Any
) -> None:
    code = handle_plugin_update_command(
        _args(all_=True, dry_run=True, json=True),
        load_fn=lambda *, refresh: _catalog(),
        probe_fn=lambda: _install(tmp_path, _intact_dev_receipt(tmp_path)),
    )
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["plugins"] == ["sase-github", "sase-telegram"]
    assert payload["command"].count("--upgrade-package") == 2


def test_update_all_with_no_plugins_is_clean(tmp_path: Path) -> None:
    receipt = """
[tool]
requirements = [
    { name = "sase" },
]
"""

    def _run(_argv: list[str]) -> UvChangeSet:
        raise AssertionError("uv must not run when there are no plugins")

    out = _console()
    code = handle_plugin_update_command(
        _args(all_=True),
        console=out,
        load_fn=lambda *, refresh: _catalog(),
        probe_fn=lambda: _install(tmp_path, receipt),
        run_fn=_run,
    )
    assert code == 0
    assert "No plugins are installed" in _text(out)


# --------------------------------------------------------------------------- #
# Misses
# --------------------------------------------------------------------------- #


def test_update_known_but_not_installed_suggests_install(tmp_path: Path) -> None:
    err = _console()
    code = handle_plugin_update_command(
        _args("jira"),
        console=_console(),
        err_console=err,
        load_fn=lambda *, refresh: _catalog(),
        probe_fn=lambda: _install(tmp_path),
    )
    assert code == 1
    text = _text(err)
    assert "jira is not installed" in text
    assert "sase plugin install jira" in text


def test_update_unknown_name_suggests(tmp_path: Path) -> None:
    err = _console()
    code = handle_plugin_update_command(
        _args("githubb"),
        console=_console(),
        err_console=err,
        load_fn=lambda *, refresh: _catalog(),
        probe_fn=lambda: _install(tmp_path),
    )
    assert code == 1
    assert "No plugin named 'githubb'" in _text(err)


def test_update_requires_plugin_or_all(tmp_path: Path) -> None:
    err = _console()
    code = handle_plugin_update_command(
        _args(),
        err_console=err,
        probe_fn=lambda: _install(tmp_path),
    )
    assert code == 2
    assert "-a|--all" in _text(err)


# --------------------------------------------------------------------------- #
# Detection / command failures
# --------------------------------------------------------------------------- #


def test_update_not_uv_tool_exits_one() -> None:
    err = _console()
    code = handle_plugin_update_command(
        _args("github"),
        console=_console(),
        err_console=err,
        probe_fn=_not_install,
    )
    assert code == 1
    assert "uv tool install sase" in _text(err)


def test_update_command_failure_exits_one(tmp_path: Path) -> None:
    def _run(argv: list[str]) -> UvChangeSet:
        raise UvCommandFailedError(argv=argv, returncode=2, stderr="boom")

    err = _console()
    code = handle_plugin_update_command(
        _args("github"),
        console=_console(),
        err_console=err,
        load_fn=lambda *, refresh: _catalog(),
        probe_fn=lambda: _install(tmp_path),
        run_fn=_run,
        version_fn=_versions,
    )
    assert code == 1
    assert "boom" in _text(err)


# --------------------------------------------------------------------------- #
# Dry run
# --------------------------------------------------------------------------- #


def test_update_dry_run_does_not_execute(tmp_path: Path) -> None:
    def _run(_argv: list[str]) -> UvChangeSet:
        raise AssertionError("uv must not run during --dry-run")

    out = _console()
    code = handle_plugin_update_command(
        _args("github", dry_run=True),
        console=out,
        load_fn=lambda *, refresh: _catalog(),
        probe_fn=lambda: _install(tmp_path),
        run_fn=_run,
    )
    assert code == 0
    text = _text(out)
    assert "--upgrade-package sase-github" in text
    assert "Dry run" in text


def test_update_all_dry_run_json(tmp_path: Path, capsys: Any) -> None:
    code = handle_plugin_update_command(
        _args(all_=True, dry_run=True, json=True),
        load_fn=lambda *, refresh: _catalog(),
        probe_fn=lambda: _install(tmp_path),
    )
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["dry_run"] is True
    assert payload["all"] is True
    assert payload["plugins"] == ["sase-github", "sase-telegram"]
    assert payload["command"].count("--upgrade-package") == 2
