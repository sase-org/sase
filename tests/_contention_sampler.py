"""Bounded resource and signal sampler for the contention soak.

Diagnostic only. `tools/run_pytest contention` starts this as
``python -m tests._contention_sampler`` beside its pytest repeats and stops it
by closing its stdin. Every interval it appends one JSON sample and prints one
flushed log line: the soak's process tree (RSS, PSS, swap, threads), host and
cgroup memory, pressure stall information, OOM counters, filesystem headroom
for the scratch root, ``/tmp``, and the workspace, and the repeat's live
progress from `tests._contention_progress`.

Lines go to the job log as well as ``samples.jsonl``, because a runner that is
being torn down may never run the step that uploads the file.

The sampler stays in the soak's process group and blocks SIGTERM, SIGINT, and
SIGHUP, consuming them with ``sigtimedwait``. A signal broad enough to reach the
whole soak therefore reaches it too, and it can record what nothing else here
can: the sending PID and that sender's ancestry, matched to the worker and test
that were running. It keeps sampling until the soak parent exits.

It moves itself off the soak's pinned CPUs so the starvation it measures is
neither worsened by it nor delaying it. It never signals another process; the
harness owns its lifetime.
"""

from __future__ import annotations

from tests._contention_sampler_common import (
    BYTE_PEAKS,
    CAPTURED_SIGNALS,
    DEFAULT_INTERVAL_SECONDS,
    LAST_SEEN_LIMIT,
    LAST_SEEN_SECONDS,
    LOG_PREFIX,
    MAX_SAMPLE_RECORDS,
    MAX_SIGNAL_RECORDS,
    POLL_SECONDS,
    POST_ROOT_OBSERVATION_LIMIT,
    PRINT_LIMIT,
    ROLE_NAMES,
    SAMPLER_REAP_TIMEOUT_SECONDS,
    SAMPLER_STOP_TIMEOUT_SECONDS,
    SAMPLES_FILENAME,
    SI_CODE_NAMES,
    SIGNALS_FILENAME,
    USAGE_SCAN_EVERY,
    read_progress,
    role,
)
from tests._contention_sampler_runner import SamplerHandle, main, start_sampler
from tests._contention_sampler_sampler import Sampler

__all__ = [
    "BYTE_PEAKS",
    "CAPTURED_SIGNALS",
    "DEFAULT_INTERVAL_SECONDS",
    "LAST_SEEN_LIMIT",
    "LAST_SEEN_SECONDS",
    "LOG_PREFIX",
    "MAX_SAMPLE_RECORDS",
    "MAX_SIGNAL_RECORDS",
    "POLL_SECONDS",
    "POST_ROOT_OBSERVATION_LIMIT",
    "PRINT_LIMIT",
    "ROLE_NAMES",
    "SAMPLER_REAP_TIMEOUT_SECONDS",
    "SAMPLER_STOP_TIMEOUT_SECONDS",
    "SAMPLES_FILENAME",
    "SI_CODE_NAMES",
    "SIGNALS_FILENAME",
    "USAGE_SCAN_EVERY",
    "Sampler",
    "SamplerHandle",
    "read_progress",
    "role",
    "main",
    "start_sampler",
]


if __name__ == "__main__":
    raise SystemExit(main())
