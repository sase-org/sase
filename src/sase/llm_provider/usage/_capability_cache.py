"""Fingerprint-keyed on-disk cache of CLI capability results for usage probes.

Version and help probes cost a process spawn each. Their answers only change
when the CLI binary changes, so each provider keeps one JSON entry under the
SASE home cache directory keyed by its CLI fingerprint
(``"<path>:<mtime_ns>:<size>"``). A 24 h TTL bounds staleness when a fingerprint
collides, and entries that end in ``unsupported_cli_version`` or
``vendor_drift`` are deleted outright.

Workers read and write the cache directly from the probe path, so nothing
travels through the refresh payload. Every helper is best-effort: cache
failures degrade to a miss, never to a probe failure.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import tempfile
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

CAPABILITY_CACHE_TTL_SECONDS = 24 * 3600.0
CAPABILITY_CACHE_DIR_NAME = "usage_probe_capabilities"
_INVALIDATING_REASON_CODES = frozenset({"unsupported_cli_version", "vendor_drift"})
_MAX_CACHED_OUTPUT_BYTES = 65_536


def _capability_cache_dir() -> Path:
    """Return the directory holding per-provider capability entries."""
    from sase.core.paths import sase_home

    return Path(str(sase_home())) / "cache" / CAPABILITY_CACHE_DIR_NAME


def executable_fingerprint(executable: str | None) -> str | None:
    """Return ``"<path>:<mtime_ns>:<size>"`` for *executable*, if it exists.

    Bare command names resolve through ``PATH`` exactly as the subprocess
    spawn does, so probes that pass ``"agy"`` or ``"grok"`` still hit the
    cache in production. ``None`` means the command is not on disk: the
    cache is bypassed rather than keyed on a guess.
    """
    if not executable:
        return None
    try:
        candidate = Path(executable)
        if not candidate.is_file():
            resolved = shutil.which(executable)
            if not resolved:
                return None
            candidate = Path(resolved)
        stat = candidate.stat()
    except (OSError, ValueError):
        return None
    return f"{candidate}:{stat.st_mtime_ns}:{stat.st_size}"


def read_probe_capability(
    provider: str,
    fingerprint: str | None,
    *,
    now: float | None = None,
) -> dict[str, Any] | None:
    """Return cached capabilities for *provider* at *fingerprint*.

    A missing file, a fingerprint mismatch, TTL expiry, or any corruption is
    a miss (``None``).
    """
    if not provider or not fingerprint:
        return None
    clock = time.time() if now is None else now
    try:
        raw = _cache_path(provider).read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        envelope = json.loads(raw)
    except ValueError:
        log.debug("Ignoring corrupt capability cache for provider %r", provider)
        return None
    if not isinstance(envelope, Mapping):
        return None
    if envelope.get("fingerprint") != fingerprint:
        return None
    cached_at = envelope.get("cached_at")
    if (
        isinstance(cached_at, bool)
        or not isinstance(cached_at, int | float)
        or cached_at != cached_at
        or cached_at in (float("inf"), float("-inf"))
        or clock - float(cached_at) < 0
        or clock - float(cached_at) > CAPABILITY_CACHE_TTL_SECONDS
    ):
        return None
    capabilities = envelope.get("capabilities")
    if not isinstance(capabilities, Mapping):
        return None
    decoded: dict[str, Any] = {}
    for key, value in capabilities.items():
        if not isinstance(key, str):
            return None
        decoded[key] = value
    return decoded


def write_probe_capability(
    provider: str,
    fingerprint: str | None,
    capabilities: Mapping[str, Any],
    *,
    now: float | None = None,
) -> None:
    """Persist *capabilities* for *provider* at *fingerprint*, atomically."""
    if not provider or not fingerprint:
        return None
    clock = time.time() if now is None else now
    try:
        envelope = {
            "fingerprint": fingerprint,
            "cached_at": float(clock),
            "capabilities": dict(capabilities),
        }
        payload = json.dumps(envelope, separators=(",", ":")).encode("utf-8")
        target = _cache_path(provider)
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(
            dir=str(target.parent), prefix=f"{target.name}.", suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_name, target)
        except BaseException:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise
    except Exception:
        log.debug("Capability cache write failed for provider %r", provider)
    return None


def _invalidate_probe_capability(provider: str) -> None:
    """Delete *provider*'s cached entry, if any."""
    if not provider:
        return
    try:
        _cache_path(provider).unlink(missing_ok=True)
    except OSError:
        log.debug("Capability cache invalidation failed for %r", provider)


def note_probe_capability_outcome(
    provider: str,
    observation: Mapping[str, Any] | None,
) -> None:
    """Drop *provider*'s entry when *observation* reports drift or staleness.

    A probe that ends in ``unsupported_cli_version`` or ``vendor_drift`` proves
    the cached version/help answers no longer describe the CLI.
    """
    if not isinstance(observation, Mapping):
        return
    if observation.get("reason_code") in _INVALIDATING_REASON_CODES:
        _invalidate_probe_capability(provider)


def encode_command_result(
    returncode: int, stdout: str, stderr: str
) -> dict[str, Any] | None:
    """Encode one cached CLI command result, or ``None`` when too large."""
    if (
        isinstance(returncode, bool)
        or not isinstance(returncode, int)
        or not isinstance(stdout, str)
        or not isinstance(stderr, str)
        or len(stdout.encode("utf-8")) > _MAX_CACHED_OUTPUT_BYTES
        or len(stderr.encode("utf-8")) > _MAX_CACHED_OUTPUT_BYTES
    ):
        return None
    return {"returncode": returncode, "stdout": stdout, "stderr": stderr}


def decode_command_result(value: Any) -> tuple[int, str, str] | None:
    """Decode a cached command result, or ``None`` when it is not one."""
    if not isinstance(value, Mapping):
        return None
    returncode = value.get("returncode")
    stdout = value.get("stdout")
    stderr = value.get("stderr")
    if (
        isinstance(returncode, bool)
        or not isinstance(returncode, int)
        or not isinstance(stdout, str)
        or not isinstance(stderr, str)
    ):
        return None
    return (returncode, stdout, stderr)


def _cache_path(provider: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9_-]", "_", provider).strip("_") or "unknown"
    return _capability_cache_dir() / f"{safe}.json"


__all__ = [
    "CAPABILITY_CACHE_DIR_NAME",
    "CAPABILITY_CACHE_TTL_SECONDS",
    "decode_command_result",
    "encode_command_result",
    "executable_fingerprint",
    "note_probe_capability_outcome",
    "read_probe_capability",
    "write_probe_capability",
]
