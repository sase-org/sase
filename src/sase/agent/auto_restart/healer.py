"""The update-skew healer: claim, verify, and relaunch once per lineage.

``sase agent auto-restart run`` executes these steps in order:

1. Claim the ledger, or exit if another claim is live.
2. Gather inputs and witnesses.
3. Classify.
4. Run the quiescence gate and the probe; on failure, mark ``deferred``.
5. Apply the skip rules.
6. Apply the storm breaker.
7. Write evidence.
8. Plan the restart.
9. Guard the wipe scope.
10. Execute.
11. Record the outcome.
12. Notify.

The claim is recorded before any mutation, and any uncertainty resolves to
"attempt spent, notify". A second pass never launches twice: a dead
``launching`` claim is adopted when the replacement exists, else settled
as failed and re-surfaced.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class HealerTarget:
    """One failure the healer should attempt."""

    artifacts_dir: Path
    project: str
    agent_name: str
    died_at: float | None = None


@dataclass(frozen=True)
class HealerOutcome:
    """What one healer pass did with one target."""

    action: str
    reason: str
    reason_text: str
    ledger_key: str | None = None
    launched_artifacts_dir: str | None = None
    evidence_dir: str | None = None


@dataclass(frozen=True)
class SkipDecision:
    """One skip-rule evaluation."""

    skip: bool
    decline_reason: str = ""
    reason_text: str = ""
    loud: bool = True


def resolve_targets(
    *,
    name: str | None = None,
    artifacts_dir: str | None = None,
    pending: bool = False,
) -> list[HealerTarget]:
    """Resolve CLI target selection into concrete healer targets."""
    if pending:
        return resolve_pending_targets()
    if artifacts_dir is not None:
        return [_target_for_artifacts_dir(Path(artifacts_dir))]
    if name is not None:
        from sase.agent.names._lookup_named import find_named_agent

        agent = find_named_agent(name)
        if agent is None:
            raise LookupError(f"No agent found with name '{name}'.")
        return [_target_for_artifacts_dir(Path(agent.artifacts_dir))]
    raise ValueError("one of NAME, --artifacts-dir, or --pending is required")


def _target_for_artifacts_dir(artifacts_dir: Path) -> HealerTarget:
    from sase.agent.auto_restart.history import project_for_done

    done = _read_json(artifacts_dir / "done.json") or {}
    meta = _read_json(artifacts_dir / "agent_meta.json") or {}
    project = project_for_done(done, artifacts_dir)
    name = str(meta.get("name") or meta.get("workflow_name") or artifacts_dir.name)
    return HealerTarget(artifacts_dir=artifacts_dir, project=project, agent_name=name)


def resolve_pending_targets() -> list[HealerTarget]:
    """Enumerate doorbells plus recent failed rows (shared with the job)."""
    from sase.agent.auto_restart.history import collect_failed_candidates
    from sase.agent.auto_restart.ledger import delete_doorbell, list_doorbells

    targets: list[HealerTarget] = []
    seen: set[str] = set()
    for doorbell in list_doorbells():
        raw = doorbell.get("artifacts_dir")
        if not raw:
            continue
        path = Path(str(raw))
        if not (path / "done.json").is_file():
            delete_doorbell(str(doorbell.get("doorbell_path", "")))
            continue
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        try:
            targets.append(_target_for_artifacts_dir(path))
        except Exception:
            continue
    try:
        candidates = collect_failed_candidates(since_seconds=7 * 86400)
    except Exception:
        candidates = []
    for candidate in candidates:
        if candidate.artifacts_dir is None:
            continue
        key = str(candidate.artifacts_dir)
        if key in seen:
            continue
        seen.add(key)
        targets.append(
            HealerTarget(
                artifacts_dir=candidate.artifacts_dir,
                project=candidate.project,
                agent_name=candidate.name,
                died_at=candidate.died_at,
            )
        )
    return _order_targets(targets)


def _order_targets(targets: list[HealerTarget]) -> list[HealerTarget]:
    """Dependencies before dependents, then least progress first.

    Correctness never depends on this order (waiters stay parked on a
    failed dependency); it only makes the sweep read sensibly.
    """

    def depth(target: HealerTarget) -> int:
        meta = _read_json(target.artifacts_dir / "agent_meta.json") or {}
        waits = meta.get("wait_for") or meta.get("depends_on") or []
        if isinstance(waits, (list, tuple)):
            return len(waits)
        return 0

    def progress(target: HealerTarget) -> float:
        try:
            return target.artifacts_dir.stat().st_mtime
        except OSError:
            return 0.0

    return sorted(targets, key=lambda t: (depth(t), progress(t)))


def heal_one(
    target: HealerTarget,
    *,
    dry_run: bool = False,
    classify: Callable | None = None,
    check_quiescence: Callable | None = None,
    run_probe: Callable | None = None,
    plan_restart: Callable | None = None,
    execute_restart: Callable | None = None,
    now: float | None = None,
) -> HealerOutcome:
    """Run one healer pass over one failed agent row."""
    from sase.agent.auto_restart import ledger as ledger_mod
    from sase.core.agent_auto_restart_facade import (
        auto_restart_lineage_root,
        derive_auto_restart_episode,
    )

    at = time.time() if now is None else now
    done = _read_json(target.artifacts_dir / "done.json") or {}
    meta = _read_json(target.artifacts_dir / "agent_meta.json") or {}

    lineage_root = _lineage_root(meta, target, auto_restart_lineage_root)
    key = ledger_mod.ledger_key(target.project, lineage_root)

    stored = ledger_mod.load_ledger_record(key)
    if stored is not None:
        return _recover_existing_claim(
            stored,
            target,
            done=done,
            meta=meta,
            dry_run=dry_run,
            lineage_root=lineage_root,
            now=at,
        )

    if dry_run:
        return HealerOutcome(
            action="dry_run",
            reason="dry_run",
            reason_text="dry run: ledger not claimed, nothing relaunched",
            ledger_key=key,
        )
    stored = ledger_mod.claim_ledger_record(
        key=key,
        lineage_root=lineage_root,
        agent_name=target.agent_name,
        project=target.project,
        failed_artifacts_dir=str(target.artifacts_dir),
    )
    if stored is None:
        return HealerOutcome(
            action="deferred",
            reason="claim_race",
            reason_text="another healer pass claimed this lineage first",
            ledger_key=key,
        )
    if stored.record.state != "claimed" or _claimer_is_other(stored):
        return HealerOutcome(
            action="deferred",
            reason="claim_live",
            reason_text="another live claim owns this lineage",
            ledger_key=key,
        )

    write_recovery(target, "claimed", "healer claimed this lineage", now=at)
    return _heal_claimed(
        stored,
        target,
        done=done,
        meta=meta,
        dry_run=dry_run,
        lineage_root=lineage_root,
        classify=classify,
        check_quiescence=check_quiescence,
        run_probe=run_probe,
        plan_restart=plan_restart,
        execute_restart=execute_restart,
        derive_episode=derive_auto_restart_episode,
        now=at,
    )


def _claimer_is_other(stored: Any) -> bool:
    import os

    pid = stored.extra.get("python_claimer_pid")
    return isinstance(pid, int) and pid != os.getpid()


def _lineage_root(
    meta: Mapping[str, Any], target: HealerTarget, derive: Callable
) -> str:
    auto_restart = meta.get("auto_restart")
    lineage = None
    if isinstance(auto_restart, Mapping):
        lineage = auto_restart.get("lineage_root")
    try:
        return str(
            derive(
                auto_restart_lineage_root=(
                    str(lineage) if lineage is not None else None
                ),
                retry_chain_root_timestamp=_opt_str(
                    meta.get("retry_chain_root_timestamp")
                ),
                artifacts_timestamp=target.artifacts_dir.name,
            )
        )
    except Exception:
        return target.artifacts_dir.name


def _opt_str(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _recover_existing_claim(
    stored: Any,
    target: HealerTarget,
    *,
    done: Mapping[str, Any],
    meta: Mapping[str, Any],
    dry_run: bool,
    lineage_root: str | None = None,
    now: float,
) -> HealerOutcome:
    """Handle a ledger record left by an earlier pass; never launch twice."""
    from sase.agent.auto_restart import ledger as ledger_mod

    state = stored.record.state
    key = stored.record.key
    if state in ("declined", "settled_ok", "settled_failed"):
        return HealerOutcome(
            action="declined",
            reason=stored.record.decline_reason or state,
            reason_text="this lineage already spent its automatic restart",
            ledger_key=key,
        )
    if state == "launched":
        return HealerOutcome(
            action="declined",
            reason="already_launched",
            reason_text="this lineage already relaunched",
            ledger_key=key,
        )
    if state == "launching":
        if ledger_mod.claimer_is_live(stored):
            return HealerOutcome(
                action="deferred",
                reason="launch_in_flight",
                reason_text="another live healer pass is launching this lineage",
                ledger_key=key,
            )
        return _adopt_or_settle(stored, target, dry_run=dry_run, now=now)
    # claimed / deferred with a live claimer: not ours to touch.
    if ledger_mod.claimer_is_live(stored):
        return HealerOutcome(
            action="deferred",
            reason="claim_live",
            reason_text="another live claim owns this lineage",
            ledger_key=key,
        )
    if state == "deferred":
        max_age = _max_defer_seconds()
        claimed_at = _parse_epoch(stored.record.claimed_at)
        if claimed_at is not None and now - claimed_at > max_age:
            if not dry_run:
                stored = ledger_mod.advance_ledger_record(
                    stored, "decline", note="max_defer_seconds elapsed"
                )
                stored = _annotate(stored, decline_reason="deferred_expired")
            write_recovery(target, "declined", "deferred too long", now=now)
            return HealerOutcome(
                action="declined",
                reason="deferred_expired",
                reason_text="deferred too long without settling; not retrying",
                ledger_key=key,
            )
        # Stale deferred with a dead claimer: re-attempt in a fresh pass.
        if not dry_run:
            with contextlib.suppress(Exception):
                ledger_mod.advance_ledger_record(stored, "reclaim")
            stored = ledger_mod.load_ledger_record(key) or stored
        return _heal_claimed(
            stored,
            target,
            done=done,
            meta=meta,
            dry_run=dry_run,
            lineage_root=lineage_root,
            now=now,
        )
    # Stale claimed with a dead claimer: adopt the claim and proceed.
    if not dry_run:
        stored = ledger_mod.store_ledger_record(stored)
    return _heal_claimed(
        stored,
        target,
        done=done,
        meta=meta,
        dry_run=dry_run,
        lineage_root=lineage_root,
        now=now,
    )


def _adopt_or_settle(
    stored: Any, target: HealerTarget, *, dry_run: bool, now: float
) -> HealerOutcome:
    """A dead ``launching`` claim adopts the replacement or settles failed."""
    from sase.agent.auto_restart import ledger as ledger_mod

    key = stored.record.key
    planned = stored.record.planned_name
    claimed_at = _parse_epoch(stored.record.claimed_at) or 0.0
    replacement = _find_replacement_dir(planned, since=claimed_at) if planned else None
    if dry_run:
        return HealerOutcome(
            action="dry_run",
            reason="launching_unresolved",
            reason_text="dry run: launching claim left unresolved",
            ledger_key=key,
        )
    if replacement is not None:
        stored = ledger_mod.advance_ledger_record(
            stored,
            "launched",
            note=f"adopted replacement {replacement}",
        )
        stored = _annotate(stored, launched_artifacts_dir=replacement)
        write_recovery(target, "launched", "adopted replacement", now=now)
        return HealerOutcome(
            action="relaunched",
            reason="adopted",
            reason_text=f"adopted replacement {replacement}",
            ledger_key=key,
            launched_artifacts_dir=replacement,
        )
    stored = ledger_mod.advance_ledger_record(
        stored, "settled_failed", note="claimer died before launch"
    )
    stored = _annotate(stored, decline_reason="launch_aborted")
    write_recovery(target, "declined", "claimer died before launch", now=now)
    _resurface(target, "the restart attempt died before relaunching")
    return HealerOutcome(
        action="declined",
        reason="launch_aborted",
        reason_text="the restart attempt died before relaunching; not retrying",
        ledger_key=key,
    )


def _find_replacement_dir(planned_name: str, *, since: float) -> str | None:
    try:
        from sase.agent.names._lookup_named import find_named_agent
    except Exception:
        return None
    try:
        agent = find_named_agent(planned_name)
    except Exception:
        return None
    if agent is None:
        return None
    artifacts = Path(str(agent.artifacts_dir))
    try:
        if artifacts.stat().st_mtime < since:
            return None
    except OSError:
        return None
    return str(artifacts)


def _annotate(
    stored: Any,
    *,
    decline_reason: str | None = None,
    launched_artifacts_dir: str | None = None,
    evidence_dir: str | None = None,
    episode_id: str | None = None,
    planned_name: str | None = None,
) -> Any:
    """Persist annotation-only wire fields without a state transition."""
    import dataclasses

    from sase.agent.auto_restart import ledger as ledger_mod

    record = stored.record
    changes: dict[str, Any] = {}
    if decline_reason is not None:
        changes["decline_reason"] = decline_reason
    if launched_artifacts_dir is not None:
        changes["launched_artifacts_dir"] = launched_artifacts_dir
    if evidence_dir is not None:
        changes["evidence_dir"] = evidence_dir
    if episode_id is not None:
        changes["episode_id"] = episode_id
    if planned_name is not None:
        changes["planned_name"] = planned_name
    if not changes:
        return stored
    return ledger_mod.store_ledger_record(
        ledger_mod.StoredLedgerRecord(
            record=dataclasses.replace(record, **changes), extra=dict(stored.extra)
        )
    )


def _heal_claimed(
    stored: Any,
    target: HealerTarget,
    *,
    done: Mapping[str, Any],
    meta: Mapping[str, Any],
    dry_run: bool,
    lineage_root: str | None = None,
    classify: Callable | None = None,
    check_quiescence: Callable | None = None,
    run_probe: Callable | None = None,
    plan_restart: Callable | None = None,
    execute_restart: Callable | None = None,
    derive_episode: Callable | None = None,
    now: float,
) -> HealerOutcome:
    from sase.agent.auto_restart import ledger as ledger_mod

    key = stored.record.key
    skip = apply_skip_rules(target, done=done, meta=meta)
    if skip.skip:
        if not dry_run:
            stored = ledger_mod.advance_ledger_record(
                stored, "decline", note=skip.decline_reason
            )
            stored = _annotate(stored, decline_reason=skip.decline_reason)
            write_recovery(target, "declined", skip.reason_text, now=now)
            if skip.loud:
                kind = (
                    "already_restarted"
                    if skip.decline_reason == "already_restarted"
                    else "decline"
                )
                _escalate(
                    target,
                    skip.reason_text,
                    episode_id=stored.record.episode_id,
                    kind=kind,
                )
            else:
                _resurface(target, skip.reason_text)
        return HealerOutcome(
            action="declined",
            reason=skip.decline_reason,
            reason_text=skip.reason_text,
            ledger_key=key,
        )

    try:
        assembled = _assemble(target, done=done, meta=meta)
    except Exception as exc:
        return _defer(stored, target, f"could not assemble inputs: {exc}", now=now)
    verdict = (classify or _classify_default)(assembled)
    _store_verdict(stored, verdict, assembled, dry_run=dry_run)
    if verdict.mode == "decline":
        return _decline(
            stored,
            target,
            verdict.reason or "declined",
            verdict.reason_text or "not an update-skew failure",
            now=now,
            dry_run=dry_run,
        )
    if verdict.mode in ("notify_post_provider", "ask"):
        return _decline(
            stored,
            target,
            verdict.reason or verdict.mode,
            verdict.reason_text or "not relaunched by policy",
            now=now,
            dry_run=dry_run,
            escalate=True,
            escalate_kind=(
                "post_provider" if verdict.mode == "notify_post_provider" else "decline"
            ),
        )
    if verdict.mode != "relaunch" and verdict.mode != "defer":
        return _decline(
            stored,
            target,
            verdict.reason or "declined",
            verdict.reason_text or "classifier declined",
            now=now,
            dry_run=dry_run,
        )

    episode_id = verdict.episode_id
    if episode_id is None and derive_episode is not None:
        try:
            episode_id = derive_episode(assembled.witnesses).id or None
        except Exception:
            episode_id = None
    if episode_id is not None and not dry_run:
        stored = _annotate(stored, episode_id=episode_id)

    quiescence = (check_quiescence or _quiescence_default)()
    probe_ok, probe_failures = _probe_for_verdict(
        verdict, assembled, run_probe=run_probe
    )
    if verdict.mode == "defer" or not quiescence.ok or not probe_ok:
        detail = "; ".join(
            part
            for part in [
                "classifier deferred" if verdict.mode == "defer" else "",
                quiescence.reason if not quiescence.ok else "",
                (
                    f"probe failed: {'; '.join(probe_failures)[:300]}"
                    if not probe_ok
                    else ""
                ),
            ]
            if part
        )
        return _defer(stored, target, detail or "deferred", now=now)

    storm = _storm_decision(episode_id)
    if not storm.allowed:
        from sase.agent.auto_restart import storm as storm_mod

        if not dry_run:
            storm_mod.trip_pause(reason=storm.reason, episode=episode_id)
            _escalate(target, storm.reason, episode_id=episode_id, kind="storm")
        return _decline(
            stored, target, "paused", storm.reason, now=now, dry_run=dry_run
        )

    if dry_run:
        return HealerOutcome(
            action="dry_run",
            reason="would_relaunch",
            reason_text="dry run: pre-provider skew verified; nothing relaunched",
            ledger_key=key,
        )
    return _relaunch(
        stored,
        target,
        done=done,
        meta=meta,
        verdict=verdict,
        assembled=assembled,
        episode_id=episode_id,
        lineage_root=lineage_root or stored.record.lineage_root,
        plan_restart=plan_restart,
        execute_restart=execute_restart,
        now=now,
    )


def apply_skip_rules(
    target: HealerTarget,
    *,
    done: Mapping[str, Any],
    meta: Mapping[str, Any],
) -> SkipDecision:
    """Apply the user-intent skip rules against fresh state (re-validated)."""
    if meta.get("auto_restart") is not None:
        return SkipDecision(
            skip=True,
            decline_reason="already_restarted",
            reason_text="auto-restart skipped — already restarted once",
        )
    if _is_remote_done(done, meta):
        return SkipDecision(
            skip=True,
            decline_reason="remote",
            reason_text="auto-restart skipped — remote agent",
            loud=False,
        )
    if _outcome_is_killed(done):
        return SkipDecision(
            skip=True,
            decline_reason="killed",
            reason_text="auto-restart skipped — agent was killed or stopped",
            loud=False,
        )
    if str(done.get("outcome", "")) != "failed":
        return SkipDecision(
            skip=True,
            decline_reason="no_longer_failed",
            reason_text="auto-restart skipped — row is no longer failed",
            loud=False,
        )
    if _find_moved_on(target, meta):
        return SkipDecision(
            skip=True,
            decline_reason="manual_relaunch",
            reason_text="auto-restart skipped — already relaunched by hand",
            loud=False,
        )
    if _has_pending_marker(target, meta):
        return SkipDecision(
            skip=True,
            decline_reason="needs_user_decision",
            reason_text="not restarted — holding a question, plan, or gate marker",
        )
    return SkipDecision(skip=False)


def _is_remote_done(done: Mapping[str, Any], meta: Mapping[str, Any]) -> bool:
    for mapping in (done, meta):
        value = mapping.get("is_remote") if isinstance(mapping, Mapping) else None
        if value is True:
            return True
    return False


def _outcome_is_killed(done: Mapping[str, Any]) -> bool:
    outcome = str(done.get("outcome", ""))
    if outcome in ("killed", "stopped", "cancelled", "canceled"):
        return True
    kill_source = str(done.get("kill_source") or "")
    return bool(kill_source) and outcome != "failed"


def _find_moved_on(target: HealerTarget, meta: Mapping[str, Any]) -> bool:
    """Return whether the user already handled this failure by hand.

    True when the name now resolves to a different artifacts dir (a manual
    ``,x`` or relaunch won the race), or when the name is gone from the
    index *and* the failed row itself is gone (dismissed or wiped). A
    missing index entry with the failed row still on disk is a stale
    index, not user intent: the ledger still guards at-most-once.
    """
    try:
        from sase.agent.names._lookup_named import find_named_agent
    except Exception:
        return False
    name = str(meta.get("name") or meta.get("workflow_name") or "")
    if not name:
        return False
    try:
        agent = find_named_agent(name)
    except Exception:
        return False
    if agent is None:
        return not (target.artifacts_dir / "done.json").is_file()
    try:
        current = str(Path(str(agent.artifacts_dir)).resolve())
        wanted = str(target.artifacts_dir.resolve())
    except OSError:
        return False
    return current != wanted


def _has_pending_marker(target: HealerTarget, meta: Mapping[str, Any]) -> bool:
    try:
        from sase.agent.auto_restart.inputs import pending_handoff
        from sase.agent.auto_restart.inputs import pending_question
    except Exception:
        return False
    try:
        if bool(pending_question(target.artifacts_dir, meta)):
            return True
    except Exception:
        pass
    try:
        if bool(pending_handoff(target.artifacts_dir)):
            return True
    except Exception:
        pass
    return False


def _assemble(target: HealerTarget, *, done: Mapping, meta: Mapping) -> Any:
    from sase.agent.auto_restart.history import candidate_log_tail
    from sase.agent.auto_restart.inputs import assemble_done_row_input
    from sase.agent.auto_restart.managed_roots import collect_managed_roots

    log_tail = ""
    try:
        from sase.agent.auto_restart.history import FailedCandidate

        candidate = FailedCandidate(
            source="done",
            name=target.agent_name,
            project=target.project,
            died_at=target.died_at,
            mtime=None,
            artifacts_dir=target.artifacts_dir,
            done=dict(done),
            meta=dict(meta),
            bundle=None,
            log_path=None,
        )
        log_tail = candidate_log_tail(candidate)
    except Exception:
        log_tail = ""
    return assemble_done_row_input(
        artifacts_dir=target.artifacts_dir,
        done=done,
        meta=meta,
        managed_roots=collect_managed_roots(),
        project=target.project,
        died_at=target.died_at,
        log_tail=log_tail,
    )


def _classify_default(assembled: Any) -> Any:
    from sase.core.agent_auto_restart_facade import classify_agent_failure

    return classify_agent_failure(
        assembled.context, assembled.witnesses, assembled.facts
    )


def _quiescence_default() -> Any:
    from sase.agent.auto_restart.quiescence import check_quiescence
    from sase.config._settings_system import (
        get_agent_auto_restart_quiescence_seconds,
    )

    return check_quiescence(
        quiescence_seconds=get_agent_auto_restart_quiescence_seconds()
    )


def _probe_for_verdict(
    verdict: Any, assembled: Any, *, run_probe: Callable | None
) -> tuple[bool, tuple[str, ...]]:
    from sase.agent.auto_restart.probe import (
        probe_modules_for_frames,
        run_probe as _run,
    )

    probe_wire = getattr(assembled.witnesses, "probe", None)
    if probe_wire is not None and getattr(probe_wire, "ok", False):
        return True, ()
    modules = probe_modules_for_frames(
        list(getattr(assembled.facts, "frames", None) or []),
        target_module=getattr(verdict, "origin_module", None),
    )
    binding_checks: list[tuple[str, str]] = []
    missing = getattr(verdict, "missing_symbol", None)
    origin = getattr(verdict, "origin_module", None)
    if origin == "sase_core_rs" and missing:
        binding_checks.append(("sase_core_rs", missing))
    result = (run_probe or _run)(modules, binding_checks=binding_checks)
    return bool(result.ok), tuple(result.failures)


def _storm_decision(episode_id: str | None) -> Any:
    from sase.agent.auto_restart import ledger as ledger_mod
    from sase.agent.auto_restart import storm as storm_mod
    from sase.config._settings_system import (
        get_agent_auto_restart_storm_max_per_30m,
        get_agent_auto_restart_storm_max_per_episode,
    )

    paused, _ = storm_mod.is_paused()
    if paused:
        from sase.agent.auto_restart.storm import StormDecision

        return StormDecision(allowed=False, reason="auto-restart is paused")
    return storm_mod.storm_check(
        ledger_mod.iter_ledger_records(),
        episode_id=episode_id,
        max_per_episode=get_agent_auto_restart_storm_max_per_episode(),
        max_per_30m=get_agent_auto_restart_storm_max_per_30m(),
    )


def _relaunch(
    stored: Any,
    target: HealerTarget,
    *,
    done: Mapping[str, Any],
    meta: Mapping[str, Any],
    verdict: Any,
    assembled: Any,
    episode_id: str | None,
    lineage_root: str,
    plan_restart: Callable | None,
    execute_restart: Callable | None,
    now: float,
) -> HealerOutcome:
    from sase.agent.auto_restart import ledger as ledger_mod

    key = stored.record.key
    # Re-validate skip rules against fresh state immediately before mutating.
    fresh_done = _read_json(target.artifacts_dir / "done.json") or {}
    fresh_meta = _read_json(target.artifacts_dir / "agent_meta.json") or {}
    skip = apply_skip_rules(target, done=fresh_done, meta=fresh_meta)
    if skip.skip:
        stored = ledger_mod.advance_ledger_record(
            stored, "decline", note=skip.decline_reason
        )
        stored = _annotate(stored, decline_reason=skip.decline_reason)
        write_recovery(target, "declined", skip.reason_text, now=now)
        return HealerOutcome(
            action="declined",
            reason=skip.decline_reason,
            reason_text=skip.reason_text,
            ledger_key=key,
        )
    try:
        plan = (plan_restart or _plan_default)(
            target.agent_name, follow_live_autonomy=True
        )
    except Exception as exc:
        return _defer(stored, target, f"restart planning refused: {exc}", now=now)
    if _wipe_reaches_others(plan, target):
        stored = ledger_mod.advance_ledger_record(
            stored, "decline", note="wipe_reaches_others"
        )
        stored = _annotate(stored, decline_reason="wipe_reaches_others")
        write_recovery(target, "declined", "wipe reaches other agents", now=now)
        return HealerOutcome(
            action="declined",
            reason="wipe_reaches_others",
            reason_text="not restarted — the name wipe would reach other agents",
            ledger_key=key,
        )
    stored = ledger_mod.advance_ledger_record(
        stored,
        "begin_launch",
        note=f"launching {target.agent_name}",
        extra={"python_plan_digest": _plan_digest(plan)},
    )
    stored = _annotate(stored, planned_name=target.agent_name)
    write_recovery(target, "launching", "relaunching", now=now)
    evidence_dir, evidence_files = _write_evidence(
        target, verdict=verdict, assembled=assembled, episode_id=episode_id
    )
    if evidence_dir is not None:
        stored = _annotate(stored, evidence_dir=evidence_dir)
    _attach_provenance(
        plan,
        target,
        verdict=verdict,
        episode_id=episode_id,
        lineage_root=lineage_root,
        ledger_key=key,
        evidence_dir=evidence_dir,
    )
    outcome = (execute_restart or _execute_default)(plan, evidence_files)
    if outcome is None or getattr(outcome, "status", "") != "ok":
        error = getattr(outcome, "error", None) or "execute failed"
        stored = ledger_mod.advance_ledger_record(
            stored, "settled_failed", note=str(error)[:200]
        )
        stored = _annotate(stored, decline_reason="execute_failed")
        write_recovery(target, "declined", str(error)[:300], now=now)
        _resurface(target, str(error)[:300])
        return HealerOutcome(
            action="declined",
            reason="execute_failed",
            reason_text=str(error)[:300],
            ledger_key=key,
            evidence_dir=evidence_dir,
        )
    launched_dir = getattr(outcome, "launched_artifacts_dir", None)
    stored = ledger_mod.advance_ledger_record(stored, "launched")
    stored = _annotate(stored, launched_artifacts_dir=launched_dir)
    write_recovery(target, "launched", "relaunched", now=now)
    _publish_relaunch(
        target, verdict=verdict, episode_id=episode_id, evidence_dir=evidence_dir
    )
    return HealerOutcome(
        action="relaunched",
        reason="relaunch",
        reason_text=f"relaunched {target.agent_name} under the same name",
        ledger_key=key,
        launched_artifacts_dir=launched_dir,
        evidence_dir=evidence_dir,
    )


def _plan_default(name: str, *, follow_live_autonomy: bool) -> Any:
    from sase.agent._restart_planning import plan_agent_restart

    return plan_agent_restart(name, follow_live_autonomy=follow_live_autonomy)


def _execute_default(plan: Any, evidence_files: dict[str, Any]) -> Any:
    import contextlib
    from pathlib import Path as _Path

    from sase.agent._restart_execute import execute_agent_restart

    with contextlib.chdir(_Path.home()):
        return execute_agent_restart(plan, extra_evidence=evidence_files)


def _plan_digest(plan: Any) -> str:
    try:
        prompt = plan.rewritten_prompt
    except AttributeError:
        prompt = repr(plan)
    return hashlib.sha256(str(prompt).encode("utf-8")).hexdigest()[:16]


def _wipe_reaches_others(plan: Any, target: HealerTarget) -> bool:
    try:
        from sase.agent._restart_preview import restart_needs_confirmation
    except Exception:
        return True
    try:
        if not restart_needs_confirmation(plan):
            return False
    except Exception:
        return True
    # A declined wipe is only safe when everything it reaches is our own row.
    try:
        wipe_dirs = plan.wipe_preview.artifact_dirs
    except AttributeError:
        return True
    own = _resolved(target.artifacts_dir)
    for raw in wipe_dirs or ():
        if _resolved(Path(str(raw))) != own:
            return True
    return False


def _resolved(path: Path) -> str:
    try:
        return str(path.resolve())
    except OSError:
        return str(path)


def _attach_provenance(
    plan: Any,
    target: HealerTarget,
    *,
    verdict: Any,
    episode_id: str | None,
    lineage_root: str,
    ledger_key: str,
    evidence_dir: str | None,
) -> None:
    import datetime

    from sase.agent.auto_restart.provenance import (
        PROVENANCE_ENV,
        provenance_segment_env,
    )
    from sase.core.time import get_timezone

    provenance = {
        "of_artifacts_dir": str(target.artifacts_dir),
        "of_timestamp": target.artifacts_dir.name,
        "lineage_root": lineage_root,
        "episode_id": episode_id,
        "ledger_key": ledger_key,
        "evidence_dir": evidence_dir,
        "signature": getattr(verdict, "signature", None),
        "from_rev": None,
        "to_rev": None,
        "culprit_commit": None,
        "culprit_subject": None,
        "restarted_at": datetime.datetime.now(get_timezone()).isoformat(),
    }
    file_proof = getattr(getattr(verdict, "witnesses", None), "file_proof", None)
    if file_proof is not None:
        provenance["culprit_commit"] = getattr(file_proof, "culprit_commit", None)
        provenance["culprit_subject"] = getattr(file_proof, "culprit_subject", None)
    env = provenance_segment_env(provenance)
    try:
        segment_envs = plan.force_reuse_plan.segment_envs
        for index, overlay in enumerate(segment_envs):
            merged = dict(overlay or {})
            merged.setdefault(PROVENANCE_ENV, env[PROVENANCE_ENV])
            segment_envs[index] = merged
    except AttributeError:
        pass


def _write_evidence(
    target: HealerTarget, *, verdict: Any, assembled: Any, episode_id: str | None
) -> tuple[str | None, dict[str, Any]]:
    """Preserve evidence before the wipe; return the dir and bundle files.

    The same payload lands in two places: the ledger evidence directory
    (outside any artifacts dir, so the forced-reuse wipe cannot remove it)
    and the restart recovery bundle (via ``execute_agent_restart``'s
    ``extra_evidence``).
    """
    import datetime

    from sase.agent.auto_restart import ledger as ledger_mod
    from sase.core.agent_auto_restart_wire import (
        auto_restart_witnesses_to_dict,
        recovery_verdict_to_dict,
    )
    from sase.core.time import get_timezone

    try:
        verdict_dict: dict[str, Any] = recovery_verdict_to_dict(verdict)
    except Exception:
        verdict_dict = {"signature": getattr(verdict, "signature", None)}
    try:
        witnesses_dict: dict[str, Any] = auto_restart_witnesses_to_dict(
            assembled.witnesses
        )
    except Exception:
        witnesses_dict = {}
    facts_dict: dict[str, Any] = dict(getattr(assembled.facts, "__dict__", {}) or {})
    done_dict = _read_json(target.artifacts_dir / "done.json") or {}
    tail = _runner_log_tail(target)
    report_text: str | None = None
    try:
        report = target.artifacts_dir / "error_report.md"
        if report.is_file():
            report_text = report.read_text(encoding="utf-8")
    except OSError:
        report_text = None
    bundle: dict[str, Any] = {
        "done.json": done_dict,
        "failure_facts.json": facts_dict,
        "verdict.json": verdict_dict,
        "witnesses.json": witnesses_dict,
    }
    if episode_id is not None:
        bundle["episode_id.txt"] = episode_id
    if tail:
        bundle["runner_log_tail.txt"] = tail
    if report_text is not None:
        bundle["error_report.md"] = report_text
    stamp = datetime.datetime.now(get_timezone()).strftime("%Y%m%d%H%M%S")
    dest = ledger_mod.auto_restart_root() / "evidence" / f"{stamp}-{target.agent_name}"
    try:
        dest.mkdir(parents=True, exist_ok=True)
        for name, value in bundle.items():
            target_path = dest / Path(name).name
            if isinstance(value, str):
                target_path.write_text(value, encoding="utf-8")
            else:
                target_path.write_text(
                    json.dumps(value, indent=2, default=str) + "\n",
                    encoding="utf-8",
                )
    except OSError:
        return None, bundle
    return str(dest), bundle


def _runner_log_tail(target: HealerTarget) -> str:
    try:
        from sase.agent.auto_restart.history import FailedCandidate
        from sase.agent.auto_restart.history import candidate_log_tail

        candidate = FailedCandidate(
            source="done",
            name=target.agent_name,
            project=target.project,
            died_at=target.died_at,
            mtime=None,
            artifacts_dir=target.artifacts_dir,
            done=_read_json(target.artifacts_dir / "done.json") or {},
            meta=_read_json(target.artifacts_dir / "agent_meta.json") or {},
            bundle=None,
            log_path=None,
        )
        return candidate_log_tail(candidate)
    except Exception:
        return ""


def _store_verdict(stored: Any, verdict: Any, assembled: Any, *, dry_run: bool) -> None:
    if dry_run:
        return
    from sase.agent.auto_restart import ledger as ledger_mod
    from sase.core.agent_auto_restart_wire import (
        auto_restart_witnesses_to_dict,
        recovery_verdict_to_dict,
    )

    try:
        verdict_dict = recovery_verdict_to_dict(verdict)
    except Exception:
        verdict_dict = {"signature": getattr(verdict, "signature", None)}
    try:
        witnesses_dict = auto_restart_witnesses_to_dict(assembled.witnesses)
    except Exception:
        witnesses_dict = {}
    with contextlib.suppress(Exception):
        ledger_mod.store_ledger_record(
            stored,
            extra={
                "python_verdict": verdict_dict,
                "python_witnesses": witnesses_dict,
            },
        )


def _defer(
    stored: Any, target: HealerTarget, detail: str, *, now: float
) -> HealerOutcome:
    from sase.agent.auto_restart import ledger as ledger_mod

    stored = ledger_mod.advance_ledger_record(stored, "defer", note=detail)
    write_recovery(target, "deferred", detail, now=now)
    return HealerOutcome(
        action="deferred",
        reason="deferred",
        reason_text=detail,
        ledger_key=stored.record.key,
    )


def _decline(
    stored: Any,
    target: HealerTarget,
    reason: str,
    reason_text: str,
    *,
    now: float,
    dry_run: bool,
    escalate: bool = False,
    episode_id: str | None = None,
    escalate_kind: str = "decline",
) -> HealerOutcome:
    from sase.agent.auto_restart import ledger as ledger_mod

    if not dry_run:
        stored = ledger_mod.advance_ledger_record(stored, "decline", note=reason)
        stored = _annotate(stored, decline_reason=reason)
        write_recovery(target, "declined", reason_text, now=now)
        if escalate:
            _escalate(target, reason_text, episode_id=episode_id, kind=escalate_kind)
        else:
            _resurface(target, reason_text)
    return HealerOutcome(
        action="declined",
        reason=reason,
        reason_text=reason_text,
        ledger_key=stored.record.key,
    )


def _max_defer_seconds() -> float:
    try:
        from sase.config._settings_system import (
            get_agent_auto_restart_max_defer_seconds,
        )

        return get_agent_auto_restart_max_defer_seconds()
    except Exception:
        return 1800.0


def _parse_epoch(value: Any) -> float | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        from datetime import datetime

        return datetime.fromisoformat(value).timestamp()
    except (ValueError, TypeError):
        return None


def _escalate(
    target: HealerTarget,
    reason_text: str,
    *,
    episode_id: str | None,
    kind: str = "decline",
) -> None:
    """Escalate one declined restart with the per-situation loud copy."""
    from sase.agent.auto_restart.notify import publish_escalation

    if kind == "storm":
        title = f"Auto-restart paused: {reason_text[:200]}"
        detail = (
            f"Episode {episode_id or 'unknown'}. Triage the failures, then run "
            "`sase agent auto-restart resume` to re-arm."
        )
    elif kind == "post_provider":
        title = (
            f"{target.agent_name} broke after its model turn during a sase "
            "update — workspace held with its changes. "
            "Review, then ,x to relaunch."
        )
        detail = reason_text
    elif kind == "already_restarted":
        episode = f" after sase update {episode_id}" if episode_id else ""
        title = (
            f"This was its automatic restart{episode} — not retrying. "
            f"Press ,x on {target.agent_name} to retry by hand."
        )
        detail = reason_text
    else:
        title = (
            f"Couldn't restart {target.agent_name} automatically — {reason_text[:160]}"
        )
        detail = (
            f"{target.agent_name} broke during a sase update but was left alone: "
            f"{reason_text} Press ,x on it to retry by hand."
        )
    with contextlib.suppress(Exception):
        publish_escalation(
            agent_name=target.agent_name,
            title=title,
            detail=detail,
            episode_id=episode_id,
            kind=kind if kind == "storm" else "decline",
            artifacts_dir=str(target.artifacts_dir),
        )


def _resurface(target: HealerTarget, reason_text: str) -> None:
    from sase.agent.auto_restart.notify import resurface_failure

    with contextlib.suppress(Exception):
        resurface_failure(
            agent_name=target.agent_name,
            reason_text=reason_text,
            artifacts_dir=str(target.artifacts_dir),
        )


def _publish_relaunch(
    target: HealerTarget,
    *,
    verdict: Any,
    episode_id: str | None,
    evidence_dir: str | None,
) -> None:
    from sase.agent.auto_restart.notify import publish_relaunch

    files = [evidence_dir] if evidence_dir else []
    with contextlib.suppress(Exception):
        publish_relaunch(
            episode_id=episode_id or "unknown",
            agent_name=target.agent_name,
            update_ref=episode_id or "unknown",
            reason_text=getattr(verdict, "reason_text", "") or "",
            evidence_files=files,
        )


def write_recovery(
    target: HealerTarget, state: str, note: str, *, now: float | None = None
) -> None:
    """Write the ``recovery`` object on the failed row's ``done.json``."""
    import datetime

    from sase.core.time import get_timezone

    at = time.time() if now is None else now
    path = target.artifacts_dir / "done.json"
    done = _read_json(path) or {}
    try:
        previous = done.get("recovery")
        episode_id = previous.get("episode_id") if isinstance(previous, dict) else None
    except AttributeError:
        episode_id = None
    done["recovery"] = {
        "state": state,
        "reason": note[:200] if state == "declined" else None,
        "reason_text": note,
        "requested_at": (
            previous.get("requested_at")
            if isinstance(previous, dict) and previous.get("requested_at")
            else datetime.datetime.fromtimestamp(at, tz=get_timezone()).isoformat()
        ),
        "updated_at": datetime.datetime.fromtimestamp(
            at, tz=get_timezone()
        ).isoformat(),
        "episode_id": episode_id,
    }
    try:
        from sase.notification_gates.durability import atomic_write_json

        atomic_write_json(path, done)
    except OSError:
        return
    with contextlib.suppress(Exception):
        from sase.core.agent_artifact_index_lifecycle_mutations import (
            update_agent_artifact_index_for_marker_mutation,
        )

        update_agent_artifact_index_for_marker_mutation(target.artifacts_dir)


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, NotADirectoryError, OSError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


__all__ = [
    "HealerOutcome",
    "HealerTarget",
    "SkipDecision",
    "apply_skip_rules",
    "heal_one",
    "resolve_pending_targets",
    "resolve_targets",
    "write_recovery",
]
