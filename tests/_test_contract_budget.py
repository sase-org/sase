"""Load- and machine-normalized measurement for the contract-set budget guard.

The budget guard in :mod:`tests.test_contract_manifest` exists to bound *the
size of the contract set*, because that set is added to every diff-scoped
selection and so is paid by every agent on every ``just check``. A wall-clock
ceiling does not measure that. The guard's own assertion runs inside the full
suite under 12-28 xdist workers, so a raw wall reading is host load at least as
much as it is set size: measured on the 64-core dev host, the same committed
set took 24.4s wall on a quiet host and 37.1s under 96 spinner processes, and
its child CPU still moved 1.4x (24.2s -> 34.0s). An absolute second count is not
portable across machines, which matters directly -- the guard's one observed
real-CI failure was on a GitHub runner, not on the dev host.

The fix is to normalize against the machine-and-moment the measurement was
taken on. Bracket the nested contract run with a fixed calibration probe
(:data:`PROBE_SOURCE`) measured exactly the same way -- child CPU of a
subprocess -- immediately before and immediately after, and scale::

    normalized = contract_cpu * (PROBE_BASELINE_CPU_SECONDS / mean(probe_cpu))

Measured on the dev host while writing this module, the contract-CPU-to-probe
ratio held to within 7% across that inflation (29.4-30.1 quiet vs 28.2 under
load), so the normalized figure reads 21.7-23.2s in every condition while the
raw wall clock ranged 24-42s. Bracketing (two probes, mean) rather than a
single leading probe is what keeps that true when the load changes partway
through a 25s run -- which it demonstrably does on this host, where individual
bracket pairs read as far apart as 0.78s and 1.09s.

The measurement helpers here need ``resource`` (Unix-only); nothing else in
this repo imports it, so callers must handle :data:`HAVE_RESOURCE` being false
by skipping rather than failing at collection time. The pure normalization
arithmetic below has no such dependency and is unit-tested directly in
``tests/test_contract_budget_normalization.py``.

`sase-go` (2026-08-07) found a gap in the above: the 96-spinner load used to
validate it is pure CPU-cycle contention, which :data:`PROBE_SOURCE` (then a
register/L1-resident loop) tracks well, but 12-28 real xdist workers spend
most of their CPU importing modules and allocating collector objects --
memory-bandwidth- and page-cache-bound work the old probe barely touched.
Measured back to back, 40 real xdist workers inflated the contract set's own
child CPU ~20% while the old probe moved only ~6%, i.e. the normalization
under-corrected for exactly the contention shape this guard runs under in
practice. :data:`PROBE_SOURCE` now mixes in stdlib imports and dict
allocation/sort/discard to close part of that gap (~9-10% under the same
contention); see the comment on :data:`PROBE_SOURCE` for the measurements, and
`test_contract_manifest.py`'s ``_BUDGET_SECONDS`` comment for how the
remaining, unclosed part of the gap is covered.
"""

from __future__ import annotations

import subprocess
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from statistics import fmean


try:  # pragma: no cover - exercised by platform, not by the suite
    import resource
except ImportError:  # pragma: no cover - non-Unix
    resource = None  # type: ignore[assignment]

#: ``resource`` is Unix-only and nothing else in this repo imports it. Callers
#: that measure must skip -- not fail at collection -- where it is missing.
HAVE_RESOURCE = resource is not None

#: Deterministic, fixed-cost calibration workload. `sase-go` found that the
#: original version of this probe -- an interpreter loop, hashing, and process
#: spawns, all cache-resident -- tracked pure CPU-cycle contention (a bank of
#: `while True: pass` spinners) essentially perfectly but under-corrected for
#: the contention a real nested pytest run experiences: measured back to back
#: on the 64-core dev host, 40 real xdist workers importing and running
#: `tests/ace/` inflated the contract set's own child CPU ~20% (24.5s -> 29.4s)
#: while the cache-resident probe moved only ~6%. Real test workers spend most
#: of their CPU importing modules and allocating the objects pytest's
#: collector builds per test item, which is memory-bandwidth- and page-cache-
#: bound in a way a register/L1-resident loop is not. This version adds a
#: batch of stdlib imports (deliberately ones unlikely to already be loaded by
#: `python -c`) plus building, sorting, and discarding a batch of dicts, so
#: the probe pays some of the same memory-traffic cost. Re-measured the same
#: way, it inflated ~9-10% under the same 40-worker contention -- a real,
#: measured improvement, though still not a full match for the contract set's
#: ~20%; see :data:`_BUDGET_SECONDS` in `test_contract_manifest.py` for how
#: the remaining gap is covered. Never tune this without re-measuring
#: :data:`PROBE_BASELINE_CPU_SECONDS`: the two are one calibration pair.
PROBE_SOURCE = """\
import gc
import hashlib
import subprocess
import sys

total = 0
for i in range(4_500_000):
    total += (i * i) % 7

digest = b"sase-contract-budget-probe"
for _ in range(40_000):
    digest = hashlib.sha256(digest).digest()

import argparse
import asyncio
import csv
import dataclasses
import decimal
import email.mime.multipart
import html.parser
import http.client
import importlib
import json
import logging
import re
import sqlite3
import unittest.mock
import urllib.request
import xml.etree.ElementTree

blobs = [
    {"id": i, "payload": "x" * 512, "tags": [str(j) for j in range(8)]}
    for i in range(20_000)
]
blobs.sort(key=lambda item: item["payload"])
del blobs
gc.collect()

for _ in range(20):
    subprocess.run([sys.executable, "-c", "pass"], check=True)

print(total, digest.hex()[:8])
"""

#: Child CPU seconds :data:`PROBE_SOURCE` costs on a quiet reference host.
#: Measured 2026-08-07 on the same 64-core dev host as the module docstring's
#: figures, across 7 samples with no deliberate contention (ambient loadavg
#: 30-35, since this host runs other agents continuously and never truly
#: idles): 0.88-1.06, mean ~0.94, taken as 0.94. Under 40 real xdist workers
#: the same probe read 0.96-1.06 -- see the comment above :data:`PROBE_SOURCE`
#: for what that inflation does and does not correct for.
PROBE_BASELINE_CPU_SECONDS = 0.94


@dataclass(frozen=True)
class Measurement:
    """One bracketed measurement of a subprocess workload.

    ``wall`` and ``cpu`` are raw; ``normalized`` is what the budget is asserted
    against. All figures are seconds.
    """

    wall: float
    cpu: float
    probe_cpu: tuple[float, ...]
    baseline: float = PROBE_BASELINE_CPU_SECONDS

    @property
    def factor(self) -> float:
        return normalization_factor(self.probe_cpu, baseline=self.baseline)

    @property
    def normalized(self) -> float:
        return self.cpu * self.factor


def normalization_factor(
    probe_cpu: Sequence[float],
    *,
    baseline: float = PROBE_BASELINE_CPU_SECONDS,
) -> float:
    """Return the factor that converts measured CPU into reference CPU.

    ``probe_cpu`` is every calibration-probe reading taken around the measured
    workload; their mean is used, so a load change partway through the run is
    split between the two brackets rather than missed entirely.
    """
    if not probe_cpu:
        raise ValueError("normalization needs at least one calibration probe")
    mean = fmean(probe_cpu)
    if mean <= 0.0:
        raise ValueError(f"calibration probe measured non-positive CPU: {mean!r}")
    return baseline / mean


def normalize_seconds(
    cpu_seconds: float,
    probe_cpu: Sequence[float],
    *,
    baseline: float = PROBE_BASELINE_CPU_SECONDS,
) -> float:
    """Scale ``cpu_seconds`` onto the reference host's quiet-second scale."""
    return cpu_seconds * normalization_factor(probe_cpu, baseline=baseline)


def describe_measurement(measurement: Measurement, budget: float) -> str:
    """Render every input to the budget verdict, for a failure message.

    A future failure of the guard has to be immediately readable as either "the
    contract set really grew" or "the normalization broke", so print the raw
    wall clock, the raw child CPU, both probe readings, the factor they imply,
    and the normalized figure the budget is actually compared against.
    """
    probes = ", ".join(f"{value:.3f}s" for value in measurement.probe_cpu)
    return (
        f"contract set normalized to {measurement.normalized:.1f}s of "
        f"reference CPU, over the {budget:.0f}s budget\n"
        f"  raw wall:           {measurement.wall:.1f}s\n"
        f"  raw child CPU:      {measurement.cpu:.1f}s\n"
        f"  calibration probes: {probes} "
        f"(baseline {measurement.baseline:.3f}s)\n"
        f"  normalization:      x{measurement.factor:.3f}\n"
        "If the probes read near the baseline, the set grew: trim it per the "
        "curation procedure in plans/202608/test_suite_tier1.md rather than "
        "raising the budget. If the probes are far off the baseline, suspect "
        "the normalization instead."
    )


def child_cpu_seconds() -> float:
    """Return cumulative user+system CPU of this process's reaped children.

    ``RUSAGE_CHILDREN`` is per-process, not per-call, so deltas around a
    ``subprocess.run`` are only meaningful while no *other* child of this
    process is running concurrently -- true here because pytest runs a worker's
    tests sequentially. Grandchildren are included transitively as long as each
    intervening parent waits on its own children, which ``subprocess.run``
    does.
    """
    assert resource is not None, "child CPU measurement needs Unix `resource`"
    usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    return usage.ru_utime + usage.ru_stime


def run_measured(
    command: Sequence[str],
    *,
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
) -> tuple[subprocess.CompletedProcess[str], float, float]:
    """Run ``command``, returning it with its wall and child-CPU cost."""
    before = child_cpu_seconds()
    start = time.monotonic()
    proc = subprocess.run(
        list(command),
        cwd=cwd,
        env=dict(env) if env is not None else None,
        capture_output=True,
        text=True,
        check=False,
    )
    wall = time.monotonic() - start
    cpu = child_cpu_seconds() - before
    return proc, wall, cpu


def run_calibration_probe(
    python: str,
    *,
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
) -> float:
    """Run :data:`PROBE_SOURCE` once and return its child CPU seconds."""
    proc, _, cpu = run_measured([python, "-c", PROBE_SOURCE], cwd=cwd, env=env)
    if proc.returncode != 0:
        raise RuntimeError(
            f"calibration probe failed (exit {proc.returncode}):\n"
            f"{proc.stdout}\n{proc.stderr}"
        )
    return cpu
