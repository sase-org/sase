"""Identity-keyed on-disk cache for the Command Line completion spec.

The TUI builds the frozen ``CommandLineGrammar`` from the full-descriptions
spec JSON (``sase completion spec -d -j``). Building walks the whole argparse
tree, so it runs in a subprocess and the result is cached by runtime identity
plus source fingerprint. Safe to call from a worker thread; never prompts.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

from sase.completion.runtime_cache_identity import (
    runtime_identity_key,
    source_fingerprint,
)
from sase.completion.runtime_cache_support import bounded_lock
from sase.core.paths import sase_subdir

_CACHE_DIRNAME = "cache"
_SPEC_PREFIX = "command_line_spec-"
_SPEC_SUFFIX = ".json"
_TIMINGS_NAME = "command_line_spec-timings.jsonl"
_BUILD_TIMEOUT_SECONDS = 120.0


def _command_line_spec_key() -> str:
    """Return the cache key for the current runtime and sources."""
    return f"{runtime_identity_key()}-{source_fingerprint()}"


def _command_line_spec_path(key: str | None = None) -> Path:
    """Return the on-disk path for the Command Line spec cache."""
    return (
        _cache_dir() / f"{_SPEC_PREFIX}{key or _command_line_spec_key()}{_SPEC_SUFFIX}"
    )


def ensure_command_line_spec(*, timeout: float = _BUILD_TIMEOUT_SECONDS) -> Path:
    """Return the path of a current Command Line spec, building it if needed.

    On a cache hit the existing path is returned without spawning anything.
    On a miss the spec is built in a subprocess
    (``sase completion spec -d -j -o <tmp>``), renamed into place atomically,
    and stale siblings are pruned. Build timings are appended best-effort to
    the completions timing log and echoed to stderr, following the
    ``completion ensure`` stderr-diagnostics convention.
    """
    key = _command_line_spec_key()
    path = _command_line_spec_path(key)
    if _is_usable(path):
        return path
    directory = path.parent
    directory.mkdir(parents=True, exist_ok=True)
    with bounded_lock(directory / ".command_line_spec.lock"):
        if _is_usable(path):
            return path
        started = time.monotonic()
        _build_in_subprocess(path, timeout=timeout)
        elapsed = time.monotonic() - started
        _record_timing(key, elapsed)
        _prune_stale_siblings(directory, keep=path.name)
    return path


def _cache_dir() -> Path:
    return sase_subdir("completion") / _CACHE_DIRNAME


def _is_usable(path: Path) -> bool:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return False
    try:
        document = json.loads(text)
    except json.JSONDecodeError:
        return False
    return isinstance(document, dict) and isinstance(document.get("root"), dict)


def _build_in_subprocess(path: Path, *, timeout: float) -> None:
    tmp_fd, tmp_name = tempfile.mkstemp(
        prefix=".command_line_spec.", suffix=".tmp", dir=path.parent
    )
    os.close(tmp_fd)
    tmp_path = Path(tmp_name)
    try:
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "sase",
                "completion",
                "spec",
                "-d",
                "-j",
                "-o",
                str(tmp_path),
            ],
            timeout=timeout,
            capture_output=True,
            text=True,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        tmp_path.unlink(missing_ok=True)
        raise CompletionSpecCacheError(
            f"timed out building command-line spec after {timeout}s"
        ) from exc
    if completed.returncode != 0 or not _is_usable(tmp_path):
        tmp_path.unlink(missing_ok=True)
        detail = (completed.stderr or completed.stdout or "").strip()
        suffix = f": {detail}" if detail else ""
        raise CompletionSpecCacheError(
            f"command-line spec subprocess failed (exit {completed.returncode}){suffix}"
        )
    try:
        os.replace(tmp_path, path)
    except OSError as exc:
        tmp_path.unlink(missing_ok=True)
        raise CompletionSpecCacheError(
            f"cannot publish command-line spec: {exc}"
        ) from exc


def _record_timing(key: str, elapsed: float) -> None:
    """Best-effort timing record; a timing failure never fails the build."""
    try:
        line = json.dumps(
            {
                "at": datetime.now(UTC).replace(microsecond=0).isoformat(),
                "elapsed_seconds": round(elapsed, 3),
                "key": key,
            },
            sort_keys=True,
        )
        timings = _cache_dir() / _TIMINGS_NAME
        with timings.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    except OSError:
        pass
    try:
        print(
            f"sase completion: built command-line spec in {elapsed:.2f}s",
            file=sys.stderr,
        )
    except OSError:
        pass


def _prune_stale_siblings(directory: Path, *, keep: str) -> None:
    try:
        entries = list(directory.iterdir())
    except OSError:
        return
    for entry in entries:
        if (
            entry.name.startswith(_SPEC_PREFIX)
            and entry.name.endswith(_SPEC_SUFFIX)
            and entry.name != keep
        ):
            try:
                entry.unlink()
            except OSError:
                pass


class CompletionSpecCacheError(RuntimeError):
    """User-facing failure while resolving the Command Line spec cache."""


__all__ = [
    "CompletionSpecCacheError",
    "ensure_command_line_spec",
]
