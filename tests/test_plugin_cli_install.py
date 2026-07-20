"""Tests for ``sase plugin install``: parser, spec resolution, flow, rendering."""

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
from sase.plugins.cli_install import (
    INSTALL_JSON_SCHEMA_VERSION,
    handle_plugin_install_command,
    _resolve_install_spec,
)
from sase.plugins.installed import InstalledInfo
from sase.uv_tool.detect import NotUvToolInstall, NotUvToolReason, UvToolInstall
from sase.uv_tool.errors import UvCommandFailedError
from sase.uv_tool.runner import UvChangeSet, parse_uv_output

# --------------------------------------------------------------------------- #
# Builders
# --------------------------------------------------------------------------- #


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
        description="desc",
        url=f"https://github.com/{owner}/{repo}",
        homepage="",
        topics=("sase--plugin",),
        stars=0,
        archived=False,
        license="MIT",
        updated_at="",
        installed=InstalledInfo(installed=installed),
    )


def _catalog(*entries: PluginCatalogEntry) -> PluginCatalog:
    return PluginCatalog(
        fetched_at=1000.0,
        entries=entries or (_entry("github"), _entry("telegram")),
        from_cache=True,
        stale=False,
    )


_RECEIPT = """
[tool]
requirements = [
    { name = "sase" },
    { name = "sase-telegram" },
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
    git: bool = False,
    refresh: bool = False,
    dry_run: bool = False,
    json: bool = False,
) -> argparse.Namespace:
    return argparse.Namespace(
        plugin_subcommand="install",
        plugin=plugin,
        git=git,
        refresh=refresh,
        dry_run=dry_run,
        json=json,
    )


def _console() -> Console:
    return Console(file=io.StringIO(), width=200, no_color=True)


def _text(console: Console) -> str:
    return console.file.getvalue()  # type: ignore[attr-defined]


_INSTALL_OUTPUT = """\
Resolved 2 packages in 120ms
 + sase-github==0.4.0
"""


# --------------------------------------------------------------------------- #
# Parser
# --------------------------------------------------------------------------- #


def test_install_parses_positional_and_flags() -> None:
    short = create_parser().parse_args(
        ["plugin", "install", "github", "-g", "-n", "-j", "-r"]
    )
    long = create_parser().parse_args(
        ["plugin", "install", "github", "--git", "--dry-run", "--json", "--refresh"]
    )
    for ns in (short, long):
        assert ns.command == "plugin"
        assert ns.plugin_subcommand == "install"
        assert ns.plugin == "github"
        assert ns.git is True
        assert ns.dry_run is True
        assert ns.json is True
        assert ns.refresh is True


def test_install_requires_plugin() -> None:
    with pytest.raises(SystemExit):
        create_parser().parse_args(["plugin", "install"])


# --------------------------------------------------------------------------- #
# Spec resolution
# --------------------------------------------------------------------------- #


def test_resolve_catalog_name_uses_distribution() -> None:
    resolved = _resolve_install_spec(_catalog(), "github")
    assert resolved is not None
    assert resolved.source == "catalog"
    assert resolved.display_name == "github"
    assert resolved.requirement.requirement_argument() == "sase-github"
    assert resolved.normalized_name == "sase-github"


def test_resolve_repo_and_full_name_match_catalog() -> None:
    for query in ("sase-github", "sase-org/sase-github"):
        resolved = _resolve_install_spec(_catalog(), query)
        assert resolved is not None
        assert resolved.requirement.name == "sase-github"
        assert resolved.source == "catalog"


def test_resolve_git_forces_repo_url() -> None:
    resolved = _resolve_install_spec(_catalog(), "github", git=True)
    assert resolved is not None
    assert resolved.source == "git"
    assert (
        resolved.requirement.requirement_argument()
        == "git+https://github.com/sase-org/sase-github"
    )
    assert resolved.normalized_name == "sase-github"


def test_resolve_raw_requirement_passthrough() -> None:
    resolved = _resolve_install_spec(_catalog(), "sase-foo==1.2")
    assert resolved is not None
    assert resolved.source == "passthrough"
    assert resolved.requirement.as_spec() == "sase-foo==1.2"


def test_resolve_git_url_passthrough() -> None:
    resolved = _resolve_install_spec(_catalog(), "git+https://example.com/x.git")
    assert resolved is not None
    assert resolved.source == "passthrough"
    assert (
        resolved.requirement.requirement_argument() == "git+https://example.com/x.git"
    )


def test_resolve_local_path_passthrough() -> None:
    resolved = _resolve_install_spec(_catalog(), "/abs/path/to/plugin")
    assert resolved is not None
    assert resolved.source == "passthrough"


def test_resolve_unknown_returns_none() -> None:
    assert _resolve_install_spec(_catalog(), "nope") is None


# --------------------------------------------------------------------------- #
# Detection / catalog failures
# --------------------------------------------------------------------------- #


def test_install_not_uv_tool_exits_one() -> None:
    err = _console()
    code = handle_plugin_install_command(
        _args("github"),
        console=_console(),
        err_console=err,
        load_fn=lambda *, refresh: _catalog(),
        probe_fn=_not_install,
    )
    assert code == 1
    assert "uv tool install sase" in _text(err)


def test_install_not_uv_tool_json(capsys: Any) -> None:
    code = handle_plugin_install_command(
        _args("github", json=True),
        load_fn=lambda *, refresh: _catalog(),
        probe_fn=_not_install,
    )
    assert code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema_version"] == INSTALL_JSON_SCHEMA_VERSION
    assert "uv tool" in payload["error"]


def test_install_ephemeral_path_json_error_shape(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: Any,
) -> None:
    workspace_root = tmp_path / "workspace-store"
    plugin_path = workspace_root / "owner" / "repo" / "repo_7" / "plugin"
    monkeypatch.setenv("SASE_WORKSPACE_ROOT", str(workspace_root))

    code = handle_plugin_install_command(
        _args(str(plugin_path), json=True),
        load_fn=lambda *, refresh: _catalog(),
        probe_fn=lambda: _install(tmp_path),
    )

    assert code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "schema_version": INSTALL_JSON_SCHEMA_VERSION,
        "error": str(
            f"plugin 'plugin' cannot be installed from {plugin_path}: "
            "workspace-local checkouts are ephemeral. Install from a durable "
            "source with `sase plugin install --git plugin` or use a durable "
            "checkout path outside the managed workspace store."
        ),
    }


def test_install_catalog_error_exits_one(tmp_path: Path, capsys: Any) -> None:
    from sase.plugins.github_source import GhNotFoundError

    def _load(*, refresh: bool) -> PluginCatalog:
        raise GhNotFoundError()

    code = handle_plugin_install_command(
        _args("github"), load_fn=_load, probe_fn=lambda: _install(tmp_path)
    )
    assert code == 1
    assert "gh" in capsys.readouterr().err.lower()


def test_install_not_found_renders_suggestions(tmp_path: Path) -> None:
    err = _console()
    code = handle_plugin_install_command(
        _args("githubb"),
        console=_console(),
        err_console=err,
        load_fn=lambda *, refresh: _catalog(),
        probe_fn=lambda: _install(tmp_path),
    )
    assert code == 1
    assert "No plugin named 'githubb'" in _text(err)
    assert "github" in _text(err)


def test_install_not_found_json(tmp_path: Path, capsys: Any) -> None:
    code = handle_plugin_install_command(
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
# Install flow
# --------------------------------------------------------------------------- #


def test_install_runs_full_set_plus_new_plugin(tmp_path: Path) -> None:
    seen: dict[str, list[str]] = {}

    def _run(argv: list[str]) -> UvChangeSet:
        seen["argv"] = argv
        return parse_uv_output(_INSTALL_OUTPUT)

    out = _console()
    code = handle_plugin_install_command(
        _args("github"),
        console=out,
        load_fn=lambda *, refresh: _catalog(),
        probe_fn=lambda: _install(tmp_path),
        run_fn=_run,
        installed_index_fn=lambda: {
            "sase-github": InstalledInfo(
                installed=True, version="0.4.0", entry_point_groups=("sase_vcs",)
            )
        },
        axe_running_fn=lambda: False,
        clock=lambda: 0.0,
    )
    assert code == 0
    # The reconstructed --with set keeps the existing plugin and adds the new one.
    assert seen["argv"] == [
        "uv",
        "tool",
        "install",
        "--color",
        "never",
        "sase",
        "--with",
        "sase-telegram",
        "--with",
        "sase-github",
    ]
    text = _text(out)
    assert "sase-github" in text
    assert "0.4.0" in text
    assert "sase_vcs" in text
    assert "Installed github" in text


def test_install_json_payload_is_stable(tmp_path: Path, capsys: Any) -> None:
    code = handle_plugin_install_command(
        _args("github", json=True),
        load_fn=lambda *, refresh: _catalog(),
        probe_fn=lambda: _install(tmp_path),
        run_fn=lambda _argv: parse_uv_output(_INSTALL_OUTPUT),
        installed_index_fn=lambda: {
            "sase-github": InstalledInfo(
                installed=True, version="0.4.0", entry_point_groups=("sase_vcs",)
            )
        },
        axe_running_fn=lambda: False,
        clock=lambda: 0.0,
    )
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema_version"] == INSTALL_JSON_SCHEMA_VERSION
    assert payload["dry_run"] is False
    assert payload["plugin"] == "github"
    assert payload["distribution"] == "sase-github"
    assert payload["source"] == "catalog"
    assert payload["version"] == "0.4.0"
    assert payload["entry_point_groups"] == ["sase_vcs"]
    assert payload["command"][:3] == ["uv", "tool", "install"]
    assert payload["restart"]["status"] == "skipped_not_running"


def test_install_restarts_axe_when_changed(tmp_path: Path) -> None:
    restart_calls = 0
    restart_source = ""

    def _restart(*, desired_state_source: str) -> AxeStartResult:
        nonlocal restart_calls, restart_source
        restart_calls += 1
        restart_source = desired_state_source
        return AxeStartResult(status="started", pid=2468)

    out = _console()
    code = handle_plugin_install_command(
        _args("github"),
        console=out,
        load_fn=lambda *, refresh: _catalog(),
        probe_fn=lambda: _install(tmp_path),
        run_fn=lambda _argv: parse_uv_output(_INSTALL_OUTPUT),
        installed_index_fn=lambda: {},
        axe_running_fn=lambda: True,
        restart_axe_fn=_restart,
        clock=lambda: 0.0,
    )

    assert code == 0
    assert restart_calls == 1
    assert restart_source == "sase plugin install"
    assert "Axe restarted (pid 2468)" in _text(out)


def test_install_noop_does_not_check_axe(tmp_path: Path) -> None:
    def _axe_running() -> bool:
        raise AssertionError("axe status must not be checked for a no-op install")

    out = _console()
    code = handle_plugin_install_command(
        _args("github"),
        console=out,
        load_fn=lambda *, refresh: _catalog(),
        probe_fn=lambda: _install(tmp_path),
        run_fn=lambda _argv: UvChangeSet(),
        installed_index_fn=lambda: {},
        axe_running_fn=_axe_running,
        clock=lambda: 0.0,
    )

    assert code == 0
    assert "Axe Restart" not in _text(out)


def test_install_already_injected_is_idempotent(tmp_path: Path) -> None:
    receipt = """
[tool]
requirements = [
    { name = "sase" },
    { name = "sase-github" },
]
"""

    def _run(_argv: list[str]) -> UvChangeSet:
        raise AssertionError("uv must not run when the plugin is already installed")

    out = _console()
    code = handle_plugin_install_command(
        _args("github"),
        console=out,
        load_fn=lambda *, refresh: _catalog(),
        probe_fn=lambda: _install(tmp_path, receipt),
        run_fn=_run,
    )
    assert code == 0
    text = _text(out)
    assert "already installed" in text
    assert "sase plugin update github" in text


def test_install_command_failure_exits_one(tmp_path: Path) -> None:
    def _run(argv: list[str]) -> UvChangeSet:
        raise UvCommandFailedError(argv=argv, returncode=2, stderr="No solution found")

    err = _console()
    code = handle_plugin_install_command(
        _args("github"),
        console=_console(),
        err_console=err,
        load_fn=lambda *, refresh: _catalog(),
        probe_fn=lambda: _install(tmp_path),
        run_fn=_run,
    )
    assert code == 1
    assert "No solution found" in _text(err)


def test_install_receipt_error_exits_one(tmp_path: Path) -> None:
    install = _install(tmp_path, "this is not toml = [")
    err = _console()
    code = handle_plugin_install_command(
        _args("github"),
        console=_console(),
        err_console=err,
        load_fn=lambda *, refresh: _catalog(),
        probe_fn=lambda: install,
    )
    assert code == 1


# --------------------------------------------------------------------------- #
# Dry run
# --------------------------------------------------------------------------- #


def test_install_dry_run_does_not_execute(tmp_path: Path) -> None:
    def _run(_argv: list[str]) -> UvChangeSet:
        raise AssertionError("uv must not run during --dry-run")

    out = _console()
    code = handle_plugin_install_command(
        _args("github", dry_run=True),
        console=out,
        load_fn=lambda *, refresh: _catalog(),
        probe_fn=lambda: _install(tmp_path),
        run_fn=_run,
    )
    assert code == 0
    text = _text(out)
    assert (
        "uv tool install --color never sase --with sase-telegram --with sase-github"
        in text
    )
    assert "Dry run" in text


def test_install_dry_run_json(tmp_path: Path, capsys: Any) -> None:
    code = handle_plugin_install_command(
        _args("github", dry_run=True, json=True),
        load_fn=lambda *, refresh: _catalog(),
        probe_fn=lambda: _install(tmp_path),
    )
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["dry_run"] is True
    assert payload["plugin"] == "github"
    assert payload["source"] == "catalog"
    assert "sase-github" in payload["command"]


def test_install_git_dry_run_uses_git_spec(tmp_path: Path, capsys: Any) -> None:
    code = handle_plugin_install_command(
        _args("github", git=True, dry_run=True, json=True),
        load_fn=lambda *, refresh: _catalog(),
        probe_fn=lambda: _install(tmp_path),
    )
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["source"] == "git"
    assert "git+https://github.com/sase-org/sase-github" in payload["command"]
