"""Path and directory utilities.

YYYYMM sharding
---------------

High-volume ``~/.sase/`` subdirectories are sharded into ``YYYYMM/``
subdirectories to keep single-directory entry counts bounded.  Callers
use :func:`sharded_path` (write), :func:`iter_sharded_files` (scan),
and :func:`find_sharded_file` (lookup) instead of hand-rolling paths.

Criteria for sharding a ``~/.sase/`` subdir:

* The directory grows unboundedly over time (append-only workload).
* Readers periodically list the entire directory (collectors, TUI).

Excluded from sharding: ``projects/`` (bounded by active-project count),
``comments/``, ``reverted/``, ``user_question/``, ``notifications/``,
``telegram/``, ``axe/``, ``commit_state/``, ``logs/``, ``home/``,
``repos/``, ``spec_writer/``, ``images/``, ``archived/``, and top-level
JSON files — either bounded, already structured, or below the threshold
at which flat-directory scans become noticeable.  Revisit individually
if any of these later crosses ~1000 entries.
"""

import os
import re
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path


def get_sase_tmpdir() -> str | None:
    """Return the SASE temp directory if $SASE_TMPDIR is set, else None.

    When $SASE_TMPDIR is set, the directory is created if it doesn't exist.
    Returning None lets tempfile functions fall back to the system default.
    """
    sase_tmpdir = os.environ.get("SASE_TMPDIR")
    if sase_tmpdir:
        os.makedirs(sase_tmpdir, exist_ok=True)
        return sase_tmpdir
    return None


def get_sase_directory(subdir: str) -> str:
    """Get the path to a subdirectory under ~/.sase/.

    Args:
        subdir: The subdirectory name (e.g., "hooks", "diffs", "chats")

    Returns:
        Full path like "/home/user/.sase/hooks"
    """
    return os.path.expanduser(f"~/.sase/{subdir}")


def ensure_sase_directory(subdir: str) -> str:
    """Ensure a ~/.sase subdirectory exists and return its path.

    Args:
        subdir: The subdirectory name (e.g., "hooks", "diffs", "chats")

    Returns:
        Full path to the created/existing directory
    """
    dir_path = get_sase_directory(subdir)
    Path(dir_path).mkdir(parents=True, exist_ok=True)
    return dir_path


def shorten_path(path: str) -> str:
    """Shorten a file path by replacing home directory with ~.

    Args:
        path: Full file path

    Returns:
        Path with home directory replaced by ~
    """
    return path.replace(str(Path.home()), "~")


def make_safe_filename(name: str) -> str:
    """Convert a string to a safe filename by replacing non-alphanumeric chars.

    Args:
        name: The string to convert

    Returns:
        Safe filename with only alphanumeric chars and underscores
    """
    return re.sub(r"[^a-zA-Z0-9_]", "_", name)


# ---------------------------------------------------------------------------
# YYYYMM sharding
# ---------------------------------------------------------------------------

_SHARD_DIR_RE = re.compile(r"^\d{6}$")

_TS_SUFFIX_RE = re.compile(r"-(\d{6}_\d{6})(?:\.\w+)?$")
"""Matches ``-YYmmdd_HHMMSS`` at end of filename (before optional extension)."""

_TS_PREFIX_RE = re.compile(r"^(\d{14})(?:__|\.|$)")
"""Matches ``YYYYmmddHHMMSS`` at start of filename (e.g. dismissed_bundles)."""


def _sase_subdir(subdir: str) -> Path:
    """Return the ``~/.sase/<subdir>`` path (expanded, not necessarily existing)."""
    return Path(f"~/.sase/{subdir}").expanduser()


def parse_filename_timestamp(filename: str) -> datetime | None:
    """Extract a datetime from a filename embedded timestamp, if any.

    Supports the two formats used across ``~/.sase/``:

    * ``-YYmmdd_HHMMSS`` suffix (chats, workflows, checks, hooks, diffs,
      mentors, comments).
    * ``YYYYmmddHHMMSS`` prefix (dismissed_bundles), optionally followed
      by ``__c<idx>`` or a file extension.

    Returns ``None`` if no timestamp can be parsed.
    """
    m = _TS_SUFFIX_RE.search(filename)
    if m:
        try:
            return datetime.strptime(m.group(1), "%y%m%d_%H%M%S")
        except ValueError:
            pass
    m = _TS_PREFIX_RE.match(filename)
    if m:
        try:
            return datetime.strptime(m.group(1), "%Y%m%d%H%M%S")
        except ValueError:
            pass
    return None


def _shard_name(ts: datetime) -> str:
    return ts.strftime("%Y%m")


def sharded_path(
    subdir: str,
    filename: str,
    *,
    ts: datetime | None = None,
    ensure: bool = True,
) -> str:
    """Return the sharded path for a file under ``~/.sase/<subdir>/YYYYMM/<filename>``.

    The shard is chosen from, in order:

    1. An explicit ``ts`` argument.
    2. A ``YYmmdd_HHMMSS`` / ``YYYYmmddHHMMSS`` timestamp parsed from
       ``filename``.
    3. ``datetime.now()``.

    If ``ensure=True``, the shard directory is created.
    """
    if ts is None:
        ts = parse_filename_timestamp(filename)
    if ts is None:
        ts = datetime.now()
    shard_dir = _sase_subdir(subdir) / _shard_name(ts)
    if ensure:
        shard_dir.mkdir(parents=True, exist_ok=True)
    return str(shard_dir / filename)


def iter_sharded_files(
    subdir: str,
    *,
    pattern: str = "*",
    include_legacy: bool = True,
) -> Iterator[Path]:
    """Yield file paths across all ``YYYYMM/`` shards under ``~/.sase/<subdir>/``.

    If ``include_legacy=True``, also yields any files directly in
    ``<subdir>/`` (pre-migration stragglers and external tools that
    don't know about sharding).

    ``pattern`` is passed through to :meth:`pathlib.Path.glob` — use
    ``"*"`` for all top-level files, ``"*.md"`` to filter by extension,
    or ``"**/*.json"`` to recurse (needed for ``plan_approval`` where
    each entry is a UUID subdirectory).
    """
    base = _sase_subdir(subdir)
    if not base.is_dir():
        return
    for entry in sorted(base.iterdir()):
        if entry.is_dir() and _SHARD_DIR_RE.match(entry.name):
            yield from entry.glob(pattern)
    if include_legacy:
        for p in base.glob(pattern):
            if p.is_file():
                yield p


def find_sharded_file(
    subdir: str,
    filename: str,
    *,
    ts: datetime | None = None,
) -> str | None:
    """Look up a specific filename under ``~/.sase/<subdir>/``.

    Fast path: try the shard implied by ``ts`` or by a timestamp parsed
    from ``filename``.  Slow path: scan all ``YYYYMM/`` shards (plus
    the legacy top-level) for an exact match.  Returns ``None`` if not
    found.
    """
    base = _sase_subdir(subdir)
    if not base.is_dir():
        return None
    hint_ts = ts if ts is not None else parse_filename_timestamp(filename)
    if hint_ts is not None:
        fast = base / _shard_name(hint_ts) / filename
        if fast.is_file():
            return str(fast)
    legacy = base / filename
    if legacy.is_file():
        return str(legacy)
    for entry in base.iterdir():
        if entry.is_dir() and _SHARD_DIR_RE.match(entry.name):
            candidate = entry / filename
            if candidate.is_file():
                return str(candidate)
    return None
