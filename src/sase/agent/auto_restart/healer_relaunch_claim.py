"""Healer relaunch claim: plan, guard, execute, and preserve evidence."""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from sase.agent.auto_restart._healer_common import (
    HealerOutcome,
    HealerTarget,
    SkipDecision,
    annotate_record,
    apply_skip_rules,
    defer_heal,
    publish_relaunch_event,
    read_json,
    resurface_healer,
    write_recovery,
)
from sase.agent.auto_restart._healer_relaunch_evidence import write_evidence
from sase.agent.auto_restart._healer_relaunch_launcher import (
    is_launcher_row,
    launch_launcher_prompt,
    launcher_has_force_reuse,
    launcher_intended_names,
    launcher_project_cwd,
    prepare_launcher_reservation,
)
from sase.agent.auto_restart._healer_relaunch_provenance import (
    attach_provenance,
    provenance_env,
)


def relaunch_claimed(
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
    silenced: bool = True,
) -> HealerOutcome:
    from sase.agent.auto_restart import ledger as ledger_mod
    from sase.agent.auto_restart._healer_common import decline_heal

    key = stored.record.key
    # Re-validate skip rules against fresh state immediately before mutating.
    fresh_done = read_json(target.artifacts_dir / "done.json") or {}
    fresh_meta = read_json(target.artifacts_dir / "agent_meta.json") or {}
    skip: SkipDecision = apply_skip_rules(target, done=fresh_done, meta=fresh_meta)
    if skip.skip:
        effective_silenced = silenced or skip.decline_reason == "already_restarted"
        kind = (
            "already_restarted"
            if skip.decline_reason == "already_restarted"
            else "decline"
        )
        return decline_heal(
            stored,
            target,
            skip.decline_reason,
            skip.reason_text,
            now=now,
            dry_run=False,
            escalate=skip.loud,
            episode_id=stored.record.episode_id or episode_id,
            escalate_kind=kind,
            silenced=effective_silenced,
        )
    launcher_row = is_launcher_row(target, done=fresh_done, meta=fresh_meta)
    launcher_prompt: str | None = None
    launcher_cwd: Path | None = None
    if launcher_row:
        prompt_path = target.artifacts_dir / "raw_prompt.md"
        try:
            launcher_prompt = prompt_path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            return decline_heal(
                stored,
                target,
                "launcher_prompt_missing",
                "not restarted — the launcher row has no readable raw_prompt.md",
                now=now,
                dry_run=False,
                escalate=False,
                episode_id=stored.record.episode_id or episode_id,
                silenced=silenced,
            )
        if not launcher_prompt.strip():
            return decline_heal(
                stored,
                target,
                "launcher_prompt_empty",
                "not restarted — raw_prompt.md is empty",
                now=now,
                dry_run=False,
                escalate=False,
                episode_id=stored.record.episode_id or episode_id,
                silenced=silenced,
            )
        try:
            from sase.agent.multi_prompt import parse_multi_prompt

            if len(parse_multi_prompt(launcher_prompt).segments) > 1:
                return decline_heal(
                    stored,
                    target,
                    "multi_segment",
                    "not restarted — raw_prompt.md contains multiple prompt segments",
                    now=now,
                    dry_run=False,
                    escalate=False,
                    episode_id=stored.record.episode_id or episode_id,
                    silenced=silenced,
                )
        except Exception as exc:
            return decline_heal(
                stored,
                target,
                "launcher_prompt_invalid",
                f"not restarted — raw_prompt.md could not be parsed: {exc}",
                now=now,
                dry_run=False,
                escalate=False,
                episode_id=stored.record.episode_id or episode_id,
                silenced=silenced,
            )
        if launcher_has_force_reuse(launcher_prompt):
            return decline_heal(
                stored,
                target,
                "launcher_force_reuse",
                "not restarted — raw_prompt.md requests forced name reuse",
                now=now,
                dry_run=False,
                escalate=False,
                episode_id=stored.record.episode_id or episode_id,
                silenced=silenced,
            )
        try:
            launcher_cwd = launcher_project_cwd(target.project)
        except Exception as exc:
            return defer_heal(
                stored,
                target,
                f"launcher project lookup refused: {exc}",
                now=now,
            )
        plan = None
    else:
        try:
            plan = (plan_restart or _plan_default)(
                target.agent_name, follow_live_autonomy=True
            )
        except Exception as exc:
            return defer_heal(
                stored, target, f"restart planning refused: {exc}", now=now
            )
        if _wipe_reaches_others(plan, target):
            return decline_heal(
                stored,
                target,
                "wipe_reaches_others",
                "not restarted — the name wipe would reach other agents",
                now=now,
                dry_run=False,
                escalate=False,
                episode_id=stored.record.episode_id or episode_id,
                silenced=silenced,
            )

    if launcher_row:
        assert launcher_prompt is not None
    else:
        assert plan is not None
    stored = ledger_mod.advance_ledger_record(
        stored,
        "begin_launch",
        note=(
            "resubmitting launcher raw prompt"
            if launcher_row
            else f"launching {target.agent_name}"
        ),
        extra={
            "python_plan_digest": (
                _prompt_digest(launcher_prompt) if launcher_row else _plan_digest(plan)
            )
        },
        at=ledger_mod.timestamp_for(now),
    )
    if not launcher_row:
        stored = annotate_record(stored, planned_name=target.agent_name)
    else:
        # Record the intended concrete identity for adoption and lineage
        # mapping. This is annotation-only; the actual reservation handoff
        # happens at the mutation boundary below.
        try:
            _intended = launcher_intended_names(launcher_prompt or "")
        except Exception:
            _intended = []
        if _intended:
            stored = annotate_record(stored, planned_name=_intended[0])
    evidence_dir, evidence_files = write_evidence(
        target, verdict=verdict, assembled=assembled, episode_id=episode_id
    )
    if evidence_dir is not None:
        stored = annotate_record(stored, evidence_dir=evidence_dir)
    if launcher_row:
        provenance_env_map = provenance_env(
            target,
            verdict=verdict,
            episode_id=episode_id,
            lineage_root=lineage_root,
            ledger_key=key,
            evidence_dir=evidence_dir,
            evidence_files=evidence_files,
            witnesses=assembled.witnesses,
            facts=assembled.facts,
        )
    else:
        attach_provenance(
            plan,
            target,
            verdict=verdict,
            episode_id=episode_id,
            lineage_root=lineage_root,
            ledger_key=key,
            evidence_dir=evidence_dir,
            evidence_files=evidence_files,
            witnesses=assembled.witnesses,
            facts=assembled.facts,
        )
        provenance_env_map = {}
    write_recovery(
        target,
        "launching",
        "relaunching",
        now=now,
        ledger_key=key,
        episode_id=episode_id,
    )
    try:
        if launcher_row:
            assert launcher_prompt is not None
            # Mutation boundary: recheck ownership/liveness, release only the
            # failed row's own planned reservation, then re-validate with the
            # real launch guard. Any change fails closed as execute_failed
            # without launching a duplicate.
            prepare_launcher_reservation(launcher_prompt, target)
            outcome = launch_launcher_prompt(
                launcher_prompt, provenance_env_map, launcher_cwd
            )
        else:
            outcome = (execute_restart or _execute_default)(plan, evidence_files)
    except Exception as exc:
        from types import SimpleNamespace

        outcome = SimpleNamespace(status="failed", error=str(exc))
    if outcome is None or getattr(outcome, "status", "") != "ok":
        import contextlib as _contextlib

        error = getattr(outcome, "error", None) or "execute failed"
        stored = ledger_mod.advance_ledger_record(
            stored,
            "settled_failed",
            note=str(error)[:200],
            at=ledger_mod.timestamp_for(now),
        )
        stored = annotate_record(stored, decline_reason="execute_failed")
        write_recovery(
            target,
            "declined",
            str(error)[:300],
            now=now,
            ledger_key=key,
            episode_id=episode_id,
            decline_reason="execute_failed",
        )
        if isinstance(episode_id, str) and episode_id:
            with _contextlib.suppress(Exception):
                from sase.agent.auto_restart.notify import (
                    refresh_episode_report,
                    refresh_episode_rows,
                )

                refresh_episode_report(episode_id)
                refresh_episode_rows(episode_id)
        with _contextlib.suppress(Exception):
            ledger_mod.delete_doorbells_for(str(target.artifacts_dir))
        if silenced:
            resurface_healer(target, str(error)[:300])
        return HealerOutcome(
            action="declined",
            reason="execute_failed",
            reason_text=str(error)[:300],
            ledger_key=key,
            evidence_dir=evidence_dir,
        )
    launched_dir = getattr(outcome, "launched_artifacts_dir", None)
    stored = ledger_mod.advance_ledger_record(
        stored, "launched", at=ledger_mod.timestamp_for(now)
    )
    stored = annotate_record(stored, launched_artifacts_dir=launched_dir)
    if launcher_row:
        # The replacement was launched without wiping the failed bootstrap
        # row. Keep its evidence and mark it terminal so scans do not treat
        # this preserved row as pending work.
        write_recovery(
            target,
            "relaunched",
            "relaunched from raw_prompt.md",
            now=now,
            ledger_key=key,
            episode_id=episode_id,
        )
        import contextlib

        with contextlib.suppress(Exception):
            ledger_mod.delete_doorbells_for(str(target.artifacts_dir))
    # The named path's execute step wiped the failed row, so writing done.json
    # here would recreate a phantom artifacts directory. Launcher rows remain
    # intact and receive the terminal recovery marker above.
    publish_relaunch_event(
        target, verdict=verdict, episode_id=episode_id, evidence_dir=evidence_dir
    )
    return HealerOutcome(
        action="relaunched",
        reason="relaunch",
        reason_text=(
            f"relaunched launcher row {target.agent_name} from raw_prompt.md"
            if launcher_row
            else f"relaunched {target.agent_name} under the same name"
        ),
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


def _prompt_digest(prompt: str | None) -> str:
    return hashlib.sha256(str(prompt or "").encode("utf-8")).hexdigest()[:16]


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


__all__ = [
    "relaunch_claimed",
]
