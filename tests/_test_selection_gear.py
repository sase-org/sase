"""The middle gear: a small, non-blocking lease for an over-budget selection.

The diff-scoped lane has had two gears and nothing between them: one worker
with no lease at all, or the whole governed suite. A selection that is too
expensive to run serially but far smaller than the suite has no good option
between them, and the epic measured what that costs — the worst run in the real
store, a 494-file selection, took 1,032.6s serially where the 232s full lane
would have finished it, and at four workers the same selection is ~258s.

This module owns the third gear. When
:data:`tests._test_selection_rules.RULE_SERIAL_BUDGET_EXCEEDED` is the *only*
reason a run escalated, ``tools/run_pytest`` asks the suite gate for a handful
of worker tokens and, if it gets them, runs the selection at that width instead
of handing the whole suite to the full lane.

Two properties are load-bearing, and both are refusals rather than features:

* **It never queues.** The lane's defining promise is that it does not wait
  behind another agent's run, so the request is a single non-blocking attempt
  (:meth:`tests._suite_gate.WorkerTokenLease.try_acquire`). A grant that is not
  available *right now* is not taken, and the run escalates exactly as it would
  have without this module.
* **It never widens itself.** The ceiling is small
  (:data:`DEFAULT_SCOPED_WORKER_CEILING`) and the width is the gate's answer,
  not the caller's request — which is why ``tools/run_pytest`` still rejects
  ``-n`` and ``SASE_PYTEST_WORKERS`` in scoped mode. An arbitrary subset run at
  an arbitrary width is the unaccounted-demand shape the gate exists to
  prevent; a leased subset run at a leased width is not.

Every outcome is recorded on the manifest under ``gear``, granted or refused,
so ``just selection-health`` can say how often the third gear engaged and a
duration recorded at width 4 is never mistaken for a serial one.
"""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from tests._suite_gate import (
    WorkerTokenLease,
    configured_token_budget,
    gate_directory,
)


#: Caps the tokens the scoped lane will ask for. Deliberately small: the gear
#: exists to make one agent's over-budget selection cheap, not to give the
#: scoped lane a second claim on the host the full lane already governs.
#: Setting it below :data:`SCOPED_WORKER_FLOOR` turns the gear off.
SCOPED_WORKER_CEILING_ENV = "SASE_TEST_SELECTION_SCOPED_WORKER_CEILING"
DEFAULT_SCOPED_WORKER_CEILING = 4

#: A one-token grant is a serial run carrying xdist's bookkeeping, so it is
#: never worth leasing for. Below this the gear declines its own grant.
SCOPED_WORKER_FLOOR = 2

#: Why the gear did not engage. Values rather than prose: the manifest records
#: them and `just selection-health` counts them.
REFUSED_TOKENS_UNAVAILABLE = "tokens-unavailable"
#: An outer governed run already accounts for this process's demand (the full
#: lane sets ``SASE_TEST_GATE_DISABLED`` for its descendants). Spawning workers
#: under it would be exactly the unaccounted demand the gate exists to stop.
REFUSED_GATE_DISABLED = "gate-disabled"
#: The ceiling was configured below :data:`SCOPED_WORKER_FLOOR`.
REFUSED_GEAR_DISABLED = "gear-disabled"
#: Something about this run has to be serial regardless of the budget —
#: ``--inline-snapshot=fix/review`` rewrites source files as it goes.
REFUSED_SERIAL_REQUIRED = "serial-required"
#: The pool itself objected (malformed capacity metadata, or an explicit
#: ``SASE_TEST_GATE_SLOTS`` that disagrees with the running pool). Escalating
#: is the honest answer: the full lane will raise the same objection, loudly,
#: rather than the scoped lane failing a run over a gate it was only asking.
REFUSED_GATE_ERROR = "gate-error"


def scoped_worker_ceiling(environ: Mapping[str, str] | None = None) -> int:
    """The configured ceiling, or the default; never negative.

    An unparseable or negative value reads as the default rather than raising:
    this knob only ever makes a run *cheaper*, and failing a verification run
    over it would be a worse answer than ignoring it.
    """
    environ = os.environ if environ is None else environ
    raw = environ.get(SCOPED_WORKER_CEILING_ENV)
    if raw is None or not raw.strip():
        return DEFAULT_SCOPED_WORKER_CEILING
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_SCOPED_WORKER_CEILING
    return max(0, value)


@dataclass(frozen=True)
class ScopedGear:
    """What the gear was asked for, and what it got."""

    #: ``False`` when the run never reached the gear at all — a change-set rule
    #: escalated, or nothing escalated. No ``gear`` block is recorded then.
    attempted: bool = False
    #: The granted width, or ``None`` when the gear did not run the selection.
    worker_count: int | None = None
    ceiling: int = DEFAULT_SCOPED_WORKER_CEILING
    #: One of the ``REFUSED_*`` values when :attr:`granted` is ``False``.
    reason: str | None = None

    @property
    def granted(self) -> bool:
        return self.worker_count is not None

    def payload(self) -> dict[str, Any]:
        return {
            "granted": self.granted,
            "worker_count": self.worker_count,
            "ceiling": self.ceiling,
            "floor": SCOPED_WORKER_FLOOR,
            "reason": self.reason,
        }


def engage_scoped_gear(
    *,
    serial_required: bool = False,
    environ: Mapping[str, str] | None = None,
    directory: Path | None = None,
) -> tuple[ScopedGear, WorkerTokenLease | None]:
    """Try once for a bounded grant; return the outcome and the held lease.

    The lease comes back to the caller rather than being managed here because
    it must live exactly as long as the pytest run it governs — ``run_pytest``
    releases it in the same ``finally`` that releases the full lane's.
    """
    environ = os.environ if environ is None else environ
    ceiling = scoped_worker_ceiling(environ)
    if serial_required:
        return ScopedGear(
            attempted=True, ceiling=ceiling, reason=REFUSED_SERIAL_REQUIRED
        ), None
    if ceiling < SCOPED_WORKER_FLOOR:
        return ScopedGear(
            attempted=True, ceiling=ceiling, reason=REFUSED_GEAR_DISABLED
        ), None
    if environ.get("SASE_TEST_GATE_DISABLED") == "1":
        return ScopedGear(
            attempted=True, ceiling=ceiling, reason=REFUSED_GATE_DISABLED
        ), None

    budget, capacity_is_explicit = configured_token_budget()
    lease = WorkerTokenLease(
        directory=gate_directory() if directory is None else directory,
        budget=budget,
        # Non-blocking by construction, but a zero timeout is set anyway so a
        # future reader of this call cannot mistake it for a waiting one.
        timeout=0.0,
        capacity_is_explicit=capacity_is_explicit,
        governed=True,
    )
    try:
        granted = lease.try_acquire(SCOPED_WORKER_FLOOR, ceiling)
    except pytest.UsageError:
        return ScopedGear(
            attempted=True, ceiling=ceiling, reason=REFUSED_GATE_ERROR
        ), None
    if granted < SCOPED_WORKER_FLOOR:
        # `_fit_request_to_budget` clamps the floor to a tiny host's budget, so
        # a one-token grant is reachable even though it was not asked for.
        lease.release()
        return (
            ScopedGear(
                attempted=True, ceiling=ceiling, reason=REFUSED_TOKENS_UNAVAILABLE
            ),
            None,
        )
    return ScopedGear(attempted=True, worker_count=granted, ceiling=ceiling), lease


def manifest_with_gear(
    manifest: Mapping[str, Any],
    gear: ScopedGear,
    *,
    selected: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Record the gear's outcome on the manifest the run really happened under.

    With ``selected``, the escalation is *withdrawn*: the run is about to
    execute exactly those files at the granted width, so recording it as
    escalated would hand the health store a run that ran a selection while
    claiming it ran everything — and, because escalated runs record
    ``duration: 0.0``, would hide the gear's real cost behind a zero. The rule
    that fired stays on ``rules_fired``: ``serial-budget-exceeded`` is *why*
    the gear engaged, and erasing it would make the third gear invisible.
    """
    payload = {**manifest, "gear": gear.payload()}
    if selected is None:
        return payload
    payload["escalated"] = False
    payload["selected"] = list(selected)
    payload["selected_count"] = len(selected)
    return payload
