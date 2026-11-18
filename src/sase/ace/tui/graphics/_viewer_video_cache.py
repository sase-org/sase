"""Shared disk cache and metadata helpers for video frame services."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path

from sase.core.paths import ensure_sase_directory

from ._viewer_video_media import (
    VideoMetadata,
    ffprobe_metadata_command,
    parse_ffprobe_metadata,
    probe_video_metadata,
)

_VIDEO_FRAME_CACHE_SUBDIR = "cache/artifact_video"

_DEFAULT_CACHE_MAX_BYTES = 256 * 1024 * 1024

_FRAME_DIGEST_CHUNK_BYTES = 1024 * 1024

_METADATA_PROBE_TIMEOUT_SECONDS = 5.0

_DIGEST_CACHE_MAX_ENTRIES = 64

_DIGEST_CACHE: dict[tuple[str, int, int, int, int], str] = {}

_DIGEST_CACHE_LOCK = threading.Lock()


def _digest_cache_key(
    resolved: str, stat: os.stat_result
) -> tuple[str, int, int, int, int]:
    return (resolved, stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns)


def artifact_video_cache_dir(
    *,
    cache_dir: str | Path | None = None,
) -> Path:
    """Return the persistent video-frame cache directory, creating it."""

    if cache_dir is not None:
        root = Path(cache_dir).expanduser()
        root.mkdir(parents=True, exist_ok=True)
        return root
    return Path(ensure_sase_directory(_VIDEO_FRAME_CACHE_SUBDIR))


def content_digest_for_path(path: str | Path) -> str | None:
    """Return the streamed sha256 hex digest of *path*, or None when unreadable.

    Memoized per viewer process by resolved path plus ``(st_dev, st_ino,
    st_size, st_mtime_ns)``, so one open plus many exact steps hash the file
    once. A changed file (new size, mtime, or inode) re-hashes.
    """

    try:
        resolved_path = str(Path(path).expanduser())
        stat = os.stat(resolved_path)
    except OSError:
        return None
    if not os.path.isfile(resolved_path):
        return None
    key = _digest_cache_key(resolved_path, stat)
    with _DIGEST_CACHE_LOCK:
        cached = _DIGEST_CACHE.get(key)
        if cached is not None:
            return cached
    try:
        digest = hashlib.sha256()
        with open(resolved_path, "rb") as handle:
            for chunk in iter(lambda: handle.read(_FRAME_DIGEST_CHUNK_BYTES), b""):
                digest.update(chunk)
    except OSError:
        return None
    hex_digest = digest.hexdigest()
    try:
        fresh = os.stat(resolved_path)
    except OSError:
        return hex_digest
    if _digest_cache_key(resolved_path, fresh) != key:
        return hex_digest
    with _DIGEST_CACHE_LOCK:
        _DIGEST_CACHE[key] = hex_digest
        while len(_DIGEST_CACHE) > _DIGEST_CACHE_MAX_ENTRIES:
            _DIGEST_CACHE.pop(next(iter(_DIGEST_CACHE)))
    return hex_digest


def metadata_for_frame_service(
    path: str | Path,
    *,
    metadata: VideoMetadata | None = None,
    cache_dir: str | Path | None = None,
) -> VideoMetadata | None:
    """Return ffprobe metadata for the frame service, cached when possible.

    A caller-provided *metadata* wins. Otherwise the ffprobe JSON payload is
    cached under the content digest so repeated opens of one clip probe once;
    without a *cache_dir* this falls back to a live probe.
    """

    if metadata is not None:
        return metadata
    if cache_dir is None:
        return probe_video_metadata(path)
    digest = content_digest_for_path(path)
    if digest is None:
        return probe_video_metadata(path)
    root = artifact_video_cache_dir(cache_dir=cache_dir)
    cached = _read_cached_metadata_payload(root, digest)
    if cached is not None:
        return cached
    fresh = _probe_and_cache_metadata(path, root, digest)
    if fresh is not None:
        return fresh
    return None


def enforce_cache_budget(
    cache_dir: str | Path,
    *,
    max_bytes: int = _DEFAULT_CACHE_MAX_BYTES,
) -> int:
    """Evict oldest cache files until *cache_dir* fits *max_bytes*.

    Returns the evicted byte count. Best-effort: unreadable entries are
    skipped, never raised.
    """

    try:
        root = Path(cache_dir).expanduser()
        entries = [
            (path, path.stat())
            for path in root.rglob("*")
            if path.is_file() and not path.name.startswith(".tmp-")
        ]
    except OSError:
        return 0
    total = sum(stat.st_size for _, stat in entries)
    if total <= max_bytes:
        return 0
    entries.sort(key=lambda item: (item[1].st_mtime_ns, item[0].name))
    evicted = 0
    for path, stat in entries:
        if total <= max_bytes:
            break
        try:
            path.unlink()
        except OSError:
            continue
        total -= stat.st_size
        evicted += stat.st_size
    _remove_empty_track_dirs(root)
    return evicted


def _metadata_payload_path(root: Path, digest: str) -> Path:
    return root / f"meta-{digest}.json"


def _read_cached_metadata_payload(root: Path, digest: str) -> VideoMetadata | None:
    try:
        raw = _metadata_payload_path(root, digest).read_text(encoding="utf-8")
        payload = json.loads(raw)
    except (OSError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    try:
        return parse_ffprobe_metadata(payload)
    except Exception:
        return None


def _probe_and_cache_metadata(
    path: str | Path, root: Path, digest: str
) -> VideoMetadata | None:
    if shutil.which("ffprobe") is None:
        return None
    try:
        result = subprocess.run(
            ffprobe_metadata_command(path),
            check=False,
            capture_output=True,
            text=True,
            timeout=_METADATA_PROBE_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    try:
        payload = json.loads(result.stdout)
    except ValueError:
        return None
    if not isinstance(payload, dict):
        return None
    try:
        parsed = parse_ffprobe_metadata(payload)
    except Exception:
        return None
    try:
        atomic_write_text(
            _metadata_payload_path(root, digest),
            json.dumps(payload, sort_keys=True),
        )
    except OSError:
        pass
    enforce_cache_budget(root)
    return parsed


def atomic_write_text(dest: Path, text: str) -> None:
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    tmp_handle = tempfile.NamedTemporaryFile(
        dir=str(dest.parent), prefix=".tmp-", suffix=".json", delete=False
    )
    try:
        with tmp_handle:
            tmp_handle.write(text.encode("utf-8"))
        os.replace(tmp_handle.name, dest)
    except OSError:
        unlink_quietly(Path(tmp_handle.name))
        raise


def _remove_empty_track_dirs(root: Path) -> None:
    try:
        children = list(root.iterdir())
    except OSError:
        return
    for child in children:
        if not child.is_dir():
            continue
        try:
            if not any(child.iterdir()):
                child.rmdir()
        except OSError:
            continue


def unlink_quietly(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass
