"""Plan/execute tests for provider-declared agent-CLI install scripts."""

from __future__ import annotations

import hashlib
import os
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from sase.agent_clis.install import (
    AgentCliInstallError,
    AgentCliInstallsPlanned,
    InstallScript,
    execute_agent_cli_installs,
    fetch_install_script,
    plan_agent_cli_install_status,
    plan_agent_cli_installs,
)
from sase.agent_clis.models import (
    AgentCliOperation,
    AgentCliStatus,
    AgentCliUnknownName,
    InstallMethod,
    UpdateResultStatus,
)
from sase.agent_clis.runner import AgentCliRunnerError, CommandResult

SCRIPT_BODY = b"#!/usr/bin/env bash\necho installing\n"
SCRIPT_DIGEST = hashlib.sha256(SCRIPT_BODY).hexdigest()
SCRIPT_URL = "https://dev.example.test/install.sh"


class _FakeResponse:
    """The minimal ``urlopen`` surface :func:`fetch_install_script` uses."""

    def __init__(self, payload: bytes, *, url: str = SCRIPT_URL) -> None:
        self._payload = payload
        self._url = url

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def geturl(self) -> str:
        return self._url

    def read(self, amt: int | None = None, /) -> bytes:
        return self._payload if amt is None else self._payload[:amt]


def _urlopen(payload: bytes = SCRIPT_BODY, *, served_url: str = SCRIPT_URL) -> Any:
    def opener(_request: Any, **_kwargs: Any) -> _FakeResponse:
        return _FakeResponse(payload, url=served_url)

    return opener


def _status(
    name: str = "muse",
    *,
    executable: str | None = None,
    installed_version: str | None = None,
    install_script_url: str | None = SCRIPT_URL,
    install_dir: str | None = None,
    install_dir_env: str | None = None,
) -> AgentCliStatus:
    return AgentCliStatus(
        name=name,
        display_name="Muse Code",
        binary=name,
        executable=executable,
        installed_version=installed_version,
        latest_version=None,
        install_method=(
            InstallMethod.SELF_MANAGED if executable else InstallMethod.NOT_INSTALLED
        ),
        update_available=False,
        docs_url="https://example.test/muse",
        install_hint=f"run `sase agent-cli install {name}`",
        install_manager=InstallMethod.SCRIPT,
        install_script_url=install_script_url,
        install_env=(("MUSE_UPGRADE_MODE", "1"),),
        install_dir=install_dir,
        install_dir_env=install_dir_env,
    )


def _script(tmp_path: Path) -> InstallScript:
    path = tmp_path / "install.sh"
    path.write_bytes(SCRIPT_BODY)
    return InstallScript(
        url=SCRIPT_URL,
        path=path,
        digest=SCRIPT_DIGEST,
        size_bytes=len(SCRIPT_BODY),
    )


def _fetch(tmp_path: Path) -> Any:
    return lambda _url: _script(tmp_path)


def test_fetch_writes_a_private_file_and_reports_its_digest() -> None:
    script = fetch_install_script(SCRIPT_URL, urlopen_fn=_urlopen())

    try:
        assert script.digest == SCRIPT_DIGEST
        assert script.size_bytes == len(SCRIPT_BODY)
        assert script.path.read_bytes() == SCRIPT_BODY
        assert script.path.stat().st_mode & 0o777 == 0o600
    finally:
        script.remove()


def test_fetch_rejects_plain_http_before_any_request() -> None:
    def opener(*_args: object, **_kwargs: object) -> _FakeResponse:
        raise AssertionError("must not request a non-HTTPS URL")

    with pytest.raises(AgentCliInstallError, match="not HTTPS"):
        fetch_install_script("http://dev.example.test/install.sh", urlopen_fn=opener)


def test_fetch_rejects_a_redirect_that_leaves_https() -> None:
    with pytest.raises(AgentCliInstallError, match="redirected off HTTPS"):
        fetch_install_script(
            SCRIPT_URL,
            urlopen_fn=_urlopen(served_url="http://dev.example.test/install.sh"),
        )


def test_fetch_enforces_a_size_cap() -> None:
    with pytest.raises(AgentCliInstallError, match="byte limit"):
        fetch_install_script(SCRIPT_URL, urlopen_fn=_urlopen(b"x" * 100), max_bytes=10)


def test_fetch_reports_a_transport_failure_as_an_install_error() -> None:
    def opener(*_args: object, **_kwargs: object) -> _FakeResponse:
        raise OSError("connection reset")

    with pytest.raises(AgentCliInstallError, match="could not fetch install script"):
        fetch_install_script(SCRIPT_URL, urlopen_fn=opener)


def test_plan_skips_a_cli_that_declares_no_install_script(tmp_path: Path) -> None:
    status = replace(
        _status("codex", install_script_url=None),
        install_manager="npm",
        install_hint="npm install -g @openai/codex",
    )

    entry = plan_agent_cli_install_status(status, fetch_fn=_fetch(tmp_path))

    assert entry.ready is False
    assert entry.script is None
    assert entry.skip_reason is not None
    assert "npm install -g @openai/codex" in entry.skip_reason


def test_plan_skips_an_installed_cli_unless_forced(tmp_path: Path) -> None:
    status = _status(executable="/opt/bin/muse", installed_version="0.1.0-R708.1")

    skipped = plan_agent_cli_install_status(status, fetch_fn=_fetch(tmp_path))
    forced = plan_agent_cli_install_status(
        status, force=True, fetch_fn=_fetch(tmp_path)
    )

    assert skipped.ready is False
    assert skipped.skip_reason is not None
    assert "already installed (0.1.0-R708.1)" in skipped.skip_reason
    assert "--force" in skipped.skip_reason
    assert forced.ready is True
    assert forced.script is not None


def test_plan_carries_the_declared_env_and_resolved_target(tmp_path: Path) -> None:
    status = _status(install_dir="~/.local/bin", install_dir_env="MUSE_INSTALL_DIR")
    env = {"MUSE_INSTALL_DIR": str(tmp_path / "bin"), "PATH": ""}

    entry = plan_agent_cli_install_status(status, env=env, fetch_fn=_fetch(tmp_path))

    assert entry.argv == ("bash", str(tmp_path / "install.sh"))
    assert entry.env_overlay == (("MUSE_UPGRADE_MODE", "1"),)
    assert entry.install_dir == str(tmp_path / "bin")
    assert entry.script is not None
    assert entry.script.digest == SCRIPT_DIGEST


def test_plan_records_a_fetch_failure_instead_of_raising() -> None:
    def failing_fetch(_url: str) -> InstallScript:
        raise AgentCliInstallError("install script URL is not HTTPS: ftp://x")

    entry = plan_agent_cli_install_status(_status(), fetch_fn=failing_fetch)

    assert entry.ready is False
    assert entry.error == "install script URL is not HTTPS: ftp://x"


def test_plan_reports_an_unknown_name_with_suggestions(tmp_path: Path) -> None:
    plan = plan_agent_cli_installs(
        ["mus3"],
        status_fn=lambda **_kwargs: (_status(),),
        fetch_fn=_fetch(tmp_path),
    )

    assert isinstance(plan, AgentCliUnknownName)
    assert plan.query == "mus3"
    assert plan.suggestions == ("muse",)


def test_cleanup_removes_every_fetched_script(tmp_path: Path) -> None:
    plan = plan_agent_cli_installs(
        ["muse"],
        status_fn=lambda **_kwargs: (_status(),),
        fetch_fn=_fetch(tmp_path),
    )
    assert isinstance(plan, AgentCliInstallsPlanned)
    script = plan.entries[0].script
    assert script is not None and script.path.exists()

    plan.cleanup()
    plan.cleanup()

    assert not script.path.exists()


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
