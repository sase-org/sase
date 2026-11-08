"""Shared constants, roles, and progress reader for the contention sampler."""

from __future__ import annotations

import json
import signal
from pathlib import Path
from typing import Any

from tests._contention import (
    CONTROLLER_PROGRESS_FILENAME,
    KILLS_FILENAME,
    WORKER_PROGRESS_PREFIX,
    read_json,
)

LOG_PREFIX = "[contention-diag]"
SAMPLES_FILENAME = "samples.jsonl"
SIGNALS_FILENAME = "signals.jsonl"
CAPTURED_SIGNALS = (signal.SIGTERM, signal.SIGINT, signal.SIGHUP)
DEFAULT_INTERVAL_SECONDS = 15.0
POLL_SECONDS = 1.0
MAX_SAMPLE_RECORDS = 2000
MAX_SIGNAL_RECORDS = 20
#: The scratch tree is walked on the first sample and every Nth after it.
USAGE_SCAN_EVERY = 8
PRINT_LIMIT = 30
#: How long an exited soak process stays identifiable, so a sender that died
#: right after signalling can still be named from the sample before.
LAST_SEEN_SECONDS = 120.0
LAST_SEEN_LIMIT = 512
# After the parent exits, one signal-time observation and one final sample are
# enough to identify surviving members. The sampler never waits for or kills
# test workers; its parent reaps only this sampler with bounded waits below.
POST_ROOT_OBSERVATION_LIMIT = 2
SAMPLER_STOP_TIMEOUT_SECONDS = 10.0
SAMPLER_REAP_TIMEOUT_SECONDS = 5.0
BYTE_PEAKS = frozenset(
    {
        "soak_rss",
        "soak_pss",
        "soak_swap",
        "min_mem_available",
        "min_swap_free",
        "cgroup_current",
        "scratch_bytes",
    }
)
SI_CODE_NAMES = {0: "SI_USER", 0x80: "SI_KERNEL", -1: "SI_QUEUE", -6: "SI_TKILL"}
ROLE_NAMES = ("parent", "controller", "worker")


def role(depth: int) -> str:
    return ROLE_NAMES[depth] if depth < len(ROLE_NAMES) else "descendant"


def read_progress(progress_root: Path) -> dict[str, Any] | None:
    """The latest repeat's controller record, worker records, and kill audit."""
    try:
        repeats = sorted(path for path in progress_root.iterdir() if path.is_dir())
    except OSError:
        return None
    if not repeats:
        return None
    current = repeats[-1]
    workers: dict[int, dict[str, Any]] = {}
    for path in current.glob(f"{WORKER_PROGRESS_PREFIX}*.json"):
        record = read_json(path)
        if record is not None and isinstance(record.get("pid"), int):
            workers[record["pid"]] = record
    kills: list[dict[str, Any]] = []
    try:
        lines = (current / KILLS_FILENAME).read_text().splitlines()
    except OSError:
        lines = []
    for line in lines:
        try:
            kills.append(json.loads(line))
        except ValueError:
            continue
    return {
        "repeat": current.name,
        "controller": read_json(current / CONTROLLER_PROGRESS_FILENAME),
        "workers": workers,
        "kill_count": len(kills),
        "kills": kills[-3:],
    }
