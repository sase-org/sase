"""Shared fixtures for provider-declared agent-CLI install-script tests."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from sase.agent_clis.install import InstallScript
from sase.agent_clis.models import (
    AgentCliStatus,
    InstallMethod,
)
from sase.agent_clis.runner import CommandResult

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


def _npm_status(
    name: str = "qwen",
    *,
    executable: str | None = None,
    installed_version: str | None = None,
    package: str | None = "@qwen-code/qwen-code",
) -> AgentCliStatus:
    return AgentCliStatus(
        name=name,
        display_name="Qwen Code",
        binary=name,
        executable=executable,
        installed_version=installed_version,
        latest_version=None,
        install_method=(
            InstallMethod.NPM if executable else InstallMethod.NOT_INSTALLED
        ),
        update_available=False,
        docs_url="https://example.test/qwen",
        install_hint=(
            f"run `sase agent-cli install {name}` (npm install -g {package})"
            if package
            else "install from https://example.test/qwen"
        ),
        package=package,
        install_manager="npm",
    )


def _npm_bin(tmp_path: Path) -> Path:
    """A directory with a fake `npm` executable for PATH resolution."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    npm = bin_dir / "npm"
    npm.write_text("#!/bin/sh\n")
    npm.chmod(0o755)
    return bin_dir


def _npm_probe(prefix: str, root: str) -> Any:
    """A run_fn answering only `npm prefix -g` and `npm root -g`."""

    def run(argv: Any, **_kwargs: Any) -> CommandResult:
        args = tuple(argv)
        if args[1:3] == ("prefix", "-g"):
            return CommandResult(argv=args, returncode=0, stdout=f"{prefix}\n")
        if args[1:3] == ("root", "-g"):
            return CommandResult(argv=args, returncode=0, stdout=f"{root}\n")
        raise AssertionError(f"unexpected npm probe: {args}")

    return run


def _never_run(argv: Any, **_kwargs: Any) -> CommandResult:
    raise AssertionError(f"must not run a subprocess: {tuple(argv)}")


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
