"""Detached sudo execution records, handoff directories, and liveness."""

from __future__ import annotations

import json
import os
import shutil
import stat
import sys
import tempfile
from collections.abc import Mapping
from contextlib import AbstractContextManager
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, BinaryIO, TextIO

from sase.core.paths import sase_subdir
from sase.core.process_identity import process_identity_matches
from sase.notification_gates.durability import (
    atomic_write_json,
    file_lock,
    fsync_dir,
    read_json_object,
)
from sase.notification_gates.models import GateError
from sase.notification_gates.paths import open_regular_nofollow
from sase.procs.identity import supervisor_is_alive
from sase.procs.models import ACTIVE_PROC_STATUSES
from sase.procs.store import get_proc

EXECUTION_STATE_FILENAME = "execution-state.json"
EXECUTION_STATE_SCHEMA_VERSION = 1
HANDOFF_DIR_MODE = 0o700
HANDOFF_FILE_MODE = 0o600
LEDGER_FILENAME = "ledger.json"
LOG_FILENAME = "output.log"
MANIFEST_FILENAME = "manifest.json"
RESPONSE_LOCK_FILENAME = ".response.lock"
STOP_FILENAME = "stop"
SUDO_EXEC_STARTED_KIND = "sudo_exec_started"
_GATE_ID_MAX_BYTES = 128
_HANDOFF_ROOT_NAME = "exec"
_OUTPUT_CHUNK_BYTES = 64 * 1024
_SUDO_STATE_SUBDIR = "sudo"


@dataclass(frozen=True)
class SudoExecutionState:
    """Versioned in-flight detached sudo execution record."""

    gate_id: str
    selected_command_ids: tuple[str, ...]
    manifest_sha256: str
    handoff_dir: str
    handshake: dict[str, Any] | None = None
    finalize_proc_id: str | None = None
    target_kind: str = "local"
    target_host: str | None = None
    startup_state: str = "legacy"
    operation_payload_digest: str | None = None
    authorization_id: str | None = None
    remote_handoff: dict[str, str] | None = None
    schema_version: int = EXECUTION_STATE_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "authorization_id": self.authorization_id,
            "finalize_proc_id": self.finalize_proc_id,
            "gate_id": self.gate_id,
            "handoff_dir": self.handoff_dir,
            "handshake": None if self.handshake is None else dict(self.handshake),
            "manifest_sha256": self.manifest_sha256,
            "operation_payload_digest": self.operation_payload_digest,
            "schema_version": self.schema_version,
            "selected_command_ids": list(self.selected_command_ids),
            "startup_state": self.startup_state,
            "target_host": self.target_host,
            "target_kind": self.target_kind,
        }
        if self.remote_handoff is not None:
            payload["remote_handoff"] = dict(self.remote_handoff)
        return payload


@dataclass(frozen=True)
class _SudoExecutionProjection:
    """Live executing-state projection for sudo show/list."""

    executing: bool
    finalize_proc_id: str | None = None
    executor_pid: int | None = None
    liveness: str = "dead"


def _sudo_exec_root() -> Path:
    """Return the SASE-owned root for detached sudo handoff directories."""
    return sase_subdir(_SUDO_STATE_SUBDIR) / _HANDOFF_ROOT_NAME


def _handoff_dir_for(gate_id: str) -> Path:
    """Return the per-attempt handoff directory for *gate_id*."""
    return _sudo_exec_root() / _validated_gate_id(gate_id)


def _execution_state_path(bundle_root: Path) -> Path:
    """Return the execution-state path co-located with a sudo gate bundle."""
    return Path(bundle_root) / EXECUTION_STATE_FILENAME


def execution_lock(bundle_root: Path) -> AbstractContextManager[None]:
    """Serialize in-flight execution-record transitions on the gate bundle."""
    return file_lock(Path(bundle_root) / RESPONSE_LOCK_FILENAME)


def load_execution_state(bundle_root: Path) -> SudoExecutionState | None:
    """Return the execution record, or ``None`` when it is absent."""
    path = _execution_state_path(bundle_root)
    if not path.exists():
        return None
    try:
        payload = read_json_object(path)
    except GateError:
        raise GateError(
            "invalid_sudo_execution_state",
            str(path),
            "sudo execution-state JSON is invalid",
        ) from None
    return _state_from_payload(payload, path=path)


def write_execution_state(bundle_root: Path, state: SudoExecutionState) -> None:
    """Atomically write a permission-safe execution record."""
    path = _execution_state_path(bundle_root)
    atomic_write_json(path, state.to_dict())
    os.chmod(path, HANDOFF_FILE_MODE)


def clear_execution_state(bundle_root: Path) -> None:
    """Remove the execution record when present."""
    path = _execution_state_path(bundle_root)
    try:
        path.unlink()
    except FileNotFoundError:
        return
    fsync_dir(path.parent)


def create_handoff_dir(
    gate_id: str,
    manifest: Mapping[str, Any],
) -> Path:
    """Create a user-owned ``0700`` handoff directory and sealed manifest."""
    root = _sudo_exec_root()
    root.mkdir(parents=True, exist_ok=True)
    os.chmod(root, HANDOFF_DIR_MODE)
    path = _handoff_dir_for(gate_id)
    if path.exists() or path.is_symlink():
        cleanup_handoff(path)
    if path.exists() or path.is_symlink():
        raise GateError(
            "unowned_sudo_handoff",
            str(path),
            "could not replace the existing sudo handoff path",
        )
    path.mkdir(mode=HANDOFF_DIR_MODE)
    os.chmod(path, HANDOFF_DIR_MODE)
    _reject_symlink_components(path, stop=root)
    _write_sealed_manifest(path / MANIFEST_FILENAME, manifest)
    return path


def claim_execution_record(
    bundle_root: Path, *, gate_id: str
) -> SudoExecutionState | None:
    """Return a live record, or clear a stale one and return ``None``.

    A live record (finalize proc or identity-matched executor still running)
    is left in place so the caller can refuse a second approval. A record is
    stale only when both the proc and the executor are dead.
    """
    state = load_execution_state(bundle_root)
    if state is None:
        return None
    if state.gate_id != gate_id:
        raise GateError(
            "invalid_sudo_execution_state",
            "gate_id",
            "sudo execution record does not match this gate",
        )
    if execution_is_live(state):
        return state
    notice = f"cleared stale sudo execution record for {gate_id}"
    if state.handoff_dir:
        cleanup_handoff(Path(state.handoff_dir))
    clear_execution_state(bundle_root)
    print(f"sase sudo: {notice}", file=sys.stderr)
    return None


def execution_is_live(state: SudoExecutionState) -> bool:
    """Return whether the attempt still owns the gate.

    This is intentionally conservative: unknown executor ownership is still
    live for duplicate-answer purposes. Use ``execution_liveness`` when the
    distinction matters.
    """
    return execution_liveness(state)["classification"] != "dead"


def execution_liveness(state: SudoExecutionState) -> dict[str, Any]:
    """Return the Rust-classified live/dead/unknown attempt decision."""
    from sase.sudo.core import DEFAULT_SUDO_CORE

    try:
        return DEFAULT_SUDO_CORE.classify_attempt_liveness(
            state.to_dict(),
            _attempt_liveness_facts(state),
        )
    except GateError:
        if _proc_is_live(state.finalize_proc_id) or executor_is_live(state.handshake):
            return {
                "schema_version": EXECUTION_STATE_SCHEMA_VERSION,
                "classification": "live",
                "reason": "legacy Python liveness fallback",
            }
        if state.startup_state == "legacy":
            return {
                "schema_version": EXECUTION_STATE_SCHEMA_VERSION,
                "classification": "dead",
                "reason": "legacy Python liveness fallback",
            }
        return {
            "schema_version": EXECUTION_STATE_SCHEMA_VERSION,
            "classification": "unknown",
            "reason": "invalid attempt state needs recovery",
        }


def _proc_is_live(proc_id: str | None) -> bool:
    """Return whether *proc_id* names an active supervised proc."""
    if not proc_id:
        return False
    proc = get_proc(proc_id)
    if proc is None or proc.status not in ACTIVE_PROC_STATUSES:
        return False
    if proc.status == "pending":
        return True
    return supervisor_is_alive(proc.pid, proc.supervisor_id)


def executor_is_live(handshake: Mapping[str, Any] | None) -> bool:
    """Return whether the handshake still names a live executor process."""
    if handshake is None:
        return False
    pid = handshake.get("executor_pid")
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        return False
    if not _pid_is_running(pid):
        return False
    return process_identity_matches(pid, handshake.get("executor_identity"))


def live_execution_error(state: SudoExecutionState) -> GateError:
    """Return the duplicate-approval error naming the live or unknown owner."""
    proc_id = state.finalize_proc_id or "unknown"
    liveness = execution_liveness(state)["classification"]
    return GateError(
        "execution_in_progress",
        proc_id,
        (
            f"sudo execution ownership is {liveness} for this gate "
            f"(finalize proc {proc_id}); the gate remains pending"
        ),
    )


def project_execution(bundle_root: Path) -> _SudoExecutionProjection:
    """Project live executing state without mutating the record."""
    state = load_execution_state(bundle_root)
    if state is None:
        return _SudoExecutionProjection(executing=False)
    liveness = execution_liveness(state)
    classification = str(liveness.get("classification") or "unknown")
    if classification == "dead":
        return _SudoExecutionProjection(executing=False)
    handshake = state.handshake or {}
    pid = handshake.get("executor_pid")
    return _SudoExecutionProjection(
        executing=True,
        finalize_proc_id=state.finalize_proc_id,
        executor_pid=pid
        if (
            state.target_kind == "local"
            and classification == "live"
            and isinstance(pid, int)
            and not isinstance(pid, bool)
        )
        else None,
        liveness=classification,
    )


def recover_dead_attempt(bundle_root: Path) -> None:
    """Clear a record and handoff when neither proc nor executor is live."""
    state = load_execution_state(bundle_root)
    if state is None or execution_liveness(state)["classification"] != "dead":
        return
    if not _cleanup_remote_handoff(state):
        return
    if state.handoff_dir:
        cleanup_handoff(Path(state.handoff_dir))
    clear_execution_state(bundle_root)


def abandon_unstarted_attempt(bundle_root: Path) -> None:
    """Drop a proven pre-spawn attempt, including any allocated remote paths."""
    state = load_execution_state(bundle_root)
    if state is None:
        return
    write_execution_state(bundle_root, replace(state, startup_state="terminal"))
    _cleanup_remote_handoff(state)
    if state.handoff_dir:
        cleanup_handoff(Path(state.handoff_dir))
    clear_execution_state(bundle_root)


def _cleanup_remote_handoff(state: SudoExecutionState) -> bool:
    """Return True when remote cleanup completed or is unnecessary."""
    if (
        state.target_kind != "remote"
        or not state.target_host
        or not state.remote_handoff
    ):
        return True
    from sase.sudo.ssh import cleanup_remote_sudo

    return cleanup_remote_sudo(state.target_host, state.remote_handoff)


def write_stop_file(handoff_dir: Path) -> None:
    """Create the executor stop file inside a SASE-owned handoff directory."""
    owned = _assert_owned_handoff(handoff_dir)
    path = owned / STOP_FILENAME
    flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags, HANDOFF_FILE_MODE)
    try:
        os.fchmod(fd, HANDOFF_FILE_MODE)
        os.fsync(fd)
    finally:
        os.close(fd)


def copy_output_log(
    log_path: Path,
    *,
    offset: int,
    dest: BinaryIO | TextIO,
) -> int:
    """Copy newly written ``output.log`` bytes to *dest* and return the offset."""
    if offset < 0:
        offset = 0
    if not log_path.exists():
        return offset
    fd = open_regular_nofollow(log_path)
    try:
        os.lseek(fd, offset, os.SEEK_SET)
        while True:
            chunk = os.read(fd, _OUTPUT_CHUNK_BYTES)
            if not chunk:
                break
            _write_output_chunk(dest, chunk)
            offset += len(chunk)
    finally:
        os.close(fd)
    _flush_output(dest)
    return offset


def read_handoff_ledger(handoff_dir: Path) -> dict[str, Any] | None:
    """Return ``ledger.json`` when it is a regular owned file, else ``None``."""
    owned = _assert_owned_handoff(handoff_dir)
    path = owned / LEDGER_FILENAME
    if not path.exists():
        return None
    fd = open_regular_nofollow(path)
    try:
        chunks: list[bytes] = []
        while True:
            chunk = os.read(fd, _OUTPUT_CHUNK_BYTES)
            if not chunk:
                break
            chunks.append(chunk)
    finally:
        os.close(fd)
    try:
        value = json.loads(b"".join(chunks).decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GateError(
            "invalid_sudo_ledger",
            str(path),
            f"invalid sudo ledger JSON: {exc}",
        ) from exc
    if not isinstance(value, dict):
        raise GateError(
            "invalid_sudo_ledger",
            str(path),
            "sudo ledger must be an object",
        )
    return value


def cleanup_handoff(path: Path) -> None:
    """Delete a validated, SASE-owned handoff directory; ignore unowned paths."""
    try:
        owned = _assert_owned_handoff(path, must_exist=False)
    except GateError:
        return
    if not owned.exists():
        return
    shutil.rmtree(owned, ignore_errors=False)
    parent = owned.parent
    if parent.exists():
        fsync_dir(parent)


def _assert_owned_handoff(path: Path, *, must_exist: bool = True) -> Path:
    """Return *path* if it is a user-owned directory under the sudo exec root."""
    root = _sudo_exec_root()
    candidate = path.expanduser()
    if candidate.is_symlink():
        raise GateError(
            "unowned_sudo_handoff",
            str(path),
            "sudo handoff path must not be a symlink",
        )
    _containment_or_raise(candidate, root=root)
    _reject_symlink_components(candidate, stop=root)
    if not candidate.exists():
        if must_exist:
            raise GateError(
                "missing_sudo_handoff",
                str(path),
                "sudo handoff directory is missing",
            )
        return candidate
    try:
        metadata = candidate.lstat()
    except OSError as exc:
        raise GateError(
            "unowned_sudo_handoff",
            str(path),
            f"cannot stat sudo handoff directory: {exc}",
        ) from exc
    if not stat.S_ISDIR(metadata.st_mode):
        raise GateError(
            "unowned_sudo_handoff",
            str(path),
            "sudo handoff path is not a directory",
        )
    if metadata.st_uid != os.getuid():
        raise GateError(
            "unowned_sudo_handoff",
            str(path),
            "sudo handoff directory is not owned by the current user",
        )
    return candidate


def handshake_from_runner_payload(value: Mapping[str, Any]) -> bool:
    """Return whether *value* looks like a started-handshake document."""
    return str(value.get("kind") or "") == SUDO_EXEC_STARTED_KIND


def _state_from_payload(
    payload: Mapping[str, Any], *, path: Path
) -> SudoExecutionState:
    version = payload.get("schema_version")
    if version != EXECUTION_STATE_SCHEMA_VERSION:
        raise GateError(
            "invalid_sudo_execution_state",
            str(path),
            "unsupported sudo execution-state schema",
        )
    gate_id = payload.get("gate_id")
    handoff_dir = payload.get("handoff_dir")
    digest = payload.get("manifest_sha256")
    selected = payload.get("selected_command_ids")
    if not isinstance(gate_id, str) or not gate_id:
        raise GateError(
            "invalid_sudo_execution_state",
            "gate_id",
            "sudo execution record is missing gate_id",
        )
    if not isinstance(handoff_dir, str) or not handoff_dir:
        raise GateError(
            "invalid_sudo_execution_state",
            "handoff_dir",
            "sudo execution record is missing handoff_dir",
        )
    if not isinstance(digest, str) or not digest:
        raise GateError(
            "invalid_sudo_execution_state",
            "manifest_sha256",
            "sudo execution record is missing manifest_sha256",
        )
    if not isinstance(selected, list) or any(
        not isinstance(item, str) for item in selected
    ):
        raise GateError(
            "invalid_sudo_execution_state",
            "selected_command_ids",
            "sudo execution record command ids must be strings",
        )
    handshake = payload.get("handshake")
    if handshake is not None and not isinstance(handshake, dict):
        raise GateError(
            "invalid_sudo_execution_state",
            "handshake",
            "sudo execution record handshake must be an object",
        )
    proc_id = payload.get("finalize_proc_id")
    if proc_id is not None and not isinstance(proc_id, str):
        raise GateError(
            "invalid_sudo_execution_state",
            "finalize_proc_id",
            "sudo execution record finalize_proc_id must be a string",
        )
    target_kind = payload.get("target_kind")
    startup_state = payload.get("startup_state")
    target_host = payload.get("target_host")
    operation_payload_digest = payload.get("operation_payload_digest")
    authorization_id = payload.get("authorization_id")
    if target_kind is None:
        target_kind = "unknown"
    if startup_state is None:
        startup_state = "unknown"
    if target_kind not in {"local", "remote", "unknown"}:
        raise GateError(
            "invalid_sudo_execution_state",
            "target_kind",
            "sudo execution record target_kind is invalid",
        )
    if startup_state not in {
        "legacy",
        "reserved",
        "authenticating",
        "starting",
        "started",
        "settling",
        "settled",
        "terminal",
        "unknown",
    }:
        raise GateError(
            "invalid_sudo_execution_state",
            "startup_state",
            "sudo execution record startup_state is invalid",
        )
    if target_host is not None and not isinstance(target_host, str):
        raise GateError(
            "invalid_sudo_execution_state",
            "target_host",
            "sudo execution record target_host must be a string",
        )
    if operation_payload_digest is not None and not isinstance(
        operation_payload_digest, str
    ):
        raise GateError(
            "invalid_sudo_execution_state",
            "operation_payload_digest",
            "sudo execution record operation_payload_digest must be a string",
        )
    if authorization_id is not None and not isinstance(authorization_id, str):
        raise GateError(
            "invalid_sudo_execution_state",
            "authorization_id",
            "sudo execution record authorization_id must be a string",
        )
    remote_handoff = _remote_handoff_from_payload(
        payload.get("remote_handoff"),
        target_kind=str(target_kind),
        target_host=target_host if isinstance(target_host, str) else None,
    )
    return SudoExecutionState(
        schema_version=EXECUTION_STATE_SCHEMA_VERSION,
        gate_id=gate_id,
        selected_command_ids=tuple(selected),
        manifest_sha256=digest,
        handoff_dir=handoff_dir,
        handshake=None if handshake is None else dict(handshake),
        finalize_proc_id=proc_id,
        target_kind=target_kind,
        target_host=target_host,
        startup_state=startup_state,
        operation_payload_digest=operation_payload_digest,
        authorization_id=authorization_id,
        remote_handoff=remote_handoff,
    )


_REMOTE_HANDOFF_KEYS = (
    "directory",
    "handshake",
    "ledger",
    "log",
    "manifest",
    "stop",
)


def _remote_handoff_from_payload(
    value: Any,
    *,
    target_kind: str,
    target_host: str | None,
) -> dict[str, str] | None:
    """Return validated remote path metadata, or ``None`` for legacy records."""
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise GateError(
            "invalid_sudo_execution_state",
            "remote_handoff",
            "sudo execution record remote_handoff must be an object",
        )
    if target_kind != "remote":
        raise GateError(
            "invalid_sudo_execution_state",
            "remote_handoff",
            "sudo remote handoff metadata requires target_kind remote",
        )
    if not target_host:
        raise GateError(
            "invalid_sudo_execution_state",
            "target_host",
            "sudo remote handoff metadata requires target_host",
        )
    paths: dict[str, str] = {}
    for key in _REMOTE_HANDOFF_KEYS:
        item = value.get(key)
        if not isinstance(item, str) or not item or item.endswith("/"):
            raise GateError(
                "invalid_sudo_execution_state",
                f"remote_handoff.{key}",
                "sudo remote handoff path must be a non-empty absolute path",
            )
        if not item.startswith("/") or "\x00" in item:
            raise GateError(
                "invalid_sudo_execution_state",
                f"remote_handoff.{key}",
                "sudo remote handoff path must be a safe absolute path",
            )
        parts = Path(item).parts
        if any(part in {".", ".."} for part in parts):
            raise GateError(
                "invalid_sudo_execution_state",
                f"remote_handoff.{key}",
                "sudo remote handoff path must not contain relative components",
            )
        paths[key] = item
    directory = paths["directory"]
    prefix = directory.rstrip("/") + "/"
    seen = {directory}
    for key in _REMOTE_HANDOFF_KEYS:
        if key == "directory":
            continue
        item = paths[key]
        if not item.startswith(prefix) or item == prefix:
            raise GateError(
                "invalid_sudo_execution_state",
                f"remote_handoff.{key}",
                "sudo remote handoff path must be inside the remote directory",
            )
        if item in seen:
            raise GateError(
                "invalid_sudo_execution_state",
                f"remote_handoff.{key}",
                "sudo remote handoff paths must be unique",
            )
        seen.add(item)
    return paths


def _attempt_liveness_facts(state: SudoExecutionState) -> dict[str, Any]:
    facts: dict[str, Any] = {
        "finalize_proc_live": (
            None
            if state.finalize_proc_id is None
            else _proc_is_live(state.finalize_proc_id)
        ),
        "executor_identity_matches": None,
        "executor_pid_live": None,
    }
    if state.target_kind != "local" or state.handshake is None:
        return facts
    pid = state.handshake.get("executor_pid")
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        return facts
    live = _pid_is_running(pid)
    facts["executor_pid_live"] = live
    facts["executor_identity_matches"] = (
        process_identity_matches(pid, state.handshake.get("executor_identity"))
        if live
        else False
    )
    return facts


def _write_sealed_manifest(path: Path, manifest: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    temporary_path = Path(temporary)
    try:
        os.fchmod(fd, HANDOFF_FILE_MODE)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(dict(manifest), handle, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
        os.chmod(path, HANDOFF_FILE_MODE)
        fsync_dir(path.parent)
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise


def _validated_gate_id(gate_id: str) -> str:
    if (
        not gate_id
        or len(gate_id.encode("utf-8")) > _GATE_ID_MAX_BYTES
        or "/" in gate_id
        or gate_id in {".", ".."}
        or "\x00" in gate_id
    ):
        raise GateError(
            "invalid_identifier",
            "gate_id",
            "sudo gate id is not a safe handoff directory name",
        )
    return gate_id


def _containment_or_raise(path: Path, *, root: Path) -> None:
    try:
        path.expanduser().absolute().relative_to(root.expanduser().absolute())
    except ValueError as exc:
        raise GateError(
            "unowned_sudo_handoff",
            str(path),
            "sudo handoff path is outside the SASE sudo exec directory",
        ) from exc


def _reject_symlink_components(path: Path, *, stop: Path) -> None:
    absolute = path.expanduser().absolute()
    stop_absolute = stop.expanduser().absolute()
    try:
        relative = absolute.relative_to(stop_absolute)
    except ValueError:
        return
    current = stop_absolute
    for part in relative.parts:
        current /= part
        try:
            if current.is_symlink():
                raise GateError(
                    "unowned_sudo_handoff",
                    str(current),
                    "symlinks are not allowed inside sudo handoff paths",
                )
        except OSError as exc:
            raise GateError(
                "unowned_sudo_handoff",
                str(current),
                f"cannot validate sudo handoff path: {exc}",
            ) from exc


def _pid_is_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _write_output_chunk(dest: BinaryIO | TextIO, chunk: bytes) -> None:
    buffer = getattr(dest, "buffer", None)
    if buffer is not None:
        buffer.write(chunk)
        return
    write = getattr(dest, "write", None)
    if write is None:
        return
    try:
        write(chunk)
    except TypeError:
        write(chunk.decode("utf-8", errors="replace"))


def _flush_output(dest: BinaryIO | TextIO) -> None:
    buffer = getattr(dest, "buffer", None)
    if buffer is not None:
        buffer.flush()
        return
    flush = getattr(dest, "flush", None)
    if flush is not None:
        flush()


__all__ = [
    "EXECUTION_STATE_FILENAME",
    "EXECUTION_STATE_SCHEMA_VERSION",
    "HANDOFF_DIR_MODE",
    "HANDOFF_FILE_MODE",
    "LEDGER_FILENAME",
    "LOG_FILENAME",
    "MANIFEST_FILENAME",
    "STOP_FILENAME",
    "SUDO_EXEC_STARTED_KIND",
    "SudoExecutionState",
    "abandon_unstarted_attempt",
    "claim_execution_record",
    "cleanup_handoff",
    "clear_execution_state",
    "copy_output_log",
    "create_handoff_dir",
    "execution_is_live",
    "execution_liveness",
    "execution_lock",
    "executor_is_live",
    "handshake_from_runner_payload",
    "live_execution_error",
    "load_execution_state",
    "project_execution",
    "read_handoff_ledger",
    "recover_dead_attempt",
    "write_execution_state",
    "write_stop_file",
]
