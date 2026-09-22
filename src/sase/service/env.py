"""Captured environment contract for the service host platform unit."""

from __future__ import annotations

import json
import os
import re
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from os import PathLike
from pathlib import Path
from typing import Any

from sase.core.paths import sase_home as _sase_home
from sase.llm_provider import registry as llm_registry
from sase.service.paths import service_env_path
from sase.service.ssh_agent import (
    is_live_ssh_agent_socket,
    ssh_agent_readiness_warnings,
)

_ENV_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_REDACTED = "[captured]"
_SSH_AUTH_SOCK_ENV = "SSH_AUTH_SOCK"
_SSH_AGENT_PID_ENV = "SSH_AGENT_PID"


@dataclass(frozen=True)
class _CapturedServiceEnvironment:
    """Service environment values plus redacted planning diagnostics."""

    values: dict[str, str]
    warnings: tuple[str, ...] = ()

    @property
    def redacted_values(self) -> dict[str, str]:
        return dict.fromkeys(sorted(self.values), _REDACTED)


class ServiceEnvironmentError(ValueError):
    """Raised when a captured environment file is malformed."""


def capture_service_environment(
    *,
    environ: Mapping[str, str] | None = None,
    force_sase_home: Path | None = None,
    metadata_payload: Mapping[str, Any] | None = None,
) -> _CapturedServiceEnvironment:
    """Capture only the environment variables the platform host is allowed to use."""
    environment = os.environ if environ is None else environ
    names = set(_allowed_provider_env_names(metadata_payload))
    names.update(("PATH", "SASE_FEATURE_FLAGS"))
    # Managed-root overrides honored by sase.core.paths: without them the
    # service reaper falls back to ~/.sase/tmp while launched agents write
    # into $SASE_TMPDIR, and the real root is never reaped (sase-15q).
    names.update(("SASE_TMPDIR", "SASE_HOME"))
    if mobile_credential := _mobile_gateway_credential_env():
        names.add(mobile_credential)

    values: dict[str, str] = {}
    for name in sorted(names):
        value = environment.get(name)
        if value is not None:
            values[name] = str(value)
    agent_values, agent_warnings = _capture_ssh_agent(environment)
    values.update(agent_values)
    if force_sase_home is not None:
        values["SASE_HOME"] = str(force_sase_home.expanduser())
    return _CapturedServiceEnvironment(values=values, warnings=agent_warnings)


def write_service_environment(
    values: Mapping[str, str],
    *,
    path: str | PathLike[str] | None = None,
) -> None:
    """Atomically write the captured service environment with mode ``0600``."""
    target = service_env_path() if path is None else Path(path).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    content = render_service_environment(values)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{target.name}.",
        suffix=".tmp",
        dir=str(target.parent),
        text=True,
    )
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, target)
        os.chmod(target, 0o600)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def render_service_environment(values: Mapping[str, str]) -> str:
    """Render environment values using a strict non-shell JSON-string format."""
    lines: list[str] = []
    for name in sorted(values):
        _validate_env_name(name)
        lines.append(f"{name}={json.dumps(str(values[name]), ensure_ascii=True)}")
    return "".join(f"{line}\n" for line in lines)


def parse_service_environment_text(text: str) -> dict[str, str]:
    """Parse a captured environment file without evaluating shell syntax."""
    values: dict[str, str] = {}
    for lineno, raw_line in enumerate(text.splitlines(), start=1):
        if not raw_line:
            continue
        if "=" not in raw_line:
            raise ServiceEnvironmentError(
                f"malformed service environment entry on line {lineno}"
            )
        name, raw_value = raw_line.split("=", 1)
        try:
            _validate_env_name(name)
        except ValueError as exc:
            raise ServiceEnvironmentError(
                f"malformed service environment variable {name!r}"
            ) from exc
        try:
            parsed = json.loads(raw_value)
        except json.JSONDecodeError as exc:
            raise ServiceEnvironmentError(
                f"malformed service environment value for {name}"
            ) from exc
        if not isinstance(parsed, str):
            raise ServiceEnvironmentError(
                f"malformed service environment value for {name}"
            )
        values[name] = parsed
    return values


def read_service_environment(
    *,
    path: str | PathLike[str] | None = None,
) -> dict[str, str]:
    """Read the captured service environment, returning ``{}`` when absent."""
    target = service_env_path() if path is None else Path(path).expanduser()
    try:
        text = target.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    return parse_service_environment_text(text)


def load_service_environment(
    *,
    sase_home: str | PathLike[str] | None = None,
    override_existing: bool = False,
) -> tuple[str, ...]:
    """Load captured service env values into ``os.environ``.

    Returns the variable names applied. Existing interactive values win unless
    ``override_existing`` is true; this keeps non-foreground commands from
    surprising the caller while allowing the platform foreground host to load
    its exact captured contract.

    A captured ``SSH_AUTH_SOCK`` that is no longer a live socket is ignored,
    together with the captured ``SSH_AGENT_PID``. The host then keeps whatever
    agent the platform manager provided.
    """
    explicit_path = os.environ.get("SASE_SERVICE_ENV")
    path = (
        Path(explicit_path).expanduser()
        if explicit_path
        else service_env_path(_sase_home() if sase_home is None else sase_home)
    )
    values = read_service_environment(path=path)
    if not is_live_ssh_agent_socket(values.get(_SSH_AUTH_SOCK_ENV)):
        values = {
            name: value
            for name, value in values.items()
            if name not in (_SSH_AUTH_SOCK_ENV, _SSH_AGENT_PID_ENV)
        }
    applied: list[str] = []
    for name, value in values.items():
        if override_existing or name not in os.environ:
            os.environ[name] = value
            applied.append(name)
    return tuple(applied)


def environment_files_match(
    actual: Mapping[str, str],
    desired: Mapping[str, str],
) -> bool:
    """Return True when two captured service env maps are exactly equal."""
    return dict(actual) == dict(desired)


def _allowed_provider_env_names(
    metadata_payload: Mapping[str, Any] | None,
) -> tuple[str, ...]:
    payload = (
        llm_registry.get_llm_metadata_payload()
        if metadata_payload is None
        else metadata_payload
    )
    providers = payload.get("providers") if isinstance(payload, Mapping) else {}
    if not isinstance(providers, Mapping):
        return ()
    names: set[str] = set()
    for provider_name, metadata in providers.items():
        name = str(provider_name)
        names.add(llm_registry.provider_path_env_var(name))
        if not isinstance(metadata, Mapping):
            continue
        auth = metadata.get("auth_evidence")
        if isinstance(auth, Mapping):
            for item in auth.get("api_key_env_vars") or ():
                if isinstance(item, str) and item:
                    names.add(item)
    return tuple(sorted(names))


def _mobile_gateway_credential_env() -> str | None:
    try:
        from sase.integrations.mobile_gateway import load_mobile_gateway_config

        value = getattr(load_mobile_gateway_config(), "fcm_credential_env", "")
    except Exception:
        return None
    value = str(value or "").strip()
    return value or None


def _capture_ssh_agent(
    environment: Mapping[str, str],
) -> tuple[dict[str, str], tuple[str, ...]]:
    """Capture the SSH agent handle when it names a live socket.

    A stale socket path is worse than none: the service host loads captured
    values over its inherited environment, so a dead path would replace a
    possibly-working agent with a guaranteed-dead one. What the agent holds is
    not the question, because a host can authenticate by ``IdentityFile`` with
    an empty agent or none at all. Whether the captured environment can
    authenticate is asked of the git remote itself, and only a refusal warns.
    """
    values: dict[str, str] = {}
    sock = environment.get(_SSH_AUTH_SOCK_ENV)
    stale: str | None = None
    if sock:
        if is_live_ssh_agent_socket(sock):
            values[_SSH_AUTH_SOCK_ENV] = str(sock)
            # Systemd- and keyring-provided agents have no PID; that is fine.
            if agent_pid := environment.get(_SSH_AGENT_PID_ENV):
                values[_SSH_AGENT_PID_ENV] = str(agent_pid)
        else:
            stale = (
                f"{_SSH_AUTH_SOCK_ENV} points at {sock}, which is not a live "
                "socket; not captured, so the service host will fall back to "
                "whatever agent the platform manager provides"
            )
    probe_env = dict(values)
    if path := environment.get("PATH"):
        probe_env["PATH"] = path
    warnings = ssh_agent_readiness_warnings(probe_env)
    if warnings and stale is not None:
        warnings = [stale, *warnings]
    return values, tuple(warnings)


def _validate_env_name(name: str) -> None:
    if not _ENV_NAME_RE.fullmatch(name):
        raise ValueError(f"invalid environment variable name: {name!r}")


__all__ = [
    "ServiceEnvironmentError",
    "capture_service_environment",
    "environment_files_match",
    "load_service_environment",
    "parse_service_environment_text",
    "read_service_environment",
    "render_service_environment",
    "write_service_environment",
]
