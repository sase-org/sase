"""Healer relaunch: plan, guard, execute, and preserve evidence."""

from __future__ import annotations

import hashlib
import json
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
) -> HealerOutcome:
    from sase.agent.auto_restart import ledger as ledger_mod

    key = stored.record.key
    # Re-validate skip rules against fresh state immediately before mutating.
    fresh_done = read_json(target.artifacts_dir / "done.json") or {}
    fresh_meta = read_json(target.artifacts_dir / "agent_meta.json") or {}
    skip: SkipDecision = apply_skip_rules(target, done=fresh_done, meta=fresh_meta)
    if skip.skip:
        stored = ledger_mod.advance_ledger_record(
            stored,
            "decline",
            note=skip.decline_reason,
            at=ledger_mod.timestamp_for(now),
        )
        stored = annotate_record(stored, decline_reason=skip.decline_reason)
        write_recovery(
            target,
            "declined",
            skip.reason_text,
            now=now,
            ledger_key=key,
            episode_id=stored.record.episode_id or episode_id,
            decline_reason=skip.decline_reason,
        )
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
        return defer_heal(stored, target, f"restart planning refused: {exc}", now=now)
    if _wipe_reaches_others(plan, target):
        stored = ledger_mod.advance_ledger_record(
            stored,
            "decline",
            note="wipe_reaches_others",
            at=ledger_mod.timestamp_for(now),
        )
        stored = annotate_record(stored, decline_reason="wipe_reaches_others")
        write_recovery(
            target,
            "declined",
            "wipe reaches other agents",
            now=now,
            ledger_key=key,
            episode_id=stored.record.episode_id or episode_id,
            decline_reason="wipe_reaches_others",
        )
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
        at=ledger_mod.timestamp_for(now),
    )
    stored = annotate_record(stored, planned_name=target.agent_name)
    evidence_dir, evidence_files = _write_evidence(
        target, verdict=verdict, assembled=assembled, episode_id=episode_id
    )
    if evidence_dir is not None:
        stored = annotate_record(stored, evidence_dir=evidence_dir)
    _attach_provenance(
        plan,
        target,
        verdict=verdict,
        episode_id=episode_id,
        lineage_root=lineage_root,
        ledger_key=key,
        evidence_dir=evidence_dir,
        witnesses=assembled.witnesses,
        facts=assembled.facts,
    )
    write_recovery(
        target,
        "launching",
        "relaunching",
        now=now,
        ledger_key=key,
        episode_id=episode_id,
    )
    outcome = (execute_restart or _execute_default)(plan, evidence_files)
    if outcome is None or getattr(outcome, "status", "") != "ok":
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
    # No done.json write here: execute wiped the failed row, and the ledger
    # owns ``launched`` — writing would recreate a phantom artifacts dir.
    publish_relaunch_event(
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
    witnesses: Any,
    facts: Any,
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
        "broke_detail": None,
    }
    refresh = getattr(witnesses, "refresh_log_line", None)
    if refresh is not None:
        provenance["from_rev"] = getattr(refresh, "from_rev", None) or None
        provenance["to_rev"] = getattr(refresh, "to_rev", None) or None
    provenance["from_rev"] = provenance["from_rev"] or _identity_revision(
        getattr(witnesses, "boot_identity", None)
    )
    provenance["to_rev"] = provenance["to_rev"] or _identity_revision(
        getattr(witnesses, "current_identity", None)
    )
    file_proof = getattr(witnesses, "file_proof", None)
    if file_proof is not None:
        provenance["culprit_commit"] = getattr(file_proof, "culprit_commit", None)
        provenance["culprit_subject"] = getattr(file_proof, "culprit_subject", None)
        provenance["to_rev"] = provenance["to_rev"] or provenance["culprit_commit"]
    phase = getattr(facts, "lifecycle_phase", None) or getattr(
        verdict, "phase_class", None
    )
    if phase:
        provenance["broke_detail"] = f"failed during {phase}"
    if refresh is not None:
        from_rev = getattr(refresh, "from_rev", None)
        to_rev = getattr(refresh, "to_rev", None)
        if from_rev and to_rev:
            detail = f"refresh moved sase from {from_rev} to {to_rev}"
            provenance["broke_detail"] = (
                f"{provenance['broke_detail']}; {detail}"
                if provenance["broke_detail"]
                else detail
            )
    env = provenance_segment_env(provenance)
    try:
        segment_envs = plan.force_reuse_plan.segment_envs
        for index, overlay in enumerate(segment_envs):
            merged = dict(overlay or {})
            merged.setdefault(PROVENANCE_ENV, env[PROVENANCE_ENV])
            segment_envs[index] = merged
    except AttributeError:
        pass


def _identity_revision(identity: Any) -> str | None:
    if not isinstance(identity, str) or not identity:
        return None
    parts = identity.split("|")
    for part in parts:
        name, separator, revision = part.partition("@")
        if separator and name == "sase" and revision:
            return revision
    for part in parts:
        _, separator, revision = part.partition("@")
        if separator and revision:
            return revision
    return None


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
    done_dict = read_json(target.artifacts_dir / "done.json") or {}
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
            done=read_json(target.artifacts_dir / "done.json") or {},
            meta=read_json(target.artifacts_dir / "agent_meta.json") or {},
            bundle=None,
            log_path=None,
        )
        return candidate_log_tail(candidate)
    except Exception:
        return ""


__all__ = [
    "relaunch_claimed",
]
