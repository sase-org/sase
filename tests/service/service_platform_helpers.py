"""Shared fakes and home-directory stubs for service-platform tests."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from types import SimpleNamespace

import pytest

from sase.service.platform import CommandResult


def _exe(tmp_path: Path) -> Path:
    path = tmp_path / "bin" / "sase"
    path.parent.mkdir(exist_ok=True)
    path.write_text("#!/bin/sh\n", encoding="utf-8")
    path.chmod(0o755)
    return path


class _Runner:
    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, argv: Sequence[str]) -> CommandResult:
        command = tuple(argv)
        self.calls.append(command)
        if command[:3] == ("systemctl", "--user", "is-enabled"):
            return CommandResult(1, "disabled\n")
        if command[:3] == ("systemctl", "--user", "is-active"):
            return CommandResult(3, "inactive\n")
        if command[0] == "loginctl":
            return CommandResult(0, "no\n")
        return CommandResult(0, "")


class _LinuxManager:
    def __init__(
        self,
        *,
        enabled: Sequence[str] = (),
        active: Sequence[str] = (),
        linger: str = "no",
    ) -> None:
        self.calls: list[tuple[str, ...]] = []
        self.enabled = set(enabled)
        self.active = set(active)
        self.linger = linger

    def __call__(self, argv: Sequence[str]) -> CommandResult:
        command = tuple(argv)
        self.calls.append(command)
        if command[:3] == ("systemctl", "--user", "is-enabled"):
            unit = command[3]
            if unit in self.enabled:
                return CommandResult(0, "enabled\n")
            return CommandResult(1, "disabled\n")
        if command[:3] == ("systemctl", "--user", "is-active"):
            unit = command[3]
            if unit in self.active:
                return CommandResult(0, "active\n")
            return CommandResult(3, "inactive\n")
        if command[0] == "loginctl" and "enable-linger" in command:
            raise AssertionError(f"privileged linger command must not run: {command}")
        if command[0] == "loginctl":
            return CommandResult(0, f"{self.linger}\n")
        if command[:3] == ("systemctl", "--user", "enable"):
            self.enabled.add(command[3])
        if command[:3] == ("systemctl", "--user", "start"):
            self.active.add(command[3])
        if command[:3] == ("systemctl", "--user", "disable"):
            unit = command[-1]
            self.enabled.discard(unit)
            if "--now" in command:
                self.active.discard(unit)
        if command[:3] == ("systemctl", "--user", "stop"):
            self.active.discard(command[3])
        return CommandResult(0, "")


class _DarwinManager:
    def __init__(
        self,
        *,
        active: Sequence[str] = (),
        user_disabled: Sequence[str] = (),
    ) -> None:
        self.calls: list[tuple[str, ...]] = []
        self.active = set(active)
        self.user_disabled = set(user_disabled)

    def __call__(self, argv: Sequence[str]) -> CommandResult:
        command = tuple(argv)
        self.calls.append(command)
        if command[:2] == ("launchctl", "print"):
            label = command[2].rsplit("/", 1)[-1]
            if label in self.user_disabled:
                return CommandResult(1, stderr="SMAppService: service is disabled\n")
            if label in self.active:
                return CommandResult(0, stdout="state = running\n")
            return CommandResult(1, stderr="Could not find service\n")
        if command[:2] == ("launchctl", "bootstrap"):
            plist = Path(command[3])
            assert plist.exists()
            label = plist.stem
            if label in self.user_disabled:
                raise AssertionError(f"must not bootstrap user-disabled {label}")
            self.active.add(label)
            return CommandResult(0, "")
        if command[:2] == ("launchctl", "bootout"):
            label = command[2].rsplit("/", 1)[-1]
            self.active.discard(label)
            return CommandResult(0, "")
        return CommandResult(0, "")


def _linux_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("HOME", str(tmp_path))
    sase_home = tmp_path / ".sase"
    monkeypatch.setenv("SASE_HOME", str(sase_home))
    monkeypatch.setattr("sase.service.platform.platform.system", lambda: "Linux")
    monkeypatch.setattr("sase.service.platform._readiness_warnings", lambda _env: ())
    return sase_home


def _darwin_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("HOME", str(tmp_path))
    sase_home = tmp_path / ".sase"
    monkeypatch.setenv("SASE_HOME", str(sase_home))
    monkeypatch.setattr("sase.service.platform.platform.system", lambda: "Darwin")
    monkeypatch.setattr("sase.service.platform._readiness_warnings", lambda _env: ())
    return sase_home


def _stub_non_ssh_readiness(monkeypatch: pytest.MonkeyPatch) -> None:
    # Readiness compares the interactive shell's managed-tmp root against the
    # captured one, so an ambient SASE_TMPDIR/SASE_HOME (every agent shell has
    # one) would otherwise leak a genuine mismatch warning into these tests.
    monkeypatch.delenv("SASE_TMPDIR", raising=False)
    monkeypatch.delenv("SASE_HOME", raising=False)
    monkeypatch.setattr(
        "sase.service.platform.collect_agent_cli_statuses", lambda **_k: ()
    )
    monkeypatch.setattr(
        "sase.integrations.mobile_gateway.load_mobile_gateway_config",
        lambda: SimpleNamespace(command=()),
    )
