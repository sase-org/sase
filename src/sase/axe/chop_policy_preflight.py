"""Preflight guard and trigger evaluation for runner-owned chop policies."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sase.core.axe_chop_facade import (
    CHOP_ENGINE_SCHEMA_VERSION,
    evaluate_chop_decision,
)
from sase.core.time import get_timezone

from .chop_policy_snapshots import (
    agent_snapshots,
    fs_snapshot,
    git_snapshot,
    patch_snapshots,
)
from .chop_policy_state import read_checkpoint_document
from .chop_policy_types import ChopPreflight
from .config import ChopConfig


def evaluate_chop_preflight(
    *,
    lumberjack_name: str,
    chop: ChopConfig,
    context_file: str | None,
    scheduled: bool,
    force: bool = False,
    now: datetime | None = None,
) -> ChopPreflight:
    """Evaluate configured guards and trigger before dispatching a chop.

    Manual runs replace the configured trigger with ``always`` while retaining
    guards. ``force`` is manual-run escape hatch that bypasses both.
    """
    if force:
        return ChopPreflight(
            outcome="fire",
            reason="forced manual run bypassed declarative guards and trigger",
        )

    timestamp = (now or datetime.now(get_timezone())).isoformat()
    try:
        checkpoint = read_checkpoint_document(lumberjack_name, chop.name)
        patches = (
            patch_snapshots(context_file)
            if any(
                # Legacy compatibility: persisted chop policies may still use
                # the old provider name.
                guard.get("provider") in {"patch", "changespec"}  # legacy provider name
                for guard in chop.inhibit_if
            )
            else []
        )
        agents = (
            agent_snapshots(chop.inhibit_if)
            if any(
                guard.get("provider") in {"agent_hood", "agent_clan", "agent_runners"}
                for guard in chop.inhibit_if
            )
            else []
        )

        trigger = chop.trigger if scheduled else {"provider": "always"}
        git: list[dict[str, Any]] = []
        fs: dict[str, Any] | None = None
        checkpoint_for_decision = checkpoint
        if trigger.get("provider") == "git.commits_since":
            git_snapshot_data, checkpoint_for_decision = git_snapshot(
                trigger,
                checkpoint,
            )
            if git_snapshot_data is not None:
                git.append(git_snapshot_data)
        elif trigger.get("provider") == "fs":
            fs = fs_snapshot(trigger)

        request: dict[str, Any] = {
            "schema_version": CHOP_ENGINE_SCHEMA_VERSION,
            "inhibit_if": chop.inhibit_if,
            "trigger": trigger,
            "changespecs": patches,  # legacy engine wire key
            "agents": agents,
            "git": git,
            "checkpoint": checkpoint_for_decision,
            "now": timestamp,
        }
        if fs is not None:
            request["fs"] = fs
        decision = evaluate_chop_decision(request)
    except Exception as exc:
        return ChopPreflight(
            outcome="check_error",
            reason=f"declarative chop preflight failed: {exc}",
        )

    outcome = str(decision.get("outcome"))
    if outcome not in {"fire", "skip", "check_error"}:
        return ChopPreflight(
            outcome="check_error",
            reason=f"declarative chop preflight returned invalid outcome {outcome!r}",
            decision=decision,
        )
    return ChopPreflight(
        outcome=outcome,  # type: ignore[arg-type]
        reason=str(decision.get("reason") or "no decision reason was provided"),
        decision=decision,
        checkpoint_enabled=scheduled,
    )


__all__ = ["evaluate_chop_preflight"]
