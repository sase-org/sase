"""Scheduler-job sweep for update-skew auto-restart.

The ``agent_auto_restart`` scheduler job enumerates recovery work and
submits the healer as a durable proc; it never heals inline. Candidate
enumeration is shared with ``sase agent auto-restart run -p`` through
:func:`healer.resolve_pending_targets`.

Idle ticks stay cheap: doorbell and ledger directory listings are a
handful of ``stat()`` calls, and the expensive failed-row artifact scan
runs only when a cheap signal suggests work (a doorbell, an actionable
ledger record) or when the full-sweep interval (60 s, matching the job's
``max_quiet`` backstop) has elapsed.

When the feature is off or the storm breaker paused, pending failures are
re-surfaced loudly, their doorbells cleared, and their ``done.json``
recovery marked ``declined`` — disabling the feature never swallows a
failure, and the ledger is never written on this path.
"""

from __future__ import annotations

import contextlib
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sase.agent.auto_restart.healer import HealerTarget

CONCURRENCY_KEY = "agent-auto-restart"
HEALER_ARGV = ["sase", "agent", "auto-restart", "run", "-p", "-j"]
HEALER_PROC_TIMEOUT_SECONDS = 1800
FULL_SWEEP_INTERVAL_SECONDS = 60.0

_ACTIONABLE_LEDGER_STATES = frozenset({"claimed", "launching", "deferred"})
_TERMINAL_LEDGER_STATES = frozenset({"declined", "settled_ok", "settled_failed"})


@dataclass
class _JobWork:
    """One sweep's worth of recovery work."""

    doorbells: list[dict[str, Any]] = field(default_factory=list)
    targets: list[HealerTarget] = field(default_factory=list)
    new_targets: list[HealerTarget] = field(default_factory=list)
    stale_claim_keys: list[str] = field(default_factory=list)
    deferred_keys: list[str] = field(default_factory=list)
    launched_keys: list[str] = field(default_factory=list)
    stale_pending: list[HealerTarget] = field(default_factory=list)
    full_scan: bool = False

    @property
    def actionable(self) -> bool:
        """Return whether any healer work exists for a proc submission."""
        return bool(
            self.doorbells
            or self.new_targets
            or self.stale_claim_keys
            or self.deferred_keys
        )


@dataclass(frozen=True)
class _TickResult:
    """What one job tick did."""

    action: str
    reason: str
    targets: int = 0
    resurfaced: int = 0
    settled: int = 0


def _sweep_stamp_path() -> Path:
    from sase.agent.auto_restart.ledger import auto_restart_root

    return auto_restart_root() / "last_full_sweep"


def _full_sweep_due(now: float) -> bool:
    try:
        stamp = float(_sweep_stamp_path().read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return True
    return now - stamp >= FULL_SWEEP_INTERVAL_SECONDS


def _record_full_sweep(now: float) -> None:
    try:
        path = _sweep_stamp_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"{now}\n", encoding="utf-8")
    except OSError:
        pass


def _collect_job_work(*, now: float | None = None) -> _JobWork:
    """Enumerate recovery work, running the artifact scan only when due."""
    from sase.agent.auto_restart import ledger as ledger_mod
    from sase.agent.auto_restart.healer import resolve_pending_targets

    at = time.time() if now is None else now
    work = _JobWork()
    try:
        work.doorbells = ledger_mod.list_doorbells()
    except Exception:
        work.doorbells = []
    try:
        # Mtime-gated: an unchanged ledger costs one stat(), not one read
        # per record, so idle ticks stay at a handful of stat() calls.
        records = ledger_mod.iter_ledger_records_cached()
    except Exception:
        records = []
    owned_dirs: set[str] = set()
    for stored in records:
        try:
            state = stored.record.state
            failed = stored.record.failed_artifacts_dir
        except AttributeError:
            continue
        if isinstance(failed, str) and failed:
            owned_dirs.add(failed)
        key = stored.record.key
        if state in ("claimed", "launching"):
            with contextlib.suppress(Exception):
                if not ledger_mod.claimer_is_live(stored):
                    work.stale_claim_keys.append(key)
        elif state == "deferred":
            work.deferred_keys.append(key)
        elif state == "launched":
            work.launched_keys.append(key)
    for doorbell in work.doorbells:
        raw = doorbell.get("artifacts_dir")
        if raw:
            owned_dirs.add(str(raw))
    cheap_signal = bool(
        work.doorbells
        or work.stale_claim_keys
        or work.deferred_keys
        or any(
            getattr(stored.record, "state", None) in _ACTIONABLE_LEDGER_STATES
            for stored in records
        )
    )
    if cheap_signal or _full_sweep_due(at):
        work.full_scan = True
        try:
            work.targets = resolve_pending_targets(now=at)
        except Exception:
            work.targets = []
        _record_full_sweep(at)
    else:
        work.targets = []
    terminal_or_owned = set(owned_dirs)
    for stored in records:
        try:
            if stored.record.state in _TERMINAL_LEDGER_STATES:
                failed = stored.record.failed_artifacts_dir
                if isinstance(failed, str) and failed:
                    terminal_or_owned.add(failed)
        except AttributeError:
            continue
    for target in work.targets:
        if str(target.artifacts_dir) not in terminal_or_owned:
            work.new_targets.append(target)
    work.stale_pending = _stale_pending_targets(work.targets, owned_dirs, now=at)
    return work


def _stale_pending_targets(
    targets: list[HealerTarget], owned_dirs: set[str], *, now: float
) -> list[HealerTarget]:
    """Return pending rows older than the resurface horizon with no ledger."""
    try:
        from sase.config._settings_system import (
            get_agent_auto_restart_pending_resurface_seconds,
        )

        horizon = float(get_agent_auto_restart_pending_resurface_seconds())
    except Exception:
        horizon = 600.0
    stale: list[HealerTarget] = []
    for target in targets:
        if str(target.artifacts_dir) in owned_dirs:
            continue
        requested_at = _pending_requested_at(target)
        if requested_at is None:
            continue
        if now - requested_at >= horizon and _not_yet_resurfaced(target, requested_at):
            stale.append(target)
    return stale


def _pending_requested_at(target: HealerTarget) -> float | None:
    import datetime
    import json

    try:
        payload = json.loads((target.artifacts_dir / "done.json").read_text())
    except (OSError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    recovery = payload.get("recovery")
    if not isinstance(recovery, dict) or recovery.get("state") != "pending":
        return None
    requested = recovery.get("requested_at")
    if not isinstance(requested, str) or not requested:
        return None
    try:
        return datetime.datetime.fromisoformat(requested).timestamp()
    except ValueError:
        return None


def _not_yet_resurfaced(target: HealerTarget, requested_at: float) -> bool:
    """Return whether this pending row still needs its one loud re-surface."""
    from sase.agent.auto_restart.ledger import auto_restart_root

    stamp_dir = auto_restart_root() / "resurfaced"
    stamp = stamp_dir / f"{target.artifacts_dir.name}.stamp"
    try:
        seen = float(stamp.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return True
    return seen < requested_at


def _mark_resurfaced(target: HealerTarget, now: float) -> None:
    from sase.agent.auto_restart.ledger import auto_restart_root

    try:
        stamp_dir = auto_restart_root() / "resurfaced"
        stamp_dir.mkdir(parents=True, exist_ok=True)
        (stamp_dir / f"{target.artifacts_dir.name}.stamp").write_text(
            f"{now}\n", encoding="utf-8"
        )
    except OSError:
        pass


def _proc_already_queued() -> bool:
    """Return whether an auto-restart healer proc is already active."""
    try:
        from sase.procs.models.common import ACTIVE_PROC_STATUSES
        from sase.procs.store import read_procs
    except Exception:
        return False
    try:
        procs = read_procs(status=set(ACTIVE_PROC_STATUSES))
    except Exception:
        return False
    for proc in procs:
        try:
            keys = proc.concurrency_keys or ()
        except AttributeError:
            continue
        if CONCURRENCY_KEY in set(keys):
            return True
    return False


def _submit_healer_proc(*, count: int) -> bool:
    """Submit the durable healer proc; True once submission succeeds."""
    from pathlib import Path as _Path

    from sase.ops.names import AGENT_AUTO_RESTART
    from sase.procs import ProcSubmitRequest, submit_proc_request

    try:
        submit_proc_request(
            ProcSubmitRequest(
                argv=list(HEALER_ARGV),
                label=f"↻ Auto-restart {count} agent(s)",
                cwd=str(_Path.home()),
                origin="agent-auto-restart-job",
                operation=AGENT_AUTO_RESTART,
                operation_payload={"pending": True, "targets": count},
                tags=["auto-restart", "update-skew"],
                concurrency_keys=[CONCURRENCY_KEY],
                timeout_seconds=HEALER_PROC_TIMEOUT_SECONDS,
            )
        )
        return True
    except Exception:
        return False


def _settle_launched_records(*, now: float | None = None) -> int:
    """Settle ``launched`` records from their replacement's outcome.

    Keeps the report's **Now** column live: a replacement that finished
    settles its record ``settled_ok`` (or ``settled_failed``), so later
    ticks stop treating it as in flight.
    """
    import json

    from sase.agent.auto_restart import ledger as ledger_mod

    settled = 0
    try:
        records = ledger_mod.iter_ledger_records()
    except Exception:
        return 0
    for stored in records:
        try:
            if stored.record.state != "launched":
                continue
            launched = stored.record.launched_artifacts_dir
        except AttributeError:
            continue
        if not isinstance(launched, str) or not launched:
            continue
        try:
            done = json.loads((Path(launched) / "done.json").read_text())
        except (OSError, ValueError):
            continue
        if not isinstance(done, dict):
            continue
        outcome = done.get("outcome")
        if outcome == "completed":
            event, note = "settled_ok", "replacement completed"
        elif outcome in ("failed", "killed"):
            event, note = "settled_failed", f"replacement {outcome}"
        else:
            continue
        with contextlib.suppress(Exception):
            ledger_mod.advance_ledger_record(stored, event, note=note)
            settled += 1
    return settled


def _disabled_resurface_stamp(target: HealerTarget) -> Path:
    """Return the once-only stamp for the disabled/paused resurface path."""
    from sase.agent.auto_restart.ledger import auto_restart_root

    return (
        auto_restart_root()
        / "resurfaced"
        / f"disabled-{target.artifacts_dir.name}.stamp"
    )


def _disabled_already_resurfaced(target: HealerTarget) -> bool:
    try:
        return _disabled_resurface_stamp(target).is_file()
    except OSError:
        return False


def _mark_disabled_resurfaced(target: HealerTarget, now: float) -> None:
    try:
        stamp = _disabled_resurface_stamp(target)
        stamp.parent.mkdir(parents=True, exist_ok=True)
        stamp.write_text(f"{now}\n", encoding="utf-8")
    except OSError:
        pass


def _resurface_for_disabled(
    work: _JobWork, *, reason: str, now: float | None = None
) -> int:
    """Loudly re-surface silenced failures while the feature cannot act.

    Only silenced rows (a doorbell, or ``recovery.state == "pending"``)
    are handled — every other failed row already notified the user, so it
    is never touched here. Each silenced failure is re-surfaced exactly
    once (a ``resurfaced/disabled-<stamp>.stamp`` file gates repeats),
    its ``done.json`` recovery is marked ``declined``, and its doorbell is
    cleared. Never writes the ledger: disabling the feature never swallows
    a failure, and no lineage budget is spent on this path.
    """
    import json

    from sase.agent.auto_restart import ledger as ledger_mod
    from sase.agent.auto_restart.healer import HealerTarget as _Target
    from sase.agent.auto_restart.healer import write_recovery
    from sase.agent.auto_restart.notify import resurface_failure

    at = time.time() if now is None else now
    resurfaced = 0
    seen: set[str] = set()
    targets: list[_Target] = list(work.targets)
    for target in targets:
        seen.add(str(target.artifacts_dir))
    doorbell_dirs: set[str] = set()
    for doorbell in work.doorbells:
        raw = doorbell.get("artifacts_dir")
        if not raw:
            continue
        doorbell_dirs.add(str(raw))
        if str(raw) in seen:
            continue
        seen.add(str(raw))
        name = doorbell.get("agent_name")
        project = doorbell.get("project")
        if not isinstance(name, str) or not name:
            name = Path(str(raw)).name
        if not isinstance(project, str) or not project:
            project = "project"
        targets.append(
            _Target(artifacts_dir=Path(str(raw)), project=project, agent_name=name)
        )
    for target in targets:
        if not (target.artifacts_dir / "done.json").is_file():
            continue
        try:
            done = json.loads((target.artifacts_dir / "done.json").read_text())
        except (OSError, ValueError):
            continue
        if not isinstance(done, dict) or str(done.get("outcome", "")) != "failed":
            continue
        recovery = done.get("recovery")
        silenced = str(target.artifacts_dir) in doorbell_dirs or (
            isinstance(recovery, dict) and recovery.get("state") == "pending"
        )
        if not silenced:
            continue
        if _disabled_already_resurfaced(target):
            continue
        with contextlib.suppress(Exception):
            resurface_failure(
                agent_name=target.agent_name,
                reason_text=f"auto-restart {reason}; the failure needs a manual ,x",
                artifacts_dir=str(target.artifacts_dir),
            )
            write_recovery(target, "declined", f"auto-restart {reason}", now=at)
            ledger_mod.delete_doorbells_for(str(target.artifacts_dir))
            _mark_disabled_resurfaced(target, at)
            resurfaced += 1
    for doorbell in work.doorbells:
        raw = doorbell.get("artifacts_dir")
        if raw and not (Path(str(raw)) / "done.json").is_file():
            with contextlib.suppress(Exception):
                ledger_mod.delete_doorbell(str(doorbell.get("doorbell_path", "")))
    return resurfaced


def run_job_tick(*, now: float | None = None) -> _TickResult:
    """Run one scheduler tick: settle, resurface, or submit the healer."""
    from sase.agent.auto_restart import storm as storm_mod
    from sase.agent.auto_restart.gate import auto_restart_automatic_enabled

    at = time.time() if now is None else now
    settled = 0
    with contextlib.suppress(Exception):
        settled = _settle_launched_records(now=at)
    try:
        enabled = bool(auto_restart_automatic_enabled())
    except Exception:
        enabled = False
    try:
        paused, _ = storm_mod.is_paused()
    except Exception:
        paused = False
    work = _collect_job_work(now=at)
    if not enabled:
        resurfaced = 0
        with contextlib.suppress(Exception):
            resurfaced = _resurface_for_disabled(work, reason="is disabled", now=at)
        return _TickResult(
            action="disabled", reason="disabled", settled=settled, resurfaced=resurfaced
        )
    if paused:
        resurfaced = 0
        with contextlib.suppress(Exception):
            resurfaced = _resurface_for_disabled(work, reason="is paused", now=at)
        return _TickResult(
            action="paused", reason="paused", settled=settled, resurfaced=resurfaced
        )
    for target in work.stale_pending:
        with contextlib.suppress(Exception):
            from sase.agent.auto_restart.notify import resurface_failure

            resurface_failure(
                agent_name=target.agent_name,
                reason_text=("auto-restart never ran — is the sase scheduler running?"),
                artifacts_dir=str(target.artifacts_dir),
            )
            _mark_resurfaced(target, at)
    if not work.actionable:
        return _TickResult(
            action="idle",
            reason="nothing_eligible" if work.full_scan else "no_signal",
            settled=settled,
            resurfaced=len(work.stale_pending),
        )
    count = len(work.new_targets) or len(work.doorbells) or 1
    with contextlib.suppress(Exception):
        if _proc_already_queued():
            return _TickResult(
                action="queued",
                reason="healer_proc_active",
                targets=count,
                settled=settled,
                resurfaced=len(work.stale_pending),
            )
    if _submit_healer_proc(count=count):
        return _TickResult(
            action="submitted",
            reason="healer_proc_submitted",
            targets=count,
            settled=settled,
            resurfaced=len(work.stale_pending),
        )
    return _TickResult(
        action="submit_failed",
        reason="healer_proc_submit_failed",
        targets=count,
        settled=settled,
        resurfaced=len(work.stale_pending),
    )


__all__ = [
    "CONCURRENCY_KEY",
    "FULL_SWEEP_INTERVAL_SECONDS",
    "HEALER_ARGV",
    "HEALER_PROC_TIMEOUT_SECONDS",
    "run_job_tick",
]
