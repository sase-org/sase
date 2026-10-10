"""Healer ledger claim: claim, adopt, or settle before any mutation."""

from __future__ import annotations

import contextlib
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from sase.agent.auto_restart._healer_common import (
    HealerOutcome,
    HealerTarget,
    annotate_record,
    read_json,
    resurface_healer,
    write_recovery,
)
from sase.agent.auto_restart.healer_flow import heal_claimed


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
    done = read_json(target.artifacts_dir / "done.json") or {}
    meta = read_json(target.artifacts_dir / "agent_meta.json") or {}

    lineage_root = _lineage_root(meta, target, auto_restart_lineage_root)
    key = ledger_mod.ledger_key(target.project, lineage_root)

    auto_restart = meta.get("auto_restart")
    if isinstance(auto_restart, Mapping) and str(done.get("outcome", "")) == "failed":
        recorded_key = _opt_str(auto_restart.get("ledger_key"))
        replacement_record = (
            ledger_mod.load_ledger_record(recorded_key) if recorded_key else None
        )
        if replacement_record is None:
            replacement_record = ledger_mod.load_ledger_record(key)
        return _handle_replacement_failure(
            replacement_record,
            target,
            done=done,
            auto_restart=auto_restart,
            now=at,
            dry_run=dry_run,
        )

    stored = ledger_mod.load_ledger_record(key)
    if stored is not None:
        if str(done.get("outcome", "")) == "failed" and _is_replacement_target(
            target, stored
        ):
            return _handle_replacement_failure(
                stored,
                target,
                done=done,
                auto_restart={},
                now=at,
                dry_run=dry_run,
            )
        return _recover_existing_claim(
            stored,
            target,
            done=done,
            meta=meta,
            dry_run=dry_run,
            lineage_root=lineage_root,
            now=at,
        )

    # Fresh lineage: re-check the candidate rule before claiming anything.
    # Non-candidates return with no ledger record, no done.json write, and
    # no notification.
    from sase.agent.auto_restart.healer_targets import (
        is_healer_candidate,
        target_was_silenced,
    )

    try:
        doorbell_dirs = {
            str(entry.get("artifacts_dir"))
            for entry in ledger_mod.list_doorbells()
            if entry.get("artifacts_dir")
        }
    except Exception:
        doorbell_dirs = set()
    has_doorbell = str(target.artifacts_dir) in doorbell_dirs
    try:
        candidate = is_healer_candidate(
            artifacts_dir=target.artifacts_dir,
            done=done,
            has_doorbell=has_doorbell,
            now=at,
        )
    except Exception:
        candidate = True
    if not candidate:
        if not dry_run:
            with contextlib.suppress(Exception):
                ledger_mod.delete_doorbells_for(str(target.artifacts_dir))
        return HealerOutcome(
            action="skipped",
            reason="not_update_skew",
            reason_text="not an update-skew candidate: no doorbell, in-flight "
            "recovery, skew suspect, or recent skew-shaped legacy row",
            ledger_key=None,
        )
    try:
        silenced: bool | None = target_was_silenced(target, done)
    except Exception:
        silenced = None

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
        at=ledger_mod.timestamp_for(at),
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

    # The ledger owns this failure now: the doorbell is handled, and the
    # runner's ``pending`` stays in place until the pass writes
    # ``deferred``, ``launching``, or ``declined`` (never ``claimed``).
    with contextlib.suppress(Exception):
        ledger_mod.delete_doorbells_for(str(target.artifacts_dir))
    return heal_claimed(
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
        silenced=True if silenced is None else silenced,
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
    if state in ("declined", "settled_ok", "settled_failed", "launched"):
        # Already spent: the doorbell is handled whether or not an earlier
        # pass deleted it, so the job goes idle on the next tick.
        if not dry_run:
            with contextlib.suppress(Exception):
                ledger_mod.delete_doorbells_for(str(target.artifacts_dir))
        if state == "launched":
            return HealerOutcome(
                action="declined",
                reason="already_launched",
                reason_text="this lineage already relaunched",
                ledger_key=key,
            )
        return HealerOutcome(
            action="declined",
            reason=stored.record.decline_reason or state,
            reason_text="this lineage already spent its automatic restart",
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
                    stored,
                    "decline",
                    note="max_defer_seconds elapsed",
                    at=ledger_mod.timestamp_for(now),
                )
                stored = annotate_record(stored, decline_reason="deferred_expired")
            write_recovery(
                target,
                "declined",
                "deferred too long without settling; not retrying",
                now=now,
                dry_run=dry_run,
                ledger_key=key,
                episode_id=stored.record.episode_id,
                decline_reason="deferred_expired",
            )
            if not dry_run:
                from sase.agent.auto_restart._healer_common import escalate_healer

                escalate_healer(
                    target,
                    "deferred too long without settling; not retrying",
                    episode_id=stored.record.episode_id,
                    kind="decline",
                )
            return HealerOutcome(
                action="declined",
                reason="deferred_expired",
                reason_text=(
                    f"Couldn't restart {target.agent_name} automatically — "
                    "deferred too long without settling; not retrying"
                ),
                ledger_key=key,
            )
        # Stale deferred with a dead claimer: re-attempt in a fresh pass.
        if not dry_run:
            stored = ledger_mod.take_over_ledger_claim(
                stored, at=ledger_mod.timestamp_for(now)
            )
        return heal_claimed(
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
        stored = ledger_mod.take_over_ledger_claim(
            stored, at=ledger_mod.timestamp_for(now)
        )
    return heal_claimed(
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
            at=ledger_mod.timestamp_for(now),
        )
        stored = annotate_record(stored, launched_artifacts_dir=replacement)
        write_recovery(
            target,
            "launched",
            "adopted replacement",
            now=now,
            ledger_key=key,
            episode_id=stored.record.episode_id,
        )
        return HealerOutcome(
            action="relaunched",
            reason="adopted",
            reason_text=f"adopted replacement {replacement}",
            ledger_key=key,
            launched_artifacts_dir=replacement,
        )
    stored = ledger_mod.advance_ledger_record(
        stored,
        "settled_failed",
        note="claimer died before launch",
        at=ledger_mod.timestamp_for(now),
    )
    stored = annotate_record(stored, decline_reason="launch_aborted")
    write_recovery(
        target,
        "declined",
        "claimer died before launch",
        now=now,
        ledger_key=key,
        episode_id=stored.record.episode_id,
    )
    resurface_healer(target, "the restart attempt died before relaunching")
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


def _max_defer_seconds() -> float:
    try:
        from sase.config._settings_system import (
            get_agent_auto_restart_max_defer_seconds,
        )

        return get_agent_auto_restart_max_defer_seconds()
    except Exception:
        return 1800.0


def _is_replacement_target(target: HealerTarget, stored: Any) -> bool:
    failed_dir = stored.record.failed_artifacts_dir
    state = stored.record.state
    if state not in ("launched", "settled_ok", "settled_failed"):
        return False
    if not isinstance(failed_dir, str) or not failed_dir:
        return False
    try:
        return Path(failed_dir).resolve() != target.artifacts_dir.resolve()
    except OSError:
        return failed_dir != str(target.artifacts_dir)


def _handle_replacement_failure(
    stored: Any,
    target: HealerTarget,
    *,
    done: Mapping[str, Any],
    auto_restart: Mapping[str, Any],
    now: float,
    dry_run: bool,
) -> HealerOutcome:
    """Settle and loudly report the one allowed replacement's failure."""
    from sase.agent.auto_restart import ledger as ledger_mod
    from sase.agent.auto_restart._healer_common import escalate_healer, write_recovery

    key = _opt_str(auto_restart.get("ledger_key")) or (
        stored.record.key if stored is not None else None
    )
    episode_id = _opt_str(auto_restart.get("episode_id")) or (
        stored.record.episode_id if stored is not None else None
    )
    reason_text = (
        f"This was its automatic restart after sase update "
        f"{episode_id.removeprefix('sase@') if episode_id else 'a sase update'} "
        "— not retrying."
    )
    recovery = done.get("recovery")
    already_handled = (
        isinstance(recovery, Mapping)
        and recovery.get("state") == "declined"
        and recovery.get("reason") == "already_restarted"
    )
    if not dry_run and not already_handled:
        if stored is not None:
            if stored.record.state == "launched":
                stored = ledger_mod.advance_ledger_record(
                    stored,
                    "settled_failed",
                    note="replacement failed; already_restarted",
                    at=ledger_mod.timestamp_for(now),
                )
            if stored.record.state == "settled_failed":
                stored = annotate_record(stored, decline_reason="already_restarted")
        write_recovery(
            target,
            "declined",
            reason_text,
            now=now,
            ledger_key=key,
            episode_id=episode_id,
            decline_reason="already_restarted",
        )
        with contextlib.suppress(Exception):
            ledger_mod.delete_doorbells_for(str(target.artifacts_dir))
        escalate_healer(
            target,
            reason_text,
            episode_id=episode_id,
            kind="already_restarted",
        )
    elif not dry_run:
        with contextlib.suppress(Exception):
            ledger_mod.delete_doorbells_for(str(target.artifacts_dir))
    return HealerOutcome(
        action="declined",
        reason="already_restarted",
        reason_text=reason_text,
        ledger_key=key,
    )


def _parse_epoch(value: Any) -> float | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        from datetime import datetime

        return datetime.fromisoformat(value).timestamp()
    except (ValueError, TypeError):
        return None


__all__ = [
    "heal_one",
]
