"""SASE-owned sudo handoff directories, sealed manifests, and output IO."""

from __future__ import annotations

import json
import os
import shutil
import stat
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any, BinaryIO, TextIO

from sase.core.paths import sase_subdir
from sase.notification_gates.durability import fsync_dir
from sase.notification_gates.models import GateError
from sase.notification_gates.paths import open_regular_nofollow
from sase.sudo.execution_state import (
    HANDOFF_DIR_MODE,
    HANDOFF_FILE_MODE,
    LEDGER_FILENAME,
    LOG_FILENAME,
    MANIFEST_FILENAME,
    STOP_FILENAME,
    SUDO_EXEC_STARTED_KIND,
)

_GATE_ID_MAX_BYTES = 128
_HANDOFF_ROOT_NAME = "exec"
_OUTPUT_CHUNK_BYTES = 64 * 1024
_SUDO_STATE_SUBDIR = "sudo"


def _sudo_exec_root() -> Path:
    """Return the SASE-owned root for detached sudo handoff directories."""
    return sase_subdir(_SUDO_STATE_SUBDIR) / _HANDOFF_ROOT_NAME


def _handoff_dir_for(gate_id: str) -> Path:
    """Return the per-attempt handoff directory for *gate_id*."""
    return _sudo_exec_root() / _validated_gate_id(gate_id)


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
    "cleanup_handoff",
    "copy_output_log",
    "create_handoff_dir",
    "handshake_from_runner_payload",
    "read_handoff_ledger",
    "write_stop_file",
]
