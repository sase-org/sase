"""Pre-spawn host admission gate for capped named ToolRuns.

``tool_runs.admission.max_concurrent`` caps how many runs of a named tool
execute their child at once on this host, across every project. The ToolRun
ledger is the queue: sase-core records the run's ``demand.admission`` and
decides FIFO slot grants atomically; this module is the Python glue that
sleeps, prints, probes peer wrappers, and reconciles dead ones.

The gate runs at the top of ``run_recorded_body``, after the run is recorded
and ``running`` and before anything is spawned. Unset config costs no core
call. Admission is load shaping, never a correctness gate, so every failure
falls open with one ``admission unavailable`` line.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import random
import sys
import time
from typing import Any

from sase.telemetry.metrics import TOOL_RUN_ADMISSION_WAIT, TOOL_RUN_ADMISSIONS
from sase.tool.executor_display import write_display
from sase.tool.executor_models import RecordedRunContext
from sase.tool.executor_signals import SignalState
from sase.tool.observe import inc_tool_metric

#: Seconds between core polls while waiting (plus up to the jitter below).
POLL_SECONDS = 1.0
POLL_JITTER_SECONDS = 0.2
#: Signal flags are checked this often between polls.
SLICE_SECONDS = 0.1
#: Peer wrappers are probed at least this often (and as soon as the
#: queue position stalls).
SWEEP_SECONDS = 5.0
#: Store errors that persist this long fall open.
STORE_ERROR_GRACE_SECONDS = 30.0
_BUSY_TIMEOUT_MS = 2000
_UNSETTLED_STATES = frozenset({"created", "running"})


@dataclass(frozen=True)
class _AdmissionResult:
    """What the body does next.

    ``proceed`` false means the wait ended without a slot (stop, signal,
    timeout, or the run settled underneath it): the command must not run.
    ``waited`` says an admission record exists for this run.
    """

    proceed: bool = True
    waited: bool = False
    stop_requested: bool = False
    timeout_requested: bool = False
    unavailable: _UnavailableAdmission | None = None


@dataclass
class _UnavailableAdmission:
    """Evidence needed to recover an unavailable fail-open admission."""

    key: str
    limit: int
    bypass_ts_ms: int
    recorded: bool = False


_PROCEED = _AdmissionResult()


class _AdmissionUnavailable(Exception):
    """Admission cannot run; the command proceeds without a slot."""


def admit_before_spawn(
    ctx: RecordedRunContext,
    signals: SignalState,
    *,
    show_header: Callable[[], None],
) -> _AdmissionResult:
    """Wait for a host slot when this run's named tool is capped.

    Returns at once, with no core call, for ad-hoc runs, uncapped tools, and
    nested runs (a run inside another unsettled ToolRun never waits, so a
    nested ``sase tool run check`` cannot deadlock its holder).
    """

    resolved = ctx.resolved
    tool = resolved.tool_name
    if resolved.adhoc or not tool:
        return _PROCEED
    try:
        from sase.config.tool_admission import get_tool_runs_admission_config

        policy = get_tool_runs_admission_config()
    except Exception as exc:  # noqa: BLE001 - invalid config falls open.
        _unavailable(tool, str(exc), show_header)
        return _PROCEED
    limit = policy.limit_for(tool)
    if limit is None:
        return _PROCEED
    if _is_nested_run(ctx.parent_run_id, ctx.run_id):
        return _PROCEED
    if not ctx.recorded:
        _unavailable(tool, "run not recorded", show_header)
        return _PROCEED
    gate = _AdmissionWait(
        ctx,
        signals,
        tool=tool,
        limit=limit,
        max_wait_seconds=policy.max_wait_seconds,
        show_header=show_header,
    )
    try:
        return gate.run()
    except _AdmissionUnavailable as exc:
        return gate._unavailable_result(str(exc))


def _is_nested_run(parent_id: str | None, run_id: str) -> bool:
    """Return whether the effective owner names a live parent ToolRun.

    ``parent_id`` comes from resolved ownership (or the adopted run's stored
    owner fields), so an inherited id that ownership cleared for a new agent
    cannot exempt that agent. An unreadable effective parent counts as nested:
    exempting a run can only fail open.
    """

    if not parent_id or parent_id == run_id:
        return False
    try:
        from sase.core.tool_run import tool_run_show

        run = tool_run_show(parent_id).get("run")
    except Exception:  # noqa: BLE001 - unknown parent is exempt (fail open).
        return True
    if not isinstance(run, dict):
        return False
    return str(run.get("state") or "") in _UNSETTLED_STATES


class _AdmissionWait:
    """One run's enter-then-poll loop."""

    def __init__(
        self,
        ctx: RecordedRunContext,
        signals: SignalState,
        *,
        tool: str,
        limit: int,
        max_wait_seconds: int,
        show_header: Callable[[], None],
    ) -> None:
        self.ctx = ctx
        self.signals = signals
        self.tool = tool
        self.limit = limit
        self.max_wait_seconds = max_wait_seconds
        self.show_header = show_header
        self.entered = False
        self.started = time.monotonic()
        self._error_since: float | None = None
        self._last_counts: tuple[int, int] | None = None
        self._last_sweep = self.started
        self._swept_since_move = False

    def run(self) -> _AdmissionResult:
        result = self._enter()
        while result is None:
            stopped = self._sleep_until_next_poll()
            if stopped is not None:
                return stopped
            result = self._enter()
        self.entered = True
        while True:
            outcome = str(result.get("outcome") or "")
            if outcome == "admitted":
                return self._admitted(result)
            if outcome == "settled":
                return self._abandon("the run settled", stop=True)
            if outcome != "waiting":
                raise _AdmissionUnavailable(f"run {outcome or 'missing'} in core")
            moved = self._report_waiting(result)
            if self._max_wait_exceeded():
                return self._force()
            if self._sweep_due(moved=moved) and self._sweep(result):
                polled = self._poll()
                if polled is not None:
                    result = polled
                    continue
            stopped = self._sleep_until_next_poll()
            if stopped is not None:
                return stopped
            polled = self._poll()
            if polled is not None:
                result = polled

    # -- core calls -------------------------------------------------------

    def _enter(self) -> dict[str, Any] | None:
        return self._call(
            "tool_run_admission_enter",
            {
                "schema_version": 1,
                "run_id": self.ctx.run_id,
                "key": self.tool,
                "limit": self.limit,
            },
        )

    def _poll(self) -> dict[str, Any] | None:
        return self._call(
            "tool_run_admission_poll",
            {"schema_version": 1, "run_id": self.ctx.run_id},
        )

    def _call(self, name: str, request: dict[str, Any]) -> dict[str, Any] | None:
        """Return the core result, ``None`` on a transient store error.

        A missing binding (a stale ``sase_core_rs``) falls open at once;
        store errors fall open once they persist past the grace period.
        """

        try:
            from sase.core import tool_run as core

            call = getattr(core, name)
            result = call(request, busy_timeout_ms=_BUSY_TIMEOUT_MS)
        except (ImportError, AttributeError) as exc:
            raise _AdmissionUnavailable(_binding_reason(exc)) from exc
        except Exception as exc:  # noqa: BLE001 - store errors retry, then fall open.
            now = time.monotonic()
            if self._error_since is None:
                self._error_since = now
            if now - self._error_since >= STORE_ERROR_GRACE_SECONDS:
                raise _AdmissionUnavailable(f"store error: {exc}") from exc
            return None
        self._error_since = None
        return result

    # -- loop steps -------------------------------------------------------

    def _sleep_until_next_poll(self) -> _AdmissionResult | None:
        deadline = (
            time.monotonic() + POLL_SECONDS + random.uniform(0, POLL_JITTER_SECONDS)
        )
        while True:
            stopped = self._stop_check(fast=True)
            if stopped is not None:
                return stopped
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return self._stop_check(fast=False)
            time.sleep(min(SLICE_SECONDS, remaining))

    def _stop_check(self, *, fast: bool) -> _AdmissionResult | None:
        """Leave the wait on a signal, a durable stop, or an owner timeout.

        Signal flags are free to read; the stop and timeout probes may read
        the store, so they run once per poll (``fast=False``).
        """

        if self.signals.sigint:
            return self._abandon("SIGINT")
        if self.signals.sigterm:
            return self._abandon("SIGTERM")
        if fast:
            return None
        if _probe(self.ctx.stop_recorded):
            return self._abandon("stop requested", stop=True)
        if _probe(self.ctx.timeout_recorded):
            return self._abandon("owner timeout", timeout=True)
        return None

    def _report_waiting(self, result: dict[str, Any]) -> bool:
        """Print the waiting line when the counts change; return whether they did."""

        holders = len(result.get("holders") or ())
        ahead = int(result.get("ahead") or 0)
        counts = (holders, ahead)
        if counts == self._last_counts:
            return False
        if self._last_counts is None:
            self.show_header()
        self._last_counts = counts
        self._swept_since_move = False
        _say(
            f"sase: waiting for a {self.tool} slot "
            f"(limit {self.limit}: {holders} running, {ahead} ahead)"
        )
        return True

    def _sweep_due(self, *, moved: bool) -> bool:
        if time.monotonic() - self._last_sweep >= SWEEP_SECONDS:
            return True
        # A position that stops moving earns one immediate sweep.
        return not moved and not self._swept_since_move

    def _sweep(self, result: dict[str, Any]) -> bool:
        """Reconcile peers whose wrapper is definitively dead.

        Returns whether anything was reconciled, so the caller re-polls at
        once instead of sleeping on a slot that just freed.
        """

        from sase.tool.liveness import probe_wrapper, reconcile_tool_runs_by_id

        self._last_sweep = time.monotonic()
        self._swept_since_move = True
        dead: list[str] = []
        for peer in [
            *(result.get("holders") or ()),
            *(result.get("waiters_ahead") or ()),
        ]:
            if not isinstance(peer, dict):
                continue
            run_id = str(peer.get("run_id") or "")
            if not run_id or run_id == self.ctx.run_id:
                continue
            observation = probe_wrapper(
                peer.get("wrapper_pid"),
                str(peer.get("boot_id") or ""),
                peer.get("process_start_identity"),
            )
            if observation == "dead":
                dead.append(run_id)
        if not dead:
            return False
        reconciled = reconcile_tool_runs_by_id(dead, reap_orphans=True)
        return bool(reconciled.get("marked_lost"))

    def _max_wait_exceeded(self) -> bool:
        if self.max_wait_seconds <= 0:
            return False
        return time.monotonic() - self.started >= self.max_wait_seconds

    # -- endings ----------------------------------------------------------

    def _admitted(self, result: dict[str, Any]) -> _AdmissionResult:
        waited_seconds = _wait_seconds(result, self.started)
        admission = result.get("admission")
        admitted_by = (
            str(admission.get("admitted_by") or "")
            if isinstance(admission, dict)
            else ""
        )
        if admitted_by == "max_wait":
            self._say_max_wait(waited_seconds)
            _count("forced", waited_seconds)
            return _AdmissionResult(waited=True)
        if admitted_by == "unavailable":
            self._say_unavailable_committed()
            _count("unavailable", waited_seconds)
            return _AdmissionResult(waited=True)
        if admitted_by != "slot":
            return self._unavailable_result(
                f"admission grant has unknown reason {admitted_by or 'missing'}"
            )
        if self._last_counts is not None:
            _say(
                f"sase: {self.tool} slot granted after "
                f"{_format_seconds(waited_seconds)}"
            )
        _count("admitted", waited_seconds)
        return _AdmissionResult(waited=True)

    def _force(self) -> _AdmissionResult:
        request = {
            "schema_version": 1,
            "run_id": self.ctx.run_id,
            "reason": "max_wait",
        }
        while True:
            stopped = self._stop_check(fast=False)
            if stopped is not None:
                return stopped
            try:
                result = self._call(
                    "tool_run_admission_force",
                    request,
                )
            except _AdmissionUnavailable as exc:
                return self._unavailable_result(str(exc))
            if result is None:
                stopped = self._sleep_until_next_poll()
                if stopped is not None:
                    return stopped
                continue
            outcome = str(result.get("outcome") or "")
            if outcome == "settled":
                return self._abandon("the run settled", stop=True)
            if outcome == "not_found":
                return self._unavailable_result("run not found in core")
            if outcome != "admitted":
                return self._unavailable_result(
                    f"force returned {outcome or 'no outcome'}"
                )
            return self._admitted(result)

    def _say_max_wait(self, waited_seconds: float) -> None:
        _say(
            f"sase: no {self.tool} slot after {_format_seconds(waited_seconds)} "
            f"(max_wait_seconds {self.max_wait_seconds}); "
            f"running over the limit of {self.limit}"
        )

    def _say_unavailable_committed(self) -> None:
        self.show_header()
        _say(
            f"sase: {self.tool} admission unavailable; "
            "running through the recorded bypass"
        )

    def _unavailable_result(self, reason: str) -> _AdmissionResult:
        waited_seconds = time.monotonic() - self.started
        _unavailable(
            self.tool,
            reason,
            self.show_header,
            waited_seconds=waited_seconds,
        )
        evidence = _UnavailableAdmission(
            key=self.tool,
            limit=self.limit,
            bypass_ts_ms=time.time_ns() // 1_000_000,
        )
        return _AdmissionResult(waited=self.entered, unavailable=evidence)

    def _abandon(
        self, reason: str, *, stop: bool = False, timeout: bool = False
    ) -> _AdmissionResult:
        waited_seconds = time.monotonic() - self.started
        self.show_header()
        _say(
            f"sase: stopped waiting for a {self.tool} slot ({reason}); "
            "command was not run"
        )
        _count("abandoned", waited_seconds)
        return _AdmissionResult(
            proceed=False,
            waited=self.entered,
            stop_requested=stop,
            timeout_requested=timeout,
        )


def _probe(probe: Callable[[], bool] | None) -> bool:
    if probe is None:
        return False
    try:
        return bool(probe())
    except Exception:  # noqa: BLE001 - a probe must not break the wait.
        return False


def _binding_reason(exc: BaseException) -> str:
    text = str(exc)
    if "binding" in text or isinstance(exc, ImportError):
        return "sase_core_rs lacks the admission bindings; reinstall sase-core"
    return text or type(exc).__name__


def _wait_seconds(result: dict[str, Any], started: float) -> float:
    admission = result.get("admission")
    if isinstance(admission, dict):
        wait_ms = admission.get("wait_ms")
        if type(wait_ms) is int:
            return wait_ms / 1000
    return time.monotonic() - started


def _format_seconds(seconds: float) -> str:
    from sase.tool.render import format_duration_ms

    return format_duration_ms(max(0, int(seconds * 1000)))


def _count(outcome: str, waited_seconds: float | None = None) -> None:
    inc_tool_metric(TOOL_RUN_ADMISSIONS, outcome=outcome)
    if waited_seconds is None:
        return
    try:
        TOOL_RUN_ADMISSION_WAIT.labels(outcome=outcome).observe(
            max(0.0, waited_seconds)
        )
    except Exception:  # noqa: BLE001 - metrics cannot change the child.
        pass


def _say(line: str) -> None:
    write_display(sys.stderr, f"{line}\n".encode())


def record_unavailable_admission(
    ctx: RecordedRunContext, evidence: _UnavailableAdmission | None
) -> bool:
    """Try to record a fail-open run as a holder using its pre-spawn time.

    Each call is bounded by the core busy timeout. The caller retries at the
    existing spawn, demand-recording, and settlement points, never by delaying
    the child until the store recovers.
    """

    if evidence is None:
        return True
    if evidence.recorded:
        return True
    if not ctx.recorded:
        return False
    try:
        from sase.core.tool_run import tool_run_admission_force

        result = tool_run_admission_force(
            {
                "schema_version": 1,
                "run_id": ctx.run_id,
                "reason": "unavailable",
                "now_ms": evidence.bypass_ts_ms,
                "key": evidence.key,
                "limit": evidence.limit,
            },
            busy_timeout_ms=_BUSY_TIMEOUT_MS,
        )
    except Exception:  # noqa: BLE001 - recovery never delays child/settlement.
        return False
    if not isinstance(result, dict) or str(result.get("outcome") or "") != "admitted":
        return False
    # Core preserves any existing real slot/max-wait grant. Either way, an
    # admitted result proves the ledger no longer says this executed run was
    # abandoned.
    evidence.recorded = True
    return True


def unavailable_admission_diagnostic(
    evidence: _UnavailableAdmission | None,
) -> str | None:
    """Return the durable diagnostic needed when recovery never succeeded."""

    if evidence is None or evidence.recorded:
        return None
    return "admission bypass evidence incomplete: unavailable run was executed"


def _unavailable(
    tool: str,
    why: str,
    show_header: Callable[[], None],
    *,
    waited_seconds: float | None = None,
) -> None:
    show_header()
    _say(f"sase: {tool} admission unavailable ({why}); running without a slot")
    _count("unavailable", waited_seconds)


__all__ = [
    "admit_before_spawn",
    "record_unavailable_admission",
    "unavailable_admission_diagnostic",
]
