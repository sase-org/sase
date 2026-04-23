"""Per-attempt artifact snapshotting for retried agent executions.

When the retry loop switches from attempt N to attempt N+1, this module
moves the current `live_reply.md` / `live_reply_timestamps.jsonl` into
`attempts/<N>/` alongside a per-attempt metadata record. The root
artifacts dir is then truncated so attempt N+1 streams into clean files.
"""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

AttemptStatus = Literal["failed", "raised"]

ATTEMPTS_DIRNAME = "attempts"
ATTEMPT_META_FILENAME = "attempt_meta.json"


@dataclass
class _AttemptMeta:
    """Per-attempt metadata written to ``attempts/<N>/attempt_meta.json``."""

    attempt_number: int
    status: AttemptStatus
    start_epoch: float
    end_epoch: float
    model: str | None
    used_fallback: bool
    error_snippet: str
    error_full: str


def _attempt_dir(artifacts_dir: str, attempt_number: int) -> Path:
    return Path(artifacts_dir) / ATTEMPTS_DIRNAME / f"{attempt_number:02d}"


def _tmp_attempt_dir(artifacts_dir: str, attempt_number: int) -> Path:
    return Path(artifacts_dir) / ATTEMPTS_DIRNAME / f"{attempt_number:02d}.tmp"


def snapshot_attempt(
    artifacts_dir: str,
    attempt_number: int,
    *,
    status: AttemptStatus,
    start_epoch: float,
    end_epoch: float,
    error_full: str,
    error_snippet: str,
    model: str | None,
    used_fallback: bool,
) -> None:
    """Move current reply artifacts into ``attempts/<N>/`` and record metadata.

    Creates ``attempts/<N>.tmp/`` first, populates it, then atomically renames
    to ``attempts/<N>/``. After a successful snapshot the root
    ``live_reply.md`` / ``live_reply_timestamps.jsonl`` files are truncated so
    the next attempt streams into clean files from byte 0.

    Idempotent: if ``attempts/<N>/`` already exists, this is a no-op. Missing
    source files are tolerated (meta is still written).
    """
    final_dir = _attempt_dir(artifacts_dir, attempt_number)
    if final_dir.exists():
        return

    tmp_dir = _tmp_attempt_dir(artifacts_dir, attempt_number)
    if tmp_dir.exists():
        shutil.rmtree(tmp_dir, ignore_errors=True)
    tmp_dir.mkdir(parents=True, exist_ok=True)

    root = Path(artifacts_dir)
    for name in ("live_reply.md", "live_reply_timestamps.jsonl"):
        src = root / name
        if src.exists():
            try:
                shutil.move(str(src), str(tmp_dir / name))
            except OSError:
                pass

    meta = _AttemptMeta(
        attempt_number=attempt_number,
        status=status,
        start_epoch=start_epoch,
        end_epoch=end_epoch,
        model=model,
        used_fallback=used_fallback,
        error_snippet=error_snippet,
        error_full=error_full,
    )
    meta_path = tmp_dir / ATTEMPT_META_FILENAME
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(asdict(meta), f, indent=2)

    os.rename(tmp_dir, final_dir)

    # Truncate root reply files so attempt N+1 streams into a clean slate.
    for name in ("live_reply.md", "live_reply_timestamps.jsonl"):
        path = root / name
        try:
            with open(path, "w", encoding="utf-8"):
                pass
        except OSError:
            pass
