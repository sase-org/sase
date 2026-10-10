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
                stored = annotate_record(stored, decline_reason="deferred_expired")
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
        stored = ledger_mod.store_ledger_record(stored)
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
        )
        stored = annotate_record(stored, launched_artifacts_dir=replacement)
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
    stored = annotate_record(stored, decline_reason="launch_aborted")
    write_recovery(target, "declined", "claimer died before launch", now=now)
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
