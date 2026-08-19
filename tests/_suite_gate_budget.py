"""How wide a pytest run is allowed to be, and how wide this host can afford.

Split out of :mod:`tests._suite_gate`. Two separate questions live here. The
*host budget* is how many worker tokens exist at all — configured explicitly or
computed from CPUs and available memory. The *request range* is how many of
them one run may ask for. :func:`fit_request_to_budget` is where the second is
reconciled against the first.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from tests._suite_gate_env import positive_int


_DEFAULT_AUTOMATIC_FLOOR = 4
_DEFAULT_AUTOMATIC_CEILING = 28
_DEFAULT_AUTOMATIC_FAIR_SHARE_RUNS = 2
_DEFAULT_HARD_TOKEN_LIMIT = 32
# Reserve a proportion of the host rather than a flat count. A flat 4 is noise
# on the 64-core development host but is the entire machine on a 4-vCPU CI
# runner, where it collapsed the budget to one token and made the whole CI test
# matrix run serially.
_RESERVED_CPU_DIVISOR = 8
_MINIMUM_RESERVED_CPUS = 1
_RESERVED_MEMORY_KIB = 8 * 1024 * 1024
# Phase sase-ib.5 remeasured worker RSS after the footprint fixes at
# start=144292/post_collection=500632/median=500632/peak=500632 KiB in cost
# record 20260809T164811Z-3964960.json. Reserving 700 MiB per token keeps
# roughly 40% headroom over that peak while reflecting the measured curve.
_MEMORY_KIB_PER_WORKER = 700 * 1024
_MISSING_MEMORY_TOKEN_LIMIT = 4
_MEMINFO_PATH = Path("/proc/meminfo")


def configured_token_budget() -> tuple[int, bool]:
    """Return the configured/computed host budget and whether it is explicit."""
    configured = os.environ.get("SASE_TEST_GATE_SLOTS")
    if configured is not None:
        return positive_int("SASE_TEST_GATE_SLOTS", configured), True
    return (
        _calculate_default_token_budget(
            cpu_count=os.cpu_count(),
            mem_available_kib=_read_mem_available_kib(_MEMINFO_PATH),
        ),
        False,
    )


def automatic_worker_range(budget: int) -> tuple[int, int]:
    """Return the validated floor and ceiling for an automatic runner lease."""
    floor_raw = os.environ.get("SASE_PYTEST_WORKER_FLOOR")
    ceiling_raw = os.environ.get("SASE_PYTEST_WORKER_CEILING")
    floor = (
        min(_DEFAULT_AUTOMATIC_FLOOR, budget)
        if floor_raw is None
        else positive_int("SASE_PYTEST_WORKER_FLOOR", floor_raw)
    )
    ceiling = (
        _default_automatic_ceiling(budget, floor)
        if ceiling_raw is None
        else positive_int("SASE_PYTEST_WORKER_CEILING", ceiling_raw)
    )
    if floor > budget:
        raise pytest.UsageError(
            f"SASE_PYTEST_WORKER_FLOOR={floor} exceeds the {budget}-token "
            "host pool; lower the floor or increase SASE_TEST_GATE_SLOTS."
        )
    if ceiling > budget:
        raise pytest.UsageError(
            f"SASE_PYTEST_WORKER_CEILING={ceiling} exceeds the {budget}-token "
            "host pool; lower the ceiling or increase SASE_TEST_GATE_SLOTS."
        )
    if floor > ceiling:
        raise pytest.UsageError(
            "SASE_PYTEST_WORKER_FLOOR must be less than or equal to "
            "SASE_PYTEST_WORKER_CEILING."
        )
    return floor, ceiling


def _default_automatic_ceiling(budget: int, floor: int) -> int:
    # A controller cannot safely return tokens after xdist workers have
    # started: the pool would undercount live worker demand. Keep the default
    # grant to a peer-sized share up front, while explicit ceilings remain the
    # opt-in route for a deliberately wider single run.
    automatic_capacity = min(_DEFAULT_AUTOMATIC_CEILING, budget)
    fair_share = automatic_capacity // _DEFAULT_AUTOMATIC_FAIR_SHARE_RUNS
    return min(_DEFAULT_AUTOMATIC_CEILING, max(floor, fair_share))


def _calculate_default_token_budget(
    *, cpu_count: int | None, mem_available_kib: int | None
) -> int:
    if cpu_count is None or cpu_count < 1:
        cpu_limit = 1
    else:
        reserved_cpus = max(_MINIMUM_RESERVED_CPUS, cpu_count // _RESERVED_CPU_DIVISOR)
        cpu_limit = max(cpu_count - reserved_cpus, 1)

    if mem_available_kib is None:
        memory_limit = _MISSING_MEMORY_TOKEN_LIMIT
    else:
        worker_memory_kib = max(mem_available_kib - _RESERVED_MEMORY_KIB, 0)
        memory_limit = max(worker_memory_kib // _MEMORY_KIB_PER_WORKER, 1)

    return max(1, min(cpu_limit, memory_limit, _DEFAULT_HARD_TOKEN_LIMIT))


def _read_mem_available_kib(path: Path) -> int | None:
    try:
        meminfo = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return None

    for line in meminfo.splitlines():
        key, separator, value = line.partition(":")
        if key != "MemAvailable" or not separator:
            continue
        fields = value.split()
        if len(fields) < 2 or fields[1].lower() != "kb":
            return None
        try:
            available_kib = int(fields[0])
        except ValueError:
            return None
        return available_kib if available_kib >= 0 else None
    return None


def fit_request_to_budget(
    floor: int,
    ceiling: int,
    budget: int,
    *,
    exact: bool,
    capacity_is_explicit: bool,
) -> tuple[int, int]:
    """Clamp a floor/ceiling to ``budget``; refuse an over-budget exact ask.

    Public because the bypass path in ``tools/run_pytest`` bounds itself with
    the same arithmetic and the same error text as a real acquisition, rather
    than reimplementing either.
    """
    if exact and ceiling > budget:
        capacity_source = (
            "SASE_TEST_GATE_SLOTS" if capacity_is_explicit else "computed host budget"
        )
        raise pytest.UsageError(
            f"Requested {ceiling} pytest worker tokens, but the {capacity_source} "
            f"permits only {budget}. Reduce SASE_PYTEST_WORKERS/-n or increase "
            "SASE_TEST_GATE_SLOTS deliberately."
        )
    return min(floor, budget), min(ceiling, budget)
