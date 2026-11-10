"""Sudo gate creation, manifest validation, and request-intent coverage."""

from __future__ import annotations

import argparse
import copy
import hashlib
import io
import json
from pathlib import Path
import sys

import pytest

from sase.agent.staged_handoff import read_staged_handoff
from sase.main.parser import create_parser
from sase.notification_gates.durability import read_json_object
from sase.notification_gates.models import GATE_TURN_DEFAULT_TIMEOUT_SECONDS, GateError
from sase.notification_gates.service import create_gate
from sase.sudo import cli as sudo_cli
from sase.sudo.gate import APPROVE_OPTION_ID, DENY_OPTION_ID, build_sudo_gate_request
from sase.sudo.manifest import selected_sudo_manifest
from sase.sudo.models import normalize_sudo_request
from sase.sudo.snapshot import ExecutableSnapshot, tcc_warning
from sase.sudo.ssh_snapshot import _RemoteExecutableSnapshot
from tests._sudo_gate_helpers import _multi_command_request, _request
from tests.monitor._fixtures import make_starter_agent, write_project_file

_REMOTE_HASH = "ab" * 32
_SCUTIL = "/usr/sbin/scutil"

_DEFAULT_GATE_TIMEOUT_SECONDS = int(GATE_TURN_DEFAULT_TIMEOUT_SECONDS)


def test_sudo_gate_creation_is_unconditional(gate_home: Path) -> None:
    del gate_home
    spec = build_sudo_gate_request(_request())

    gate = create_gate(spec)

    assert gate.request_id
    assert gate.bundle_path.exists()


def test_sudo_request_stages_before_publishing_or_marking_intent(
    gate_home: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    project = "sudo-cli-staged"
    write_project_file(project)
    creator_dir = make_starter_agent(
        project,
        "20260812120001",
        "lane",
        agent_session="lane",
        agent_session_role="root",
    )
    monkeypatch.setenv("SASE_AGENT_NAME", "lane")
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", creator_dir)
    monkeypatch.setenv("SASE_AGENT", "1")
    monkeypatch.delenv("SASE_FINALIZER_OWNED_TURN", raising=False)
    monkeypatch.delenv("SASE_NATIVE_HELPER", raising=False)
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(_request())))

    result = sudo_cli._request(argparse.Namespace(origin_agent=None, json=True))

    out = capsys.readouterr()
    descriptor = json.loads(out.out)
    assert result == 0
    assert descriptor["status"] == "staged"
    assert descriptor["kind"] == "sudo"
    assert descriptor["request_id"].startswith("sudo-")
    assert descriptor["staged_id"]
    assert "Staged" in out.err
    staged = read_staged_handoff(creator_dir)
    assert staged is not None
    assert staged["kind"] == "gate"
    assert staged["payload"]["spec"]["payload"]["sudo"]["manifest_sha256"]
    assert not list(Path(creator_dir).glob(".sase_gate_intent.*"))
    assert not (Path(creator_dir) / ".sase_gate_pending").exists()
    from sase.notification_gates.paths import bundle_paths

    assert not bundle_paths("sudo", str(descriptor["request_id"])).root.exists()


def test_sudo_gate_contains_tty_approve_and_headless_deny(
    gate_home: Path,
) -> None:
    del gate_home

    gate = create_gate(build_sudo_gate_request(_request()))

    request = read_json_object(gate.request_path)
    options = {option["id"]: option for option in request["options"]}
    assert options[APPROVE_OPTION_ID]["requires_tty"] is True
    assert options[DENY_OPTION_ID]["requires_tty"] is False
    assert request["presentation"]["chip"]["label"] == "sudo"
    assert request["turn"]["pending_status"] == "SUDO"
    assert request["turn"]["settled_status"] == "SUDOED"


def test_sudo_manifest_subset_rehashes_in_reviewed_order() -> None:
    spec = build_sudo_gate_request(_multi_command_request())
    sudo_payload = spec["payload"]["sudo"]
    manifest = sudo_payload["manifest"]

    subset, command_ids, manifest_sha256 = selected_sudo_manifest(
        manifest,
        ("gamma", "alpha"),
    )

    assert command_ids == ("alpha", "gamma")
    assert [command["id"] for command in subset["commands"]] == ["alpha", "gamma"]
    assert manifest_sha256 != sudo_payload["manifest_sha256"]


def test_sudo_request_omitting_gate_timeout_uses_one_day_window() -> None:
    request = _request()
    del request["timeout_seconds"]

    normalized = normalize_sudo_request(request)
    spec = build_sudo_gate_request(request)

    assert normalized.gate_timeout_seconds == _DEFAULT_GATE_TIMEOUT_SECONDS
    assert spec["gate_timeout_seconds"] == float(_DEFAULT_GATE_TIMEOUT_SECONDS)


@pytest.mark.parametrize("timeout_key", ["timeout_seconds", "timeout"])
def test_sudo_request_command_timeout_does_not_set_review_window(
    timeout_key: str,
) -> None:
    request = _request()
    del request["timeout_seconds"]
    request[timeout_key] = 30

    normalized = normalize_sudo_request(request)
    spec = build_sudo_gate_request(request)

    assert normalized.commands[0].timeout_seconds == 30.0
    assert spec["gate_timeout_seconds"] == float(_DEFAULT_GATE_TIMEOUT_SECONDS)


def test_sudo_request_honors_explicit_gate_timeout() -> None:
    request = _request()
    request["gate_timeout_seconds"] = 600

    normalized = normalize_sudo_request(request)
    spec = build_sudo_gate_request(request)

    assert normalized.gate_timeout_seconds == 600
    assert spec["gate_timeout_seconds"] == 600.0


@pytest.mark.parametrize("value", [0, 86401, 600.0, True])
def test_sudo_request_rejects_invalid_gate_timeout(value: object) -> None:
    request = _request()
    request["gate_timeout_seconds"] = value

    with pytest.raises(GateError) as excinfo:
        normalize_sudo_request(request)

    assert excinfo.value.code == "invalid_timeout"


def test_sudo_request_validation_rejects_shorthand_and_unsafe_forms() -> None:
    executable = _request()["commands"][0]["argv"][0]

    with pytest.raises(GateError) as shorthand:
        normalize_sudo_request({"reason": "missing ids", "commands": [[executable]]})
    assert shorthand.value.code == "invalid_sudo_request"

    nested = _request()
    nested["commands"] = [{"id": "nested", "argv": ["/usr/bin/sudo", "id"]}]
    with pytest.raises(GateError) as nested_error:
        normalize_sudo_request(nested)
    assert nested_error.value.code == "nested_privilege_tool"

    bad_env = _request()
    bad_env["env"] = {"SUDO_ASKPASS": "/tmp/prompt"}
    with pytest.raises(GateError) as env_error:
        normalize_sudo_request(bad_env)
    assert env_error.value.code == "forbidden_env"


def test_sudo_manifest_hash_is_part_of_kind_validation(gate_home: Path) -> None:
    del gate_home
    spec = build_sudo_gate_request(_request())
    tampered = copy.deepcopy(spec)
    tampered["payload"]["sudo"]["manifest"]["commands"][0]["why"] = "tampered"

    with pytest.raises(GateError) as excinfo:
        create_gate(tampered)

    assert excinfo.value.code == "invalid_sudo_payload"
    assert excinfo.value.target == "payload.sudo.manifest"


def test_sudo_answer_command_option_does_not_clobber_root_command() -> None:
    args = create_parser().parse_args(
        [
            "sudo",
            "answer",
            "sudo-123",
            "--run",
            "--json",
            "--command",
            "refresh",
        ]
    )

    assert args.command == "sudo"
    assert args.sudo_subcommand == "answer"
    assert args.sudo_command == ["refresh"]


def _remote_snapshot(
    path: str,
    *,
    sha256: str | None = _REMOTE_HASH,
    error_code: str | None = None,
    message: str | None = None,
    platform: str = "linux",
    full_disk_access: bool | None = None,
) -> _RemoteExecutableSnapshot:
    return _RemoteExecutableSnapshot(
        host_facts={"full_disk_access": full_disk_access, "platform": platform},
        executables=(
            ExecutableSnapshot(
                path=path,
                sha256=sha256,
                error_code=error_code,
                message=message,
            ),
        ),
    )


def _patch_remote_snapshot(
    monkeypatch: pytest.MonkeyPatch, snapshot: _RemoteExecutableSnapshot
) -> list[tuple[str, tuple[str, ...]]]:
    calls: list[tuple[str, tuple[str, ...]]] = []

    def fake(host: str, paths: object, **_kwargs: object) -> _RemoteExecutableSnapshot:
        calls.append((host, tuple(str(path) for path in paths)))  # type: ignore[arg-type]
        return snapshot

    monkeypatch.setattr("sase.sudo.gate.snapshot_remote_executables", fake)
    return calls


def test_remote_sudo_request_uses_target_hash_for_missing_local_binary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_remote_snapshot(monkeypatch, _remote_snapshot(_SCUTIL, platform="darwin"))
    request = _request()
    request["machine"] = "mac"
    request["commands"][0]["argv"] = [_SCUTIL]

    spec = build_sudo_gate_request(request)
    sudo = spec["payload"]["sudo"]

    assert sudo["request"]["commands"][0]["executable_sha256"] == _REMOTE_HASH
    assert sudo["target"]["snapshot"]["taken_on"] == "target"
    assert sudo["target"]["snapshot"]["host_facts"]["platform"] == "darwin"
    preview = next(
        resource["content"]
        for resource in spec["resources"]
        if resource["path"] == "sudo-request.md"
    )
    assert "Target facts: platform=darwin" in preview


def test_remote_sudo_request_rejects_target_writable_executable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    local = _request()["commands"][0]["argv"][0]
    _patch_remote_snapshot(
        monkeypatch,
        _remote_snapshot(
            local,
            sha256=None,
            error_code="agent_writable_executable",
            message="sudo command executable is writable by this agent",
        ),
    )
    request = _request()
    request["machine"] = "mac"

    with pytest.raises(GateError) as excinfo:
        build_sudo_gate_request(request)

    assert excinfo.value.code == "agent_writable_executable"


def test_remote_sudo_request_fails_when_target_is_unreachable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom(host: str, paths: object, **_kwargs: object) -> _RemoteExecutableSnapshot:
        del host, paths
        raise GateError(
            "remote_snapshot_unavailable",
            "ssh",
            "could not snapshot executables on 'mac'; "
            "the target must be online when the request is created",
        )

    monkeypatch.setattr("sase.sudo.gate.snapshot_remote_executables", boom)
    request = _request()
    request["machine"] = "mac"
    request["commands"][0]["argv"] = [_SCUTIL]

    with pytest.raises(GateError) as excinfo:
        build_sudo_gate_request(request)

    assert excinfo.value.code == "remote_snapshot_unavailable"


def test_remote_sudo_request_declared_hash_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_remote_snapshot(monkeypatch, _remote_snapshot(_SCUTIL))
    request = _request()
    request["machine"] = "mac"
    request["commands"][0]["argv"] = [_SCUTIL]
    request["commands"][0]["executable_sha256"] = "cd" * 32

    with pytest.raises(GateError) as excinfo:
        build_sudo_gate_request(request)

    assert excinfo.value.code == "snapshot_mismatch"


def test_local_sudo_request_still_hashes_locally() -> None:
    request = _request()
    executable = request["commands"][0]["argv"][0]
    spec = build_sudo_gate_request(request)
    sudo = spec["payload"]["sudo"]
    expected = hashlib.sha256(Path(executable).read_bytes()).hexdigest()

    assert sudo["request"]["commands"][0]["executable_sha256"] == expected
    assert sudo["target"]["snapshot"]["taken_on"] == "local"
    assert sudo["target"]["remote"] is False


def test_validate_remote_sudo_spec_does_not_ssh_or_hash_locally(
    gate_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del gate_home
    calls: list[str] = []
    _patch_remote_snapshot(monkeypatch, _remote_snapshot(_SCUTIL, platform="darwin"))
    request = _request()
    request["machine"] = "mac"
    request["commands"][0]["argv"] = [_SCUTIL]
    spec = build_sudo_gate_request(request)

    def boom(*_args: object, **_kwargs: object) -> object:
        calls.append("ssh")
        raise AssertionError("validation must not snapshot remotely")

    def local_boom(*_args: object, **_kwargs: object) -> object:
        calls.append("local")
        raise AssertionError("validation must not hash locally")

    monkeypatch.setattr("sase.sudo.gate.snapshot_remote_executables", boom)
    monkeypatch.setattr("sase.sudo.snapshot.snapshot_executable", local_boom)
    monkeypatch.setattr("sase.sudo.models.snapshot_executable", local_boom)

    create_gate(spec)

    assert calls == []


def test_preview_warns_for_darwin_without_full_disk_access(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_remote_snapshot(
        monkeypatch,
        _remote_snapshot(_SCUTIL, platform="darwin", full_disk_access=False),
    )
    request = _request()
    request["machine"] = "mac"
    request["commands"][0]["argv"] = [_SCUTIL]
    spec = build_sudo_gate_request(request)
    preview = next(
        resource["content"]
        for resource in spec["resources"]
        if resource["path"] == "sudo-request.md"
    )

    assert "full_disk_access=no" in preview
    assert "macOS TCC" in preview
    assert "Allow full disk access for remote users" in preview


def test_preview_omits_tcc_warning_for_linux_and_missing_facts() -> None:
    spec = build_sudo_gate_request(_request())
    preview = next(
        resource["content"]
        for resource in spec["resources"]
        if resource["path"] == "sudo-request.md"
    )
    assert "macOS TCC" not in preview
    assert tcc_warning({"remote": False, "host": "athena"}) is None
    assert (
        tcc_warning(
            {
                "remote": True,
                "host": "mac",
                "snapshot": {
                    "taken_on": "target",
                    "host_facts": {"platform": "linux", "full_disk_access": None},
                },
            }
        )
        is None
    )
