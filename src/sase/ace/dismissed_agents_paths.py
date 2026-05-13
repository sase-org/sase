"""Path helpers for dismissed agent archives."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from sase.core.paths import parse_filename_timestamp

_SHARD_DIR_RE = re.compile(r"^\d{6}$")


def bundle_shard_dir(bundles_dir: Path, filename: str) -> Path:
    """Return the YYYYMM shard subdir under ``bundles_dir`` for a bundle.

    Bundle filenames start with a 14-digit timestamp (``raw_suffix``);
    children append ``__c<idx>`` before ``.json``. If the timestamp can't be
    parsed, fall back to ``now()`` so the file still lands in a valid shard.
    """
    ts = parse_filename_timestamp(filename) or datetime.now()
    return bundles_dir / ts.strftime("%Y%m")


def iter_bundle_paths(bundles_dir: Path, pattern: str = "*.json") -> list[Path]:
    """Yield bundle file paths across all shards and the legacy top level."""
    if not bundles_dir.is_dir():
        return []
    results: list[Path] = []
    for entry in bundles_dir.iterdir():
        if entry.is_dir() and _SHARD_DIR_RE.match(entry.name):
            results.extend(path for path in entry.glob(pattern) if path.is_file())
    # Legacy (pre-migration) files directly in the root.
    for path in bundles_dir.glob(pattern):
        if path.is_file():
            results.append(path)
    return results


def find_bundle(bundles_dir: Path, filename: str) -> Path | None:
    """Return the on-disk path for ``filename`` - shard fast path, then scan."""
    ts = parse_filename_timestamp(filename)
    if ts is not None:
        candidate = bundles_dir / ts.strftime("%Y%m") / filename
        if candidate.is_file():
            return candidate
    legacy = bundles_dir / filename
    if legacy.is_file():
        return legacy
    if bundles_dir.is_dir():
        for entry in bundles_dir.iterdir():
            if entry.is_dir() and _SHARD_DIR_RE.match(entry.name):
                candidate = entry / filename
                if candidate.is_file():
                    return candidate
    return None
