"""Offline local SSH credential checks used by git retry policy."""

from __future__ import annotations

import shlex
from pathlib import Path

from sase.service.ssh_agent import local_ssh_credential_state
from tests.service.service_effective_env_helpers import _fake_ssh_add, _live_socket


def _fake_ssh_config(
    bin_dir: Path, lines: tuple[str, ...], *, exit_code: int = 0
) -> None:
    bin_dir.mkdir(parents=True, exist_ok=True)
    script = bin_dir / "ssh"
    prints = "\n".join(f"printf '%s\\n' {shlex.quote(line)}" for line in lines)
    script.write_text(f"#!/bin/sh\n{prints}\nexit {exit_code}\n", encoding="utf-8")
    script.chmod(0o755)


def test_local_ssh_credential_state_reports_live_agent_identity(
    tmp_path: Path,
) -> None:
    bin_dir = tmp_path / "bin"
    _fake_ssh_config(bin_dir, ("identityagent SSH_AUTH_SOCK",))
    _fake_ssh_add(bin_dir, 0)
    with _live_socket(tmp_path / "agent.sock"):
        state = local_ssh_credential_state(
            {
                "PATH": str(bin_dir),
                "SSH_AUTH_SOCK": str(tmp_path / "agent.sock"),
            },
            "github.com",
        )

    assert state == "present"


def test_local_ssh_credential_state_checks_identity_files_with_env_home(
    tmp_path: Path,
) -> None:
    bin_dir = tmp_path / "bin"
    home = tmp_path / "home"
    identity = home / ".ssh" / "id_ed25519"
    identity.parent.mkdir(parents=True)
    identity.write_text("key", encoding="utf-8")
    _fake_ssh_config(bin_dir, ("identityagent none", "identityfile ~/.ssh/id_ed25519"))

    assert (
        local_ssh_credential_state(
            {"PATH": str(bin_dir), "HOME": str(home)}, "github.com"
        )
        == "present"
    )


def test_local_ssh_credential_state_is_absent_only_after_checks_fail(
    tmp_path: Path,
) -> None:
    bin_dir = tmp_path / "bin"
    _fake_ssh_config(bin_dir, ("identityagent none", "identityfile ~/.ssh/id_ed25519"))

    assert (
        local_ssh_credential_state(
            {"PATH": str(bin_dir), "HOME": str(tmp_path / "empty-home")},
            "github.com",
        )
        == "absent"
    )


def test_local_ssh_credential_state_unknown_for_unreadable_agent(
    tmp_path: Path,
) -> None:
    bin_dir = tmp_path / "bin"
    _fake_ssh_config(bin_dir, ("identityagent SSH_AUTH_SOCK", "identityfile none"))
    _fake_ssh_add(bin_dir, 2)
    with _live_socket(tmp_path / "agent.sock"):
        state = local_ssh_credential_state(
            {
                "PATH": str(bin_dir),
                "SSH_AUTH_SOCK": str(tmp_path / "agent.sock"),
            },
            "github.com",
        )

    assert state == "unknown"


def test_local_ssh_credential_state_keeps_identity_file_result_when_agent_is_unknown(
    tmp_path: Path,
) -> None:
    bin_dir = tmp_path / "bin"
    identity = tmp_path / "id_ed25519"
    identity.write_text("key", encoding="utf-8")
    _fake_ssh_config(
        bin_dir, ("identityagent SSH_AUTH_SOCK", f"identityfile {identity}")
    )
    _fake_ssh_add(bin_dir, 2)
    with _live_socket(tmp_path / "agent.sock"):
        state = local_ssh_credential_state(
            {
                "PATH": str(bin_dir),
                "SSH_AUTH_SOCK": str(tmp_path / "agent.sock"),
            },
            "github.com",
        )

    assert state == "present"


def test_local_ssh_credential_state_unknown_when_ssh_config_fails(
    tmp_path: Path,
) -> None:
    bin_dir = tmp_path / "bin"
    _fake_ssh_config(bin_dir, (), exit_code=255)

    assert local_ssh_credential_state({"PATH": str(bin_dir)}, "github.com") == "unknown"


def test_local_ssh_credential_state_unknown_for_custom_ssh_or_missing_host(
    tmp_path: Path,
) -> None:
    env = {"PATH": str(tmp_path / "no-ssh"), "GIT_SSH_COMMAND": "ssh -F custom"}

    assert local_ssh_credential_state(env, "github.com") == "unknown"
    assert local_ssh_credential_state({"PATH": env["PATH"]}, None) == "unknown"
