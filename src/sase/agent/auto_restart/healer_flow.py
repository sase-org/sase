"""Healer claimed-pass orchestration: classify, gate, and decide relaunch."""

from __future__ import annotations

import contextlib
from collections.abc import Callable, Mapping
from typing import Any

from sase.agent.auto_restart._healer_common import (
    HealerOutcome,
    HealerTarget,
    SkipDecision,
    annotate_record,
    apply_skip_rules,
    decline_heal,
    defer_heal,
    escalate_healer,
    resurface_healer,
    write_recovery,
)
from sase.agent.auto_restart.healer_relaunch import relaunch_claimed


def heal_claimed(
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
    silenced: bool = True,
) -> HealerOutcome:
    from sase.agent.auto_restart import ledger as ledger_mod

    key = stored.record.key
    skip: SkipDecision = apply_skip_rules(target, done=done, meta=meta)
    if skip.skip:
        if not dry_run:
            stored = ledger_mod.advance_ledger_record(
                stored, "decline", note=skip.decline_reason
            )
            stored = annotate_record(stored, decline_reason=skip.decline_reason)
            write_recovery(target, "declined", skip.reason_text, now=now)
            with contextlib.suppress(Exception):
                ledger_mod.delete_doorbells_for(str(target.artifacts_dir))
            if skip.loud:
                kind = (
                    "already_restarted"
                    if skip.decline_reason == "already_restarted"
                    else "decline"
                )
                escalate_healer(
                    target,
                    skip.reason_text,
                    episode_id=stored.record.episode_id,
                    kind=kind,
                )
            else:
                resurface_healer(target, skip.reason_text)
        return HealerOutcome(
            action="declined",
            reason=skip.decline_reason,
            reason_text=skip.reason_text,
            ledger_key=key,
        )

    try:
        assembled = _assemble(target, done=done, meta=meta)
    except Exception as exc:
        return defer_heal(
            stored,
            target,
            f"could not assemble inputs: {exc}",
            now=now,
            dry_run=dry_run,
        )
    verdict = (classify or _classify_default)(assembled)
    _store_verdict(stored, verdict, assembled, dry_run=dry_run)
    if verdict.mode == "decline":
        return decline_heal(
            stored,
            target,
            verdict.reason or "declined",
            verdict.reason_text or "not an update-skew failure",
            now=now,
            dry_run=dry_run,
            escalate=silenced,
            silenced=silenced,
        )
    if verdict.mode in ("notify_post_provider", "ask"):
        return decline_heal(
            stored,
            target,
            verdict.reason or verdict.mode,
            verdict.reason_text or "not relaunched by policy",
            now=now,
            dry_run=dry_run,
            escalate=silenced,
            escalate_kind=(
                "post_provider" if verdict.mode == "notify_post_provider" else "decline"
            ),
            silenced=silenced,
        )
    if verdict.mode != "relaunch" and verdict.mode != "defer":
        return decline_heal(
            stored,
            target,
            verdict.reason or "declined",
            verdict.reason_text or "classifier declined",
            now=now,
            dry_run=dry_run,
            escalate=silenced,
            silenced=silenced,
        )

    episode_id = verdict.episode_id
    if episode_id is None and derive_episode is not None:
        try:
            episode_id = derive_episode(assembled.witnesses).id or None
        except Exception:
            episode_id = None
    if episode_id is not None and not dry_run:
        stored = annotate_record(stored, episode_id=episode_id)

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
        return defer_heal(
            stored, target, detail or "deferred", now=now, dry_run=dry_run
        )

    storm = _storm_decision(episode_id)
    if not storm.allowed:
        from sase.agent.auto_restart import storm as storm_mod

        if not dry_run:
            try:
                already_paused, _ = storm_mod.is_paused()
            except Exception:
                already_paused = False
            if not already_paused:
                # The pass that trips sends the one storm escalation for the
                # episode; every later target while paused declines quietly.
                storm_mod.trip_pause(reason=storm.reason, episode=episode_id)
                escalate_healer(
                    target, storm.reason, episode_id=episode_id, kind="storm"
                )
        return decline_heal(
            stored,
            target,
            "paused",
            storm.reason,
            now=now,
            dry_run=dry_run,
            silenced=False,
        )

    if dry_run:
        return HealerOutcome(
            action="dry_run",
            reason="would_relaunch",
            reason_text="dry run: pre-provider skew verified; nothing relaunched",
            ledger_key=key,
        )
    return relaunch_claimed(
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


__all__ = [
    "heal_claimed",
]
