"""Validation and normalization for version-one sudo requests."""

from __future__ import annotations

import hashlib
import os
import re
import stat
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sase.notification_gates.models import GateError

SUDO_REQUEST_SCHEMA_VERSION = 1

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
_ENV_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_FORBIDDEN_ENV_KEYS = frozenset(
    {
        "DYLD_INSERT_LIBRARIES",
        "LD_AUDIT",
        "LD_LIBRARY_PATH",
        "LD_PRELOAD",
        "PYTHONINSPECT",
        "PYTHONPATH",
        "SUDO_ASKPASS",
        "SSH_ASKPASS",
    }
)
_PRIVILEGE_TOOLS = frozenset({"sudo", "sudoedit", "su", "doas", "pkexec", "run0"})
_INTERACTIVE_TOOLS = frozenset(
    {
        "bash",
        "dash",
        "fish",
        "htop",
        "less",
        "more",
        "nano",
        "sh",
        "ssh",
        "top",
        "vim",
        "vi",
        "zsh",
    }
)
_SHELLS = frozenset({"bash", "dash", "fish", "sh", "zsh"})
_CREDENTIAL_WORDS = ("password", "passwd", "passphrase", "secret", "token")


@dataclass(frozen=True)
class _SudoCommand:
    """One reviewed command in a sudo request."""

    id: str
    argv: tuple[str, ...]
    executable_sha256: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "argv": list(self.argv),
            "executable_sha256": self.executable_sha256,
        }


@dataclass(frozen=True)
class SudoRequest:
    """Normalized version-one sudo request."""

    reason: str
    commands: tuple[_SudoCommand, ...]
    run_as: str
    cwd: str
    env: dict[str, str]
    timeout_seconds: int
    stop_policy: str
    output_policy: str
    machine: str | None
    next_prompt: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SUDO_REQUEST_SCHEMA_VERSION,
            "reason": self.reason,
            "commands": [command.to_dict() for command in self.commands],
            "run_as": self.run_as,
            "cwd": self.cwd,
            "env": dict(sorted(self.env.items())),
            "timeout_seconds": self.timeout_seconds,
            "stop_policy": self.stop_policy,
            "output_policy": self.output_policy,
            "machine": self.machine,
            "next_prompt": self.next_prompt,
        }


def normalize_sudo_request(value: object) -> SudoRequest:
    """Validate and normalize one stdin sudo request object."""
    data = _json_object(value, "request")
    unknown = set(data) - {
        "schema_version",
        "reason",
        "commands",
        "run_as",
        "cwd",
        "env",
        "timeout_seconds",
        "timeout",
        "stop_policy",
        "output_policy",
        "machine",
        "next_prompt",
    }
    if unknown:
        raise GateError(
            "invalid_sudo_request",
            "request",
            f"unsupported sudo request field(s): {', '.join(sorted(unknown))}",
        )
    version = data.get("schema_version", SUDO_REQUEST_SCHEMA_VERSION)
    if version != SUDO_REQUEST_SCHEMA_VERSION:
        raise GateError(
            "unsupported_schema",
            "schema_version",
            "sudo request schema_version must be 1",
        )
    reason = _required_text(data.get("reason"), "reason")
    run_as = _run_as(data.get("run_as", "root"))
    cwd = _cwd(data.get("cwd", os.getcwd()))
    env = _env(data.get("env", {}))
    timeout_seconds = _timeout(data.get("timeout_seconds", data.get("timeout", 300)))
    stop_policy = _choice(
        data.get("stop_policy", "terminate"),
        "stop_policy",
        {"terminate", "kill-tree"},
    )
    output_policy = _choice(
        data.get("output_policy", "bounded"),
        "output_policy",
        {"bounded", "discard", "tail"},
    )
    machine = data.get("machine")
    if machine is not None:
        if not isinstance(machine, str) or machine not in {"", "local"}:
            raise GateError(
                "unsupported_machine",
                "machine",
                "remote sudo relay is not available in this phase",
            )
        machine = None
    next_prompt = data.get("next_prompt")
    if next_prompt is not None:
        next_prompt = _required_text(next_prompt, "next_prompt")
    commands = _commands(data.get("commands"))
    return SudoRequest(
        reason=reason,
        commands=commands,
        run_as=run_as,
        cwd=cwd,
        env=env,
        timeout_seconds=timeout_seconds,
        stop_policy=stop_policy,
        output_policy=output_policy,
        machine=machine,
        next_prompt=next_prompt,
    )


def contains_credential_shape(value: object) -> bool:
    """Return whether *value* contains credential-shaped keys or values."""
    if isinstance(value, Mapping):
        for key, item in value.items():
            lowered = str(key).lower()
            if any(word in lowered for word in _CREDENTIAL_WORDS):
                return True
            if contains_credential_shape(item):
                return True
    elif isinstance(value, list | tuple):
        return any(contains_credential_shape(item) for item in value)
    elif isinstance(value, str):
        lowered = value.lower()
        return any(f"{word}=" in lowered for word in _CREDENTIAL_WORDS)
    return False


def _commands(value: object) -> tuple[_SudoCommand, ...]:
    if not isinstance(value, list) or not value:
        raise GateError(
            "invalid_sudo_request",
            "commands",
            "commands must be a non-empty array",
        )
    commands = tuple(_command(item, index) for index, item in enumerate(value))
    ids = [command.id for command in commands]
    duplicates = sorted({item for item in ids if ids.count(item) > 1})
    if duplicates:
        raise GateError(
            "duplicate_identifier",
            "commands",
            f"duplicate command id(s): {', '.join(duplicates)}",
        )
    return commands


def _command(value: object, index: int) -> _SudoCommand:
    target = f"commands[{index}]"
    data = _json_object(value, target)
    unknown = set(data) - {"id", "argv", "executable_sha256"}
    if unknown:
        raise GateError(
            "invalid_sudo_command",
            target,
            f"unsupported command field(s): {', '.join(sorted(unknown))}",
        )
    command_id = _identifier(data.get("id"), f"{target}.id")
    raw_argv = data.get("argv")
    if not isinstance(raw_argv, list) or not raw_argv:
        raise GateError(
            "invalid_sudo_command",
            f"{target}.argv",
            "argv must be a non-empty array",
        )
    argv = tuple(
        _argument(item, f"{target}.argv[{i}]") for i, item in enumerate(raw_argv)
    )
    _reject_unsafe_argv(argv, target)
    executable_sha256 = _executable_sha256(argv[0], target)
    declared_sha256 = data.get("executable_sha256")
    if declared_sha256 is not None and declared_sha256 != executable_sha256:
        raise GateError(
            "snapshot_mismatch",
            f"{target}.executable_sha256",
            "sudo command executable no longer matches the reviewed snapshot",
        )
    return _SudoCommand(
        id=command_id,
        argv=argv,
        executable_sha256=executable_sha256,
    )


def _reject_unsafe_argv(argv: tuple[str, ...], target: str) -> None:
    executable = Path(argv[0])
    name = executable.name
    if name in _PRIVILEGE_TOOLS:
        raise GateError(
            "nested_privilege_tool",
            f"{target}.argv",
            f"sudo requests may not invoke nested privilege tool {name!r}",
        )
    if name in _INTERACTIVE_TOOLS:
        raise GateError(
            "interactive_program",
            f"{target}.argv",
            f"sudo requests may not invoke interactive program {name!r}",
        )
    if name in _SHELLS or any(part == "-c" for part in argv[1:]):
        raise GateError(
            "malformed_shell_request",
            f"{target}.argv",
            "shell commands and '-c' forms are not accepted; provide argv directly",
        )
    for item in argv:
        lowered = item.lower()
        if any(f"{word}=" in lowered for word in _CREDENTIAL_WORDS):
            raise GateError(
                "credential_field_rejected",
                f"{target}.argv",
                "credential-shaped argv values are not accepted",
            )


def _executable_sha256(value: str, target: str) -> str:
    path = Path(value)
    if not path.is_absolute():
        raise GateError(
            "unsnapshotshotted_executable",
            f"{target}.argv[0]",
            "sudo command executables must be absolute paths",
        )
    try:
        st = path.stat()
    except OSError as exc:
        raise GateError(
            "unsnapshotshotted_executable",
            f"{target}.argv[0]",
            f"cannot snapshot executable: {exc}",
        ) from exc
    if not stat.S_ISREG(st.st_mode):
        raise GateError(
            "unsnapshotshotted_executable",
            f"{target}.argv[0]",
            "sudo command executable must be a regular file",
        )
    if os.access(path, os.W_OK):
        raise GateError(
            "agent_writable_executable",
            f"{target}.argv[0]",
            "sudo command executable is writable by this agent",
        )
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _env(value: object) -> dict[str, str]:
    data = _json_object(value, "env")
    result: dict[str, str] = {}
    for raw_key, raw_value in data.items():
        key = str(raw_key)
        if not _ENV_KEY_RE.fullmatch(key):
            raise GateError("invalid_env", f"env.{key}", "invalid environment key")
        if key in _FORBIDDEN_ENV_KEYS or key.startswith(("LD_", "DYLD_")):
            raise GateError(
                "forbidden_env",
                f"env.{key}",
                f"environment key {key!r} is not allowed",
            )
        if any(word in key.lower() for word in _CREDENTIAL_WORDS):
            raise GateError(
                "credential_field_rejected",
                f"env.{key}",
                "credential-shaped environment keys are not accepted",
            )
        if not isinstance(raw_value, str):
            raise GateError(
                "invalid_env", f"env.{key}", "environment values must be strings"
            )
        if contains_credential_shape(raw_value):
            raise GateError(
                "credential_field_rejected",
                f"env.{key}",
                "credential-shaped environment values are not accepted",
            )
        result[key] = raw_value
    return result


def _json_object(value: object, target: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise GateError("invalid_sudo_request", target, f"{target} must be an object")
    return dict(value)


def _required_text(value: object, target: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise GateError("invalid_sudo_request", target, f"{target} is required")
    return value.strip()


def _identifier(value: object, target: str) -> str:
    text = _required_text(value, target)
    if not _ID_RE.fullmatch(text):
        raise GateError(
            "invalid_identifier",
            target,
            f"{target} must contain letters, numbers, '.', '_', or '-'",
        )
    return text


def _argument(value: object, target: str) -> str:
    if not isinstance(value, str) or not value:
        raise GateError("invalid_sudo_command", target, f"{target} must be a string")
    if "\x00" in value:
        raise GateError("invalid_sudo_command", target, "argv cannot contain NUL")
    return value


def _run_as(value: object) -> str:
    text = _required_text(value, "run_as")
    if text != "root" and not _ID_RE.fullmatch(text):
        raise GateError("invalid_sudo_request", "run_as", "run_as is invalid")
    return text


def _cwd(value: object) -> str:
    text = _required_text(value, "cwd")
    path = Path(text).expanduser()
    if not path.is_absolute() or not path.is_dir():
        raise GateError(
            "invalid_sudo_request", "cwd", "cwd must be an existing absolute directory"
        )
    return str(path)


def _timeout(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise GateError(
            "invalid_timeout", "timeout_seconds", "timeout_seconds must be an integer"
        )
    if value <= 0 or value > 24 * 60 * 60:
        raise GateError(
            "invalid_timeout", "timeout_seconds", "timeout_seconds is out of range"
        )
    return value


def _choice(value: object, target: str, allowed: set[str]) -> str:
    if not isinstance(value, str) or value not in allowed:
        raise GateError(
            "invalid_sudo_request",
            target,
            f"{target} must be one of {', '.join(sorted(allowed))}",
        )
    return value


__all__ = [
    "SUDO_REQUEST_SCHEMA_VERSION",
    "SudoRequest",
    "contains_credential_shape",
    "normalize_sudo_request",
]
