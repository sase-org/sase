"""Shared fixtures for managed-tmp reaper tests."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from sase.core.managed_tmp_reaper import reap_managed_tmpdir as _reap_managed_tmpdir


NOW = 1_800_000_000.0
HOUR = 3600.0
DAY = 24 * HOUR
FREE_SPACE_OK = 64 * 1024**3


def reap_managed_tmpdir(*args: Any, **kwargs: Any) -> Any:
    kwargs.setdefault("filesystem_available_bytes", FREE_SPACE_OK)
    return _reap_managed_tmpdir(*args, **kwargs)


def _fail_on_call(dirs: object) -> int:
    raise AssertionError(f"artifact index touched for {dirs!r}")


def _aged_file(root: Path, relative: str, *, age_seconds: float) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("scratch", encoding="utf-8")
    stamp = NOW - age_seconds
    os.utime(path, (stamp, stamp))
    return path


def _aged_dir(
    root: Path,
    relative: str,
    *,
    age_seconds: float,
    size_bytes: int = 0,
) -> Path:
    path = root / relative
    path.mkdir(parents=True, exist_ok=True)
    (path / "state.json").write_text("{}", encoding="utf-8")
    if size_bytes:
        with (path / "payload.bin").open("wb") as handle:
            handle.truncate(size_bytes)
    stamp = NOW - age_seconds
    for child in path.iterdir():
        os.utime(child, (stamp, stamp))
    os.utime(path, (stamp, stamp))
    return path
