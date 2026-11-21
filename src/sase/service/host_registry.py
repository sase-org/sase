"""Account-wide registry of live ``sase service run`` hosts.

``host.lock`` and ``state.json`` are keyed to one SASE home, so a host that
runs against a different (for example throwaway) home is invisible to them.
Every foreground host therefore also registers under one per-account
directory, ``$XDG_RUNTIME_DIR/sase/service-hosts/`` (falling back to a
per-uid runtime directory). Each entry is one JSON file whose exclusive flock
the host holds for its whole lifetime; it records the pid, the process start
identity, the SASE home, the native unit or scope, and the launching agent's
``SASE_AGENT_NAME``. The host removes its entry on exit. Readers ignore (and
reap) entries whose pid is gone, whose start identity no longer matches, or
whose flock is no longer held.

``sase service run`` refuses to start while another live host is registered,
whatever its SASE home, unless :data:`SERVICE_ALLOW_SECOND_HOST_ENV` holds a
non-empty reason. ``sase service status`` lists every other live host from
this registry and from ``systemctl --user list-units 'sase-service-*'``.
"""

from __future__ import annotations

import fcntl
import json
import os
import shutil
import sys
import tempfile
import time
from collections.abc import Callable, Generator, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sase.core.paths import sase_home
from sase.core.process_identity import process_identity_matches, process_identity_token
from sase.detach_scope import SASE_SERVICE_UNIT, process_systemd_unit
from sase.service.platform_models import CommandResult

#: Overrides the registry directory (tests point this at a private directory).
SERVICE_HOST_REGISTRY_DIR_ENV = "SASE_SERVICE_HOST_REGISTRY_DIR"
#: Escape hatch: a non-empty reason that lets a second host start anyway.
SERVICE_ALLOW_SECOND_HOST_ENV = "SASE_SERVICE_ALLOW_SECOND_HOST"
#: Transient scopes created by the detached start path use this unit prefix.
SERVICE_SCOPE_UNIT_PREFIX = "sase-service-"

_ENTRY_PREFIX = "host-"
_ENTRY_SUFFIX = ".json"
_REGISTRY_LOCK_NAME = ".registry.lock"
_ENTRY_SCHEMA_VERSION = 1
_ENTRY_MAX_BYTES = 16 * 1024
_SYSTEMCTL_TIMEOUT_SECONDS = 5.0


@dataclass(frozen=True)
class _ServiceHostRegistryEntry:
    """One registered service host."""

    pid: int
    identity: str
    sase_home: str
    unit: str | None
    agent_name: str | None
    registered_at: float
    path: Path | None = None

    @classmethod
    def from_wire(
        cls, payload: Mapping[str, Any], *, path: Path | None = None
    ) -> _ServiceHostRegistryEntry:
        return cls(
            pid=int(payload["pid"]),
            identity=str(payload.get("identity") or ""),
            sase_home=str(payload["sase_home"]),
            unit=_optional_text(payload.get("unit")),
            agent_name=_optional_text(payload.get("agent_name")),
            registered_at=float(payload.get("registered_at") or 0.0),
            path=path,
        )

    def to_wire(self) -> dict[str, Any]:
        return {
            "schema_version": _ENTRY_SCHEMA_VERSION,
            "pid": self.pid,
            "identity": self.identity,
            "sase_home": self.sase_home,
            "unit": self.unit,
            "agent_name": self.agent_name,
            "registered_at": self.registered_at,
        }

    def describe(self) -> str:
        """Return ``pid N (home H, unit U, launched by agent A)``."""
        details = [f"home {self.sase_home}"]
        if self.unit:
            details.append(f"unit {self.unit}")
        if self.agent_name:
            details.append(f"launched by agent {self.agent_name}")
        return f"pid {self.pid} ({', '.join(details)})"


@dataclass(frozen=True)
class OtherServiceHost:
    """A live service host other than the current home's own host."""

    source: str
    pid: int | None
    sase_home: str | None
    home_differs: bool | None
    unit: str | None
    agent_name: str | None
    stop_command: str

    def to_wire(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "pid": self.pid,
            "sase_home": self.sase_home,
            "home_differs": self.home_differs,
            "unit": self.unit,
            "agent_name": self.agent_name,
            "stop_command": self.stop_command,
        }


class _ServiceHostRegistration:
    """This host's registry entry; the held flock marks it live."""

    def __init__(self, fd: int, path: Path) -> None:
        self._fd: int | None = fd
        self.path = path

    def release(self) -> None:
        """Remove the entry, then drop its flock."""
        if self._fd is None:
            return
        fd, self._fd = self._fd, None
        try:
            self.path.unlink(missing_ok=True)
        except OSError:
            pass
        finally:
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            finally:
                os.close(fd)


@dataclass(frozen=True)
class ServiceHostRegistrationResult:
    """Outcome of registering the starting host."""

    registration: _ServiceHostRegistration | None
    others: tuple[_ServiceHostRegistryEntry, ...] = ()
    refused: bool = False
    message: str | None = None


def _service_host_registry_dir(environ: Mapping[str, str] | None = None) -> Path:
    """Return the per-account registry directory (not created)."""
    env = os.environ if environ is None else environ
    override = (env.get(SERVICE_HOST_REGISTRY_DIR_ENV) or "").strip()
    if override:
        return Path(override).expanduser()
    runtime = (env.get("XDG_RUNTIME_DIR") or "").strip()
    if runtime and Path(runtime).is_dir():
        return Path(runtime) / "sase" / "service-hosts"
    run_user = Path(f"/run/user/{os.getuid()}")
    if run_user.is_dir() and os.access(run_user, os.W_OK):
        return run_user / "sase" / "service-hosts"
    # A fixed root keeps the fallback account-wide even when TMPDIR differs.
    return Path("/tmp") / f"sase-{os.getuid()}" / "service-hosts"


def register_service_host(
    *,
    home: Path | None = None,
    unit: str | None = None,
    agent_name: str | None = None,
    allow_second_reason: str | None = None,
    registry_dir: Path | None = None,
) -> ServiceHostRegistrationResult:
    """Register this process as a live host, refusing a second one.

    The check and the registration happen under one registry-wide lock, so
    two hosts starting at once cannot both miss each other.
    """
    directory = _service_host_registry_dir() if registry_dir is None else registry_dir
    pid = os.getpid()
    entry = _ServiceHostRegistryEntry(
        pid=pid,
        identity=process_identity_token(pid),
        sase_home=str(sase_home() if home is None else home),
        unit=unit,
        agent_name=agent_name,
        registered_at=time.time(),
    )
    _ensure_private_dir(directory)
    with _registry_lock(directory):
        others = tuple(other for other in _live_entries(directory) if other.pid != pid)
        if others and not allow_second_reason:
            return ServiceHostRegistrationResult(
                registration=None,
                others=others,
                refused=True,
                message=_second_host_refusal_message(others),
            )
        registration = _write_entry(directory, entry)
    message = None
    if others:
        message = (
            "warning: starting a second service host on this account because "
            f"{SERVICE_ALLOW_SECOND_HOST_ENV}='{allow_second_reason}'; already "
            f"running: {'; '.join(other.describe() for other in others)}"
        )
    return ServiceHostRegistrationResult(
        registration=registration, others=others, message=message
    )


def _second_host_refusal_message(others: Sequence[_ServiceHostRegistryEntry]) -> str:
    """Name each live host, how to stop it, and the override."""
    lines = [
        "sase service run: refusing to start a second service host on this "
        "account; already running:"
    ]
    for other in others:
        lines.append(f"  {other.describe()}")
        lines.append(f"    stop it with: {_stop_command(other.unit, other.pid)}")
    lines.append(
        f"Set {SERVICE_ALLOW_SECOND_HOST_ENV}='<reason>' to run both deliberately."
    )
    return "\n".join(lines)


def _live_service_hosts(
    registry_dir: Path | None = None,
) -> list[_ServiceHostRegistryEntry]:
    """Return every live registered host, reaping stale entries."""
    directory = _service_host_registry_dir() if registry_dir is None else registry_dir
    if not directory.is_dir():
        return []
    return list(_live_entries(directory))


def current_host_unit(environ: Mapping[str, str] | None = None) -> str | None:
    """Return the native unit or scope that runs this host, if any."""
    env = os.environ if environ is None else environ
    configured = (env.get("SASE_SERVICE_UNIT") or "").strip()
    if configured:
        return configured
    return process_systemd_unit(os.getpid())


def other_service_hosts(
    *,
    current_pid: int | None,
    home: Path | None = None,
    registry_dir: Path | None = None,
    runner: Callable[[Sequence[str]], CommandResult] | None = None,
) -> list[OtherServiceHost]:
    """Return live hosts other than *current_pid*, the current home's host.

    Sources are the account registry and the ``sase-service-*`` transient
    scopes systemd still runs, which also catches hosts from releases that
    predate the registry.
    """
    current_home = str(sase_home() if home is None else home)
    try:
        entries = _live_service_hosts(registry_dir)
    except OSError:
        entries = []
    known_units: set[str] = set()
    if current_pid is not None:
        current_unit = process_systemd_unit(current_pid)
        if current_unit:
            known_units.add(current_unit)
    others: list[OtherServiceHost] = []
    for entry in entries:
        if entry.unit:
            known_units.add(entry.unit)
        if entry.pid == current_pid:
            continue
        others.append(
            OtherServiceHost(
                source="registry",
                pid=entry.pid,
                sase_home=entry.sase_home,
                home_differs=_same_path(entry.sase_home, current_home) is False,
                unit=entry.unit,
                agent_name=entry.agent_name,
                stop_command=_stop_command(entry.unit, entry.pid),
            )
        )
    for unit in _systemd_service_scopes(runner):
        if unit in known_units:
            continue
        others.append(
            OtherServiceHost(
                source="systemd",
                pid=None,
                sase_home=None,
                home_differs=None,
                unit=unit,
                agent_name=None,
                stop_command=_stop_command(unit, None),
            )
        )
    return others


def _is_service_host_unit(unit: str | None) -> bool:
    """Return whether *unit* exists only to run a service host."""
    if not unit:
        return False
    if unit == SASE_SERVICE_UNIT:
        return True
    if unit.startswith(SERVICE_SCOPE_UNIT_PREFIX) and unit.endswith(".scope"):
        return True
    # Home-scoped native units are ``sase-<suffix>.service``.
    return unit.startswith("sase-") and unit.endswith(".service")


def _stop_command(unit: str | None, pid: int | None) -> str:
    if unit and _is_service_host_unit(unit):
        return f"systemctl --user stop {unit}"
    if pid is not None:
        return f"kill {pid}"
    return "sase service stop"


def _same_path(left: str, right: str) -> bool | None:
    try:
        return Path(left).expanduser().resolve() == Path(right).expanduser().resolve()
    except (OSError, RuntimeError):
        return None


def _systemd_service_scopes(
    runner: Callable[[Sequence[str]], CommandResult] | None,
) -> list[str]:
    if sys.platform != "linux":
        return []
    run = runner
    if run is None:
        if shutil.which("systemctl") is None:
            return []
        from sase.service.platform_runner import default_runner

        def run(argv: Sequence[str]) -> CommandResult:
            return default_runner(argv, timeout=_SYSTEMCTL_TIMEOUT_SECONDS)

    result = run(
        [
            "systemctl",
            "--user",
            "list-units",
            "--plain",
            "--no-legend",
            "--no-pager",
            f"{SERVICE_SCOPE_UNIT_PREFIX}*",
        ]
    )
    if result.returncode != 0:
        return []
    units: list[str] = []
    for line in result.stdout.splitlines():
        fields = line.split()
        if len(fields) < 4:
            continue
        unit, active = fields[0], fields[2]
        if unit.startswith(SERVICE_SCOPE_UNIT_PREFIX) and active == "active":
            units.append(unit)
    return units


def _live_entries(directory: Path) -> Iterator[_ServiceHostRegistryEntry]:
    try:
        paths = sorted(directory.glob(f"{_ENTRY_PREFIX}*{_ENTRY_SUFFIX}"))
    except OSError:
        return
    for path in paths:
        entry = _read_entry(path)
        if entry is not None and _entry_live(entry, path):
            yield entry
            continue
        _reap_entry(path)


def _read_entry(path: Path) -> _ServiceHostRegistryEntry | None:
    try:
        if path.stat().st_size > _ENTRY_MAX_BYTES:
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            return None
        return _ServiceHostRegistryEntry.from_wire(payload, path=path)
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _pid_exists(pid: int) -> bool:
    """Return whether *pid* exists; the entry flock covers zombies."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _entry_live(entry: _ServiceHostRegistryEntry, path: Path) -> bool:
    if entry.pid <= 0 or not _pid_exists(entry.pid):
        return False
    if not process_identity_matches(entry.pid, entry.identity):
        return False
    return _entry_lock_held(path)


def _entry_lock_held(path: Path) -> bool:
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError:
        return False
    try:
        fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
    except OSError:
        return True
    else:
        fcntl.flock(fd, fcntl.LOCK_UN)
        return False
    finally:
        os.close(fd)


def _reap_entry(path: Path) -> None:
    """Remove a stale entry, but never one whose holder is still alive."""
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        os.close(fd)
        return
    try:
        if os.fstat(fd).st_ino == path.stat().st_ino:
            path.unlink(missing_ok=True)
    except OSError:
        pass
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def _write_entry(
    directory: Path, entry: _ServiceHostRegistryEntry
) -> _ServiceHostRegistration:
    """Write and flock the entry before it becomes visible under its name."""
    start = entry.identity.rpartition(":")[2] or "x"
    path = directory / f"{_ENTRY_PREFIX}{entry.pid}-{start}{_ENTRY_SUFFIX}"
    fd, temp_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(directory)
    )
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        payload = json.dumps(entry.to_wire(), sort_keys=True).encode("utf-8")
        os.write(fd, payload + b"\n")
        os.fsync(fd)
        os.replace(temp_name, path)
    except BaseException:
        os.close(fd)
        Path(temp_name).unlink(missing_ok=True)
        raise
    return _ServiceHostRegistration(fd, path)


def _ensure_private_dir(directory: Path) -> None:
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    if directory.stat().st_uid != os.getuid():
        raise PermissionError(f"service host registry {directory} is not owned by you")


@contextmanager
def _registry_lock(directory: Path) -> Generator[None]:
    fd = os.open(directory / _REGISTRY_LOCK_NAME, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)


def _optional_text(value: object) -> str | None:
    text = "" if value is None else str(value).strip()
    return text or None


__all__ = [
    "SERVICE_ALLOW_SECOND_HOST_ENV",
    "SERVICE_HOST_REGISTRY_DIR_ENV",
    "SERVICE_SCOPE_UNIT_PREFIX",
    "OtherServiceHost",
    "ServiceHostRegistrationResult",
    "current_host_unit",
    "other_service_hosts",
    "register_service_host",
]
