"""Local executable snapshots and macOS TCC host facts for sudo requests."""

from __future__ import annotations

import errno
import hashlib
import os
import stat
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SNAPSHOT_KIND = "sase_sudo_executable_snapshot"
SNAPSHOT_SCHEMA_VERSION = 1
_TCC_DB = Path("/Library/Application Support/com.apple.TCC/TCC.db")
_SHA256_CHUNK = 1024 * 1024

TccProbe = Callable[[], None]


@dataclass(frozen=True)
class ExecutableSnapshot:
    """One per-path snapshot result from the execution host."""

    path: str
    sha256: str | None = None
    error_code: str | None = None
    message: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "error_code": self.error_code,
            "message": self.message,
            "path": self.path,
            "sha256": self.sha256,
        }


def snapshot_executable(path: str) -> ExecutableSnapshot:
    """Return the SHA-256 snapshot of *path*, or a structured error."""
    location = Path(path)
    if not location.is_absolute():
        return ExecutableSnapshot(
            path=path,
            error_code="unsnapshotshotted_executable",
            message="sudo command executables must be absolute paths",
        )
    try:
        st = location.stat()
    except OSError as exc:
        return ExecutableSnapshot(
            path=path,
            error_code="unsnapshotshotted_executable",
            message=f"cannot snapshot executable: {exc}",
        )
    if not stat.S_ISREG(st.st_mode):
        return ExecutableSnapshot(
            path=path,
            error_code="unsnapshotshotted_executable",
            message="sudo command executable must be a regular file",
        )
    if os.access(location, os.W_OK):
        return ExecutableSnapshot(
            path=path,
            error_code="agent_writable_executable",
            message="sudo command executable is writable by this agent",
        )
    digest = hashlib.sha256()
    with location.open("rb") as handle:
        for block in iter(lambda: handle.read(_SHA256_CHUNK), b""):
            digest.update(block)
    return ExecutableSnapshot(path=path, sha256=digest.hexdigest())


def host_facts(
    *,
    platform: str | None = None,
    tcc_probe: TccProbe | None = None,
) -> dict[str, Any]:
    """Return platform facts, including a macOS Full Disk Access probe."""
    plat = sys.platform if platform is None else platform
    if plat != "darwin":
        return {"full_disk_access": None, "platform": plat}
    probe = _default_tcc_probe if tcc_probe is None else tcc_probe
    try:
        probe()
    except PermissionError as exc:
        if exc.errno == errno.EPERM:
            return {"full_disk_access": False, "platform": plat}
        return {"full_disk_access": None, "platform": plat}
    except OSError:
        return {"full_disk_access": None, "platform": plat}
    return {"full_disk_access": True, "platform": plat}


def executable_snapshot_payload(paths: Sequence[str]) -> dict[str, Any]:
    """Return the target-side JSON object for ``sase sudo exec --snapshot``."""
    return {
        "executables": [snapshot_executable(path).to_dict() for path in paths],
        "host_facts": host_facts(),
        "kind": SNAPSHOT_KIND,
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
    }


def tcc_warning(target_payload: Mapping[str, Any] | None) -> str | None:
    """Return the shared Full Disk Access warning, or ``None`` when it does not apply."""
    facts = _snapshot_host_facts(target_payload)
    if facts is None:
        return None
    if facts.get("platform") != "darwin" or facts.get("full_disk_access") is not False:
        return None
    remote = bool(
        target_payload.get("remote") if isinstance(target_payload, Mapping) else False
    )
    if remote:
        host = _target_host_label(target_payload)
        subject = f"SSH sessions on {host} lack Full Disk Access"
        remedy = (
            "Enable System Settings → General → Sharing → Remote Login ⓘ → "
            '"Allow full disk access for remote users" before approving.'
        )
    else:
        subject = "this terminal lacks Full Disk Access"
        remedy = (
            "Enable Full Disk Access for this terminal in System Settings → "
            "Privacy & Security → Full Disk Access before approving."
        )
    return (
        f"macOS TCC: {subject}. Root writes to protected paths "
        '(for example /etc/postfix) will fail with "Operation not permitted". '
        f"{remedy}"
    )


def tcc_failure_hint(
    target_payload: Mapping[str, Any] | None,
    ledger: Sequence[Any] | None,
) -> str | None:
    """Return a successor hint when a darwin sudo ledger shows TCC denials."""
    facts = _snapshot_host_facts(target_payload)
    if facts is None or facts.get("platform") != "darwin":
        return None
    failed_ids = [
        str(entry.get("id"))
        for entry in ledger or ()
        if isinstance(entry, Mapping)
        and entry.get("status") == "failed"
        and "Operation not permitted" in str(entry.get("output_tail") or "")
        and entry.get("id")
    ]
    if not failed_ids:
        return None
    certainty = (
        "is macOS TCC"
        if facts.get("full_disk_access") is False
        else "is likely macOS TCC"
    )
    names = ", ".join(failed_ids)
    return (
        f"Command(s) {names} failed with Operation not permitted. "
        f"This {certainty} (SSH lacks Full Disk Access), not SIP and not a "
        "sase fault. Ask Bryan to enable System Settings → General → Sharing → "
        'Remote Login ⓘ → "Allow full disk access for remote users". '
        "Do not work around this denial."
    )


def _default_tcc_probe() -> None:
    with _TCC_DB.open("rb") as handle:
        handle.read(1)


def _snapshot_host_facts(
    target_payload: Mapping[str, Any] | None,
) -> Mapping[str, Any] | None:
    if not isinstance(target_payload, Mapping):
        return None
    snapshot = target_payload.get("snapshot")
    if not isinstance(snapshot, Mapping):
        return None
    facts = snapshot.get("host_facts")
    return facts if isinstance(facts, Mapping) else None


def _target_host_label(target_payload: Mapping[str, Any] | None) -> str:
    if not isinstance(target_payload, Mapping):
        return "the target"
    requested = target_payload.get("requested_machine")
    host = target_payload.get("host")
    if isinstance(requested, str) and requested.strip():
        return requested.strip()
    if isinstance(host, str) and host.strip():
        return host.strip()
    return "the target"


__all__ = [
    "SNAPSHOT_KIND",
    "SNAPSHOT_SCHEMA_VERSION",
    "ExecutableSnapshot",
    "executable_snapshot_payload",
    "host_facts",
    "snapshot_executable",
    "tcc_failure_hint",
    "tcc_warning",
]
