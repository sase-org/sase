"""Execute/path tests for provider-declared agent-CLI install scripts."""

from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path
from typing import Any

from sase.agent_clis.install import (
    AgentCliInstallEntry,
    AgentCliInstallError,
    AgentCliInstallsPlanned,
    InstallScript,
    execute_agent_cli_installs,
    plan_agent_cli_install_status,
)
from sase.agent_clis.models import (
    AgentCliOperation,
    InstallRoute,
    UpdateResultStatus,
)
from sase.agent_clis.runner import AgentCliRunnerError, CommandResult

from .install_helpers import (
    SCRIPT_DIGEST,
    _fetch,
    _npm_status,
    _status,
)


def test_execute_runs_the_script_with_its_env_and_reports_path(
    tmp_path: Path,
) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    binary = bin_dir / "muse"
    binary.write_text("#!/bin/sh\n")
    binary.chmod(0o755)
    calls: list[tuple[tuple[str, ...], dict[str, Any]]] = []

    def runner(argv: Any, **kwargs: Any) -> CommandResult:
        args = tuple(argv)
        calls.append((args, kwargs))
        if args[0] == "bash":
            return CommandResult(argv=args, returncode=0, stdout="installed\n")
        return CommandResult(
            argv=args, returncode=0, stdout="Muse Code 0.1.0 (0.1.0-R708.1)\n"
        )

    entry = plan_agent_cli_install_status(
        replace(_status(), version_regex=r"\((?P<version>[^)]+)\)"),
        env={"PATH": str(bin_dir)},
        fetch_fn=_fetch(tmp_path),
    )
    results = execute_agent_cli_installs(
        AgentCliInstallsPlanned(entries=(entry,)),
        env={"PATH": str(bin_dir)},
        run_fn=runner,
        record_fn=None,
    )

    assert calls[0][0] == ("bash", str(tmp_path / "install.sh"))
    assert calls[0][1]["env_overlay"] == {"MUSE_UPGRADE_MODE": "1"}
    result = results[0]
    assert result.status is UpdateResultStatus.UPDATED
    assert result.operation is AgentCliOperation.INSTALL
    assert result.new_version == "0.1.0-R708.1"
    assert result.script_digest == SCRIPT_DIGEST
    assert result.install_dir == str(bin_dir)
    assert result.install_dir_on_path is True
    assert result.reason is None


def test_execute_reports_the_export_line_when_the_target_is_not_on_path(
    tmp_path: Path,
) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    binary = bin_dir / "muse"
    binary.write_text("#!/bin/sh\n")
    binary.chmod(0o755)

    def runner(argv: Any, **_kwargs: Any) -> CommandResult:
        return CommandResult(argv=tuple(argv), returncode=0, stdout="muse 1.2.3\n")

    entry = plan_agent_cli_install_status(
        _status(install_dir=str(bin_dir)),
        env={"PATH": str(tmp_path / "elsewhere")},
        fetch_fn=_fetch(tmp_path),
    )
    results = execute_agent_cli_installs(
        AgentCliInstallsPlanned(entries=(entry,)),
        env={"PATH": str(tmp_path / "elsewhere")},
        run_fn=runner,
        record_fn=None,
    )

    result = results[0]
    assert result.status is UpdateResultStatus.UPDATED
    assert result.install_dir_on_path is False
    assert result.reason is not None
    assert f'export PATH="{bin_dir}:$PATH"' in result.reason
    assert "SASE did not edit any shell rc file" in result.reason


def test_execute_fails_when_the_script_exits_nonzero(tmp_path: Path) -> None:
    def runner(argv: Any, **_kwargs: Any) -> CommandResult:
        return CommandResult(argv=tuple(argv), returncode=3, stderr="no space left")

    entry = plan_agent_cli_install_status(_status(), fetch_fn=_fetch(tmp_path))
    results = execute_agent_cli_installs(
        AgentCliInstallsPlanned(entries=(entry,)), run_fn=runner, record_fn=None
    )

    result = results[0]
    assert result.status is UpdateResultStatus.FAILED
    assert result.reason is not None
    assert "exit 3" in result.reason
    assert result.output_tail == "no space left"


def test_execute_fails_when_the_binary_is_missing_afterwards(tmp_path: Path) -> None:
    def runner(argv: Any, **_kwargs: Any) -> CommandResult:
        return CommandResult(argv=tuple(argv), returncode=0)

    entry = plan_agent_cli_install_status(
        _status(), env={"PATH": ""}, fetch_fn=_fetch(tmp_path)
    )
    results = execute_agent_cli_installs(
        AgentCliInstallsPlanned(entries=(entry,)),
        env={"PATH": ""},
        run_fn=runner,
        record_fn=None,
    )

    result = results[0]
    assert result.status is UpdateResultStatus.FAILED
    assert result.reason is not None
    assert "could not find `muse`" in result.reason


def test_execute_surfaces_a_runner_error(tmp_path: Path) -> None:
    def runner(argv: Any, **_kwargs: Any) -> CommandResult:
        raise AgentCliRunnerError(tuple(argv), "command not found: bash")

    entry = plan_agent_cli_install_status(_status(), fetch_fn=_fetch(tmp_path))
    results = execute_agent_cli_installs(
        AgentCliInstallsPlanned(entries=(entry,)), run_fn=runner, record_fn=None
    )

    assert results[0].status is UpdateResultStatus.FAILED
    assert results[0].reason is not None
    assert "command not found: bash" in results[0].reason


def test_execute_maps_skips_and_fetch_errors_without_running_anything(
    tmp_path: Path,
) -> None:
    def runner(argv: Any, **_kwargs: Any) -> CommandResult:
        raise AssertionError("must not run a command")

    skipped = plan_agent_cli_install_status(
        _status(executable="/opt/bin/muse", installed_version="1.0.0"),
        fetch_fn=_fetch(tmp_path),
    )

    def failing_fetch(_url: str) -> InstallScript:
        raise AgentCliInstallError("boom")

    failed = plan_agent_cli_install_status(_status(), fetch_fn=failing_fetch)
    results = execute_agent_cli_installs(
        AgentCliInstallsPlanned(entries=(skipped, failed)),
        run_fn=runner,
        record_fn=None,
    )

    assert results[0].status is UpdateResultStatus.SKIPPED
    assert results[1].status is UpdateResultStatus.FAILED
    assert results[1].reason == "boom. See https://example.test/muse"


def test_execute_journals_the_install_with_its_script_digest(tmp_path: Path) -> None:
    recorded: list[Any] = []

    def runner(argv: Any, **_kwargs: Any) -> CommandResult:
        return CommandResult(argv=tuple(argv), returncode=0, stdout="muse 1.2.3\n")

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "muse").write_text("#!/bin/sh\n")
    (bin_dir / "muse").chmod(0o755)
    entry = plan_agent_cli_install_status(
        _status(), env={"PATH": str(bin_dir)}, fetch_fn=_fetch(tmp_path)
    )

    execute_agent_cli_installs(
        AgentCliInstallsPlanned(entries=(entry,)),
        env={"PATH": str(bin_dir)},
        run_fn=runner,
        record_fn=lambda results, **kwargs: recorded.append((results, kwargs)),
    )

    results, kwargs = recorded[0]
    assert results[0].operation is AgentCliOperation.INSTALL
    assert results[0].script_digest == SCRIPT_DIGEST
    assert "elapsed" in kwargs


def test_execute_reports_progress_for_runnable_entries_only(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for binary in ("qwen", "codex"):
        path = bin_dir / binary
        path.write_text("#!/bin/sh\n")
        path.chmod(0o755)

    def runner(argv: Any, **_kwargs: Any) -> CommandResult:
        args = tuple(argv)
        if args[0] == "npm":
            return CommandResult(argv=args, returncode=0)
        return CommandResult(argv=args, returncode=0, stdout=f"{args[0]} 1.2.3\n")

    first = AgentCliInstallEntry(
        _npm_status(),
        route=InstallRoute.NPM,
        argv=("npm", "install", "-g", "@qwen-code/qwen-code"),
        install_dir=str(bin_dir),
        install_dir_on_path=True,
    )
    skipped = AgentCliInstallEntry(
        _npm_status("antigravity", package=None),
        route=InstallRoute.MANUAL,
        skip_reason="manual",
    )
    second = AgentCliInstallEntry(
        _npm_status("codex", package="@openai/codex"),
        route=InstallRoute.NPM,
        argv=("npm", "install", "-g", "@openai/codex"),
        install_dir=str(bin_dir),
        install_dir_on_path=True,
    )
    calls: list[tuple[int, int, str]] = []
    results = execute_agent_cli_installs(
        AgentCliInstallsPlanned(entries=(first, skipped, second)),
        env={"PATH": str(bin_dir)},
        run_fn=runner,
        record_fn=None,
        progress_fn=lambda position, total, entry: calls.append(
            (position, total, entry.name)
        ),
    )

    assert [(position, total) for position, total, _ in calls] == [(1, 2), (2, 2)]
    assert [name for _, _, name in calls] == ["qwen", "codex"]
    assert tuple(result.status for result in results) == (
        UpdateResultStatus.UPDATED,
        UpdateResultStatus.SKIPPED,
        UpdateResultStatus.UPDATED,
    )


def test_execute_npm_install_reports_the_export_line_off_path(
    tmp_path: Path,
) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    binary = bin_dir / "qwen"
    binary.write_text("#!/bin/sh\n")
    binary.chmod(0o755)

    def runner(argv: Any, **_kwargs: Any) -> CommandResult:
        args = tuple(argv)
        if args[0] == "npm":
            return CommandResult(argv=args, returncode=0)
        return CommandResult(argv=args, returncode=0, stdout="qwen 1.2.3\n")

    entry = AgentCliInstallEntry(
        _npm_status(),
        route=InstallRoute.NPM,
        argv=("npm", "install", "-g", "@qwen-code/qwen-code"),
        install_dir=str(bin_dir),
        install_dir_on_path=False,
    )
    results = execute_agent_cli_installs(
        AgentCliInstallsPlanned(entries=(entry,)),
        env={"PATH": str(tmp_path / "elsewhere")},
        run_fn=runner,
        record_fn=None,
    )

    result = results[0]
    assert result.status is UpdateResultStatus.UPDATED
    assert result.new_version == "1.2.3"
    assert result.install_dir == str(bin_dir)
    assert result.install_dir_on_path is False
    assert result.reason is not None
    assert f'export PATH="{bin_dir}:$PATH"' in result.reason


def test_install_dir_prefers_the_declared_env_var_over_the_default(
    tmp_path: Path,
) -> None:
    status = _status(install_dir="~/.local/bin", install_dir_env="MUSE_INSTALL_DIR")

    override = plan_agent_cli_install_status(
        status, env={"MUSE_INSTALL_DIR": "/opt/muse/bin"}, fetch_fn=_fetch(tmp_path)
    )
    default = plan_agent_cli_install_status(status, env={}, fetch_fn=_fetch(tmp_path))
    undeclared = plan_agent_cli_install_status(
        _status(), env={}, fetch_fn=_fetch(tmp_path)
    )

    assert override.install_dir == "/opt/muse/bin"
    assert default.install_dir == os.path.expanduser("~/.local/bin")
    assert undeclared.install_dir is None


def test_a_symlinked_path_entry_still_counts_as_on_path(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    binary = real / "muse"
    binary.write_text("#!/bin/sh\n")
    binary.chmod(0o755)
    link = tmp_path / "link"
    link.symlink_to(real)

    def runner(argv: Any, **_kwargs: Any) -> CommandResult:
        return CommandResult(argv=tuple(argv), returncode=0, stdout="muse 1.2.3\n")

    entry = plan_agent_cli_install_status(
        _status(install_dir=str(link)), env={"PATH": ""}, fetch_fn=_fetch(tmp_path)
    )
    results = execute_agent_cli_installs(
        AgentCliInstallsPlanned(entries=(entry,)),
        env={"PATH": str(link)},
        run_fn=runner,
        record_fn=None,
    )

    assert results[0].install_dir_on_path is True
    assert results[0].reason is None


def test_a_failed_version_probe_is_reported_but_not_a_failed_install(
    tmp_path: Path,
) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    binary = bin_dir / "muse"
    binary.write_text("#!/bin/sh\n")
    binary.chmod(0o755)

    def runner(argv: Any, **_kwargs: Any) -> CommandResult:
        args = tuple(argv)
        if args[0] == "bash":
            return CommandResult(argv=args, returncode=0)
        return CommandResult(argv=args, returncode=1, stderr="unknown flag")

    entry = plan_agent_cli_install_status(
        _status(), env={"PATH": str(bin_dir)}, fetch_fn=_fetch(tmp_path)
    )
    results = execute_agent_cli_installs(
        AgentCliInstallsPlanned(entries=(entry,)),
        env={"PATH": str(bin_dir)},
        run_fn=runner,
        record_fn=None,
    )

    result = results[0]
    assert result.status is UpdateResultStatus.UPDATED
    assert result.new_version is None
    assert result.reason is not None
    assert "post-install version probe failed: unknown flag" in result.reason
