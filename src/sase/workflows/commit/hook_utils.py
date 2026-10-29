"""Shared helpers for commit hook modules."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
import threading
from pathlib import Path
from typing import BinaryIO, Literal

HOOK_LOG_DIRNAME = "commit_hooks"
HOOK_LOG_CAP_BYTES = 1_048_576
HOOK_TAIL_CAP_BYTES = 16_384
HOOK_READ_CHUNK_BYTES = 65_536
HOOK_READER_JOIN_SECONDS = 1.0

__all__ = [
    "HOOK_LOG_DIRNAME",
    "HOOK_LOG_CAP_BYTES",
    "HOOK_TAIL_CAP_BYTES",
    "HOOK_READ_CHUNK_BYTES",
    "HOOK_READER_JOIN_SECONDS",
    "decode_tail",
    "drain_stream",
    "get_repo_root",
    "hook_log_root",
    "local_config_path_for_repo_root",
    "normalize_path",
    "repo_digest",
    "write_json_atomic",
]


def local_config_path_for_repo_root(repo_root: str) -> Path:
    """Return the project-local config file for *repo_root*.

    Canonical ``sase/sase.yml`` is preferred while root-level ``sase.yml``
    remains readable for compatibility. Falls back to *repo_root* itself
    (which the YAML loader reads as missing) when neither file exists, so
    callers keep default behavior without extra existence checks.
    """
    root = Path(repo_root).expanduser()
    for candidate in (root / "sase" / "sase.yml", root / "sase.yml"):
        try:
            if candidate.is_file():
                return candidate
        except OSError:
            continue
    return root


def get_repo_root(cwd: str) -> str:
    """Return the repository root directory, or an empty string on failure."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            cwd=cwd,
            check=False,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return ""


def hook_log_root() -> Path:
    """Return the directory holding per-run commit-hook evidence files."""
    artifacts_dir = os.environ.get("SASE_ARTIFACTS_DIR", "").strip()
    if artifacts_dir:
        return Path(artifacts_dir) / HOOK_LOG_DIRNAME
    owner = str(getattr(os, "getuid", lambda: "user")())
    return Path(tempfile.gettempdir()) / "sase-commit-hooks" / owner


def normalize_path(path: str) -> str:
    """Normalize *path* for evidence records and digest computation."""
    return os.path.normcase(os.path.abspath(os.path.expanduser(path)))


def repo_digest(repo_root: str) -> str:
    """Return a short stable digest identifying *repo_root* in file stems."""
    return hashlib.sha256(normalize_path(repo_root).encode("utf-8")).hexdigest()[:12]


def decode_tail(value: bytearray) -> str:
    """Decode a captured output tail, tolerating undecodable bytes."""
    return bytes(value).decode("utf-8", errors="replace")


def write_json_atomic(path: Path, payload: dict[str, object]) -> None:
    """Write *payload* as JSON, atomically replacing *path*."""
    tmp_path = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        tmp_path.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(tmp_path, path)
    finally:
        try:
            tmp_path.unlink()
        except FileNotFoundError:
            pass


def _write_bytes_atomic(path: Path, payload: bytes) -> None:
    """Write *payload* bytes, atomically replacing *path*."""
    tmp_path = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        tmp_path.write_bytes(payload)
        os.replace(tmp_path, path)
    finally:
        try:
            tmp_path.unlink()
        except FileNotFoundError:
            pass


def drain_stream(
    stream: BinaryIO | None,
    name: Literal["stdout", "stderr"],
    log_path: Path,
    tail_path: Path,
    lock: threading.Lock,
    written: dict[str, int],
    truncated: dict[str, bool],
    tails: dict[str, bytearray],
) -> None:
    """Drain *stream* into a size-capped log plus a rolling tail file."""
    if stream is None:
        return
    try:
        while True:
            chunk = stream.read(HOOK_READ_CHUNK_BYTES)
            if not chunk:
                break
            with lock:
                _append_bounded_log(log_path, name, chunk, written, truncated)
                tails[name].extend(chunk)
                if len(tails[name]) > HOOK_TAIL_CAP_BYTES:
                    del tails[name][: len(tails[name]) - HOOK_TAIL_CAP_BYTES]
                _write_bytes_atomic(tail_path, bytes(tails[name]))
    except OSError:
        return
    finally:
        try:
            stream.close()
        except OSError:
            pass


def _append_bounded_log(
    path: Path,
    name: Literal["stdout", "stderr"],
    chunk: bytes,
    written: dict[str, int],
    truncated: dict[str, bool],
) -> None:
    if truncated[name]:
        return
    room = HOOK_LOG_CAP_BYTES - written[name]
    with path.open("ab") as handle:
        if len(chunk) <= room:
            handle.write(chunk)
            written[name] += len(chunk)
            return
        if room > 0:
            handle.write(chunk[:room])
            written[name] += room
        marker = (
            f"\n[commit hook {name} log truncated after {HOOK_LOG_CAP_BYTES} bytes; "
            "see the .tail file for recent output]\n"
        ).encode()
        handle.write(marker)
        truncated[name] = True
