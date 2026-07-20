"""Tests for ``sase plugin uninstall``: parser, flow, rendering, JSON."""

from __future__ import annotations

import argparse
import io
import json
from pathlib import Path
from typing import Any

import pytest
from rich.console import Console

from sase.axe.process import AxeStartResult
from sase.main.parser import create_parser
from sase.plugins.catalog import PluginCatalog, PluginCatalogEntry
from sase.plugins.cli_uninstall import (
    UNINSTALL_PLUGIN_JSON_SCHEMA_VERSION,
    handle_plugin_uninstall_command,
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

# A dev receipt: editable entries plus bare index dups of one plugin.
_DEV_RECEIPT = """
[tool]
requirements = [
    { name = "sase", editable = "/home/u/sase" },
    { name = "sase-github", editable = "/home/u/sase-github" },
    { name = "sase-telegram" },
    { name = "sase-github" },
]
"""


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
    plugin: str,
    *,
    refresh: bool = False,
    dry_run: bool = False,
    json: bool = False,
) -> argparse.Namespace:
    return argparse.Namespace(
        plugin_subcommand="uninstall",
        plugin=plugin,
        refresh=refresh,
        dry_run=dry_run,
        json=json,
    )


def _console() -> Console:
    return Console(file=io.StringIO(), width=200, no_color=True)


def _text(console: Console) -> str:
    return console.file.getvalue()  # type: ignore[attr-defined]


_UNINSTALL_OUTPUT = """\
Resolved 1 package in 50ms
 - sase-github==0.4.0
Uninstalled 1 package
"""


# --------------------------------------------------------------------------- #
# Parser
# --------------------------------------------------------------------------- #


def test_uninstall_parses_positional_and_flags() -> None:
    short = create_parser().parse_args(
        ["plugin", "uninstall", "github", "-n", "-j", "-r"]
    )
    long = create_parser().parse_args(
        ["plugin", "uninstall", "github", "--dry-run", "--json", "--refresh"]
    )
    for ns in (short, long):
        assert ns.command == "plugin"
        assert ns.plugin_subcommand == "uninstall"
        assert ns.plugin == "github"
        assert ns.dry_run is True
        assert ns.json is True
        assert ns.refresh is True


def test_uninstall_requires_plugin() -> None:
    with pytest.raises(SystemExit):
        create_parser().parse_args(["plugin", "uninstall"])


# --------------------------------------------------------------------------- #
# Uninstall flow
# --------------------------------------------------------------------------- #


def test_uninstall_runs_full_set_minus_plugin(tmp_path: Path) -> None:
    seen: dict[str, list[str]] = {}

    def _run(argv: list[str]) -> UvChangeSet:
        seen["argv"] = argv
        return parse_uv_output(_UNINSTALL_OUTPUT)

    out = _console()
    code = handle_plugin_uninstall_command(
        _args("github"),
        console=out,
        load_fn=lambda *, refresh: _catalog(),
        probe_fn=lambda: _install(tmp_path),
        run_fn=_run,
        axe_running_fn=lambda: False,
        clock=lambda: 0.0,
    )
    assert code == 0
    # Full set re-injected minus sase-github; sase core + sase-telegram stay.
    assert seen["argv"] == [
        "uv",
        "tool",
        "install",
        "--color",
        "never",
        "sase",
        "--with",
        "sase-telegram",
    ]
    text = _text(out)
    assert "sase-github" in text
    assert "(removed)" in text
    assert "Uninstalled github" in text


def test_uninstall_resolves_from_receipt_without_catalog(tmp_path: Path) -> None:
    def _load(*, refresh: bool) -> PluginCatalog:
        raise AssertionError("catalog must not load for an installed plugin")

    out = _console()
    code = handle_plugin_uninstall_command(
        _args("github"),
        console=out,
        load_fn=_load,
        probe_fn=lambda: _install(tmp_path),
        run_fn=lambda _argv: parse_uv_output(_UNINSTALL_OUTPUT),
        axe_running_fn=lambda: False,
        clock=lambda: 0.0,
    )
    assert code == 0


def test_uninstall_dedupes_dev_receipt_duplicates(tmp_path: Path) -> None:
    seen: dict[str, list[str]] = {}

    def _run(argv: list[str]) -> UvChangeSet:
        seen["argv"] = argv
        return parse_uv_output(_UNINSTALL_OUTPUT)

    code = handle_plugin_uninstall_command(
        _args("github"),
        console=_console(),
        load_fn=lambda *, refresh: _catalog(),
        probe_fn=lambda: _install(tmp_path, _DEV_RECEIPT),
        run_fn=_run,
        axe_running_fn=lambda: False,
        clock=lambda: 0.0,
    )
    assert code == 0
    argv = seen["argv"]
    # Both raw sase-github rows (editable + bare) are gone.
    assert "sase-github" not in argv
    assert "/home/u/sase-github" not in argv


def test_uninstall_json_payload_is_stable(tmp_path: Path, capsys: Any) -> None:
    clock = iter([10.0, 11.0])
    code = handle_plugin_uninstall_command(
        _args("github", json=True),
        load_fn=lambda *, refresh: _catalog(),
        probe_fn=lambda: _install(tmp_path),
        run_fn=lambda _argv: parse_uv_output(_UNINSTALL_OUTPUT),
        axe_running_fn=lambda: False,
        clock=lambda: next(clock),
    )
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema_version"] == UNINSTALL_PLUGIN_JSON_SCHEMA_VERSION
    assert payload["dry_run"] is False
    assert payload["plugin"] == "github"
    assert payload["distribution"] == "sase-github"
    assert payload["changed"] is True
    assert payload["removed_version"] == "0.4.0"
    assert payload["elapsed_seconds"] == 1.0
    assert payload["command"][:3] == ["uv", "tool", "install"]
    assert payload["restart"]["status"] == "skipped_not_running"


def test_uninstall_restarts_axe_when_changed(tmp_path: Path) -> None:
    restart_calls = 0
    restart_source = ""

    def _restart(*, desired_state_source: str) -> AxeStartResult:
        nonlocal restart_calls, restart_source
        restart_calls += 1
        restart_source = desired_state_source
        return AxeStartResult(status="started", pid=9753)

    out = _console()
    code = handle_plugin_uninstall_command(
        _args("github"),
        console=out,
        load_fn=lambda *, refresh: _catalog(),
        probe_fn=lambda: _install(tmp_path),
        run_fn=lambda _argv: parse_uv_output(_UNINSTALL_OUTPUT),
        axe_running_fn=lambda: True,
        restart_axe_fn=_restart,
        clock=lambda: 0.0,
    )

    assert code == 0
    assert restart_calls == 1
    assert restart_source == "sase plugin uninstall"
    assert "Axe restarted (pid 9753)" in _text(out)


def test_uninstall_noop_does_not_check_axe(tmp_path: Path) -> None:
    def _axe_running() -> bool:
        raise AssertionError("axe status must not be checked for a no-op uninstall")

    out = _console()
    code = handle_plugin_uninstall_command(
        _args("github"),
        console=out,
        load_fn=lambda *, refresh: _catalog(),
        probe_fn=lambda: _install(tmp_path),
        run_fn=lambda _argv: UvChangeSet(),
        axe_running_fn=_axe_running,
        clock=lambda: 0.0,
    )

    assert code == 0
    assert "Axe Restart" not in _text(out)


# --------------------------------------------------------------------------- #
# Already absent (idempotent no-op success)
# --------------------------------------------------------------------------- #


def test_uninstall_already_absent_is_noop_success(tmp_path: Path) -> None:
    def _run(_argv: list[str]) -> UvChangeSet:
        raise AssertionError("uv must not run when the plugin is already absent")

    out = _console()
    code = handle_plugin_uninstall_command(
        _args("jira"),  # known in catalog, not in the receipt
        console=out,
        load_fn=lambda *, refresh: _catalog(),
        probe_fn=lambda: _install(tmp_path),
        run_fn=_run,
    )
    assert code == 0
    text = _text(out)
    assert "jira is not installed" in text
    assert "nothing to uninstall" in text


def test_uninstall_already_absent_json(tmp_path: Path, capsys: Any) -> None:
    code = handle_plugin_uninstall_command(
        _args("jira", json=True),
        load_fn=lambda *, refresh: _catalog(),
        probe_fn=lambda: _install(tmp_path),
        run_fn=lambda _a: (_ for _ in ()).throw(AssertionError("uv must not run")),
    )
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["installed"] is False
    assert payload["changed"] is False
    assert payload["plugin"] == "jira"


# --------------------------------------------------------------------------- #
# Misses
# --------------------------------------------------------------------------- #


def test_uninstall_unknown_name_suggests(tmp_path: Path) -> None:
    err = _console()
    code = handle_plugin_uninstall_command(
        _args("githubb"),
        console=_console(),
        err_console=err,
        load_fn=lambda *, refresh: _catalog(),
        probe_fn=lambda: _install(tmp_path),
    )
    assert code == 1
    assert "No plugin named 'githubb'" in _text(err)


def test_uninstall_unknown_json(tmp_path: Path, capsys: Any) -> None:
    code = handle_plugin_uninstall_command(
        _args("githubb", json=True),
        load_fn=lambda *, refresh: _catalog(),
        probe_fn=lambda: _install(tmp_path),
    )
    assert code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["found"] is False
    assert payload["query"] == "githubb"
    assert "github" in payload["suggestions"]


# --------------------------------------------------------------------------- #
# Detection / command failures
# --------------------------------------------------------------------------- #


def test_uninstall_not_uv_tool_exits_one() -> None:
    err = _console()
    code = handle_plugin_uninstall_command(
        _args("github"),
        console=_console(),
        err_console=err,
        probe_fn=_not_install,
    )
    assert code == 1
    assert "uv tool install sase" in _text(err)


def test_uninstall_not_uv_tool_json(capsys: Any) -> None:
    code = handle_plugin_uninstall_command(
        _args("github", json=True),
        probe_fn=_not_install,
    )
    assert code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema_version"] == UNINSTALL_PLUGIN_JSON_SCHEMA_VERSION
    assert "uv tool" in payload["error"]


def test_uninstall_receipt_error_exits_one(tmp_path: Path) -> None:
    install = _install(tmp_path, "this is not toml = [")
    err = _console()
    code = handle_plugin_uninstall_command(
        _args("github"),
        console=_console(),
        err_console=err,
        probe_fn=lambda: install,
    )
    assert code == 1


def test_uninstall_command_failure_exits_one(tmp_path: Path) -> None:
    def _run(argv: list[str]) -> UvChangeSet:
        raise UvCommandFailedError(argv=argv, returncode=2, stderr="boom")

    err = _console()
    code = handle_plugin_uninstall_command(
        _args("github"),
        console=_console(),
        err_console=err,
        load_fn=lambda *, refresh: _catalog(),
        probe_fn=lambda: _install(tmp_path),
        run_fn=_run,
    )
    assert code == 1
    assert "boom" in _text(err)


# --------------------------------------------------------------------------- #
# Dry run
# --------------------------------------------------------------------------- #


def test_uninstall_dry_run_does_not_execute(tmp_path: Path) -> None:
    def _run(_argv: list[str]) -> UvChangeSet:
        raise AssertionError("uv must not run during --dry-run")

    out = _console()
    code = handle_plugin_uninstall_command(
        _args("github", dry_run=True),
        console=out,
        load_fn=lambda *, refresh: _catalog(),
        probe_fn=lambda: _install(tmp_path),
        run_fn=_run,
    )
    assert code == 0
    text = _text(out)
    assert "uv tool install --color never sase --with sase-telegram" in text
    assert "Dry run" in text


def test_uninstall_dry_run_json(tmp_path: Path, capsys: Any) -> None:
    code = handle_plugin_uninstall_command(
        _args("github", dry_run=True, json=True),
        load_fn=lambda *, refresh: _catalog(),
        probe_fn=lambda: _install(tmp_path),
    )
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["dry_run"] is True
    assert payload["plugin"] == "github"
    assert payload["distribution"] == "sase-github"
    assert "sase-github" not in payload["command"]
