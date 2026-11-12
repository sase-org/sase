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
    launcher_row = _is_launcher_row(target, done=fresh_done, meta=fresh_meta)
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
        try:
            launcher_cwd = _launcher_project_cwd(target.project)
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
    evidence_dir, evidence_files = _write_evidence(
        target, verdict=verdict, assembled=assembled, episode_id=episode_id
    )
    if evidence_dir is not None:
        stored = annotate_record(stored, evidence_dir=evidence_dir)
    if launcher_row:
        provenance_env = _provenance_env(
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
        _attach_provenance(
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
        provenance_env = {}
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
            outcome = _launch_launcher_prompt(
                launcher_prompt, provenance_env, launcher_cwd
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


def _is_launcher_row(
    target: HealerTarget,
    *,
    done: Mapping[str, Any],
    meta: Mapping[str, Any],
) -> bool:
    """Return whether a failed row died before it acquired a workflow name."""

    for payload in (meta, done):
        for key in ("name", "workflow_name"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return False
    return target.agent_name == target.artifacts_dir.name


def _launcher_project_cwd(project: str) -> Path:
    """Find the primary checkout used to submit a prompt for *project*."""

    if project == "home":
        cwd = Path.home()
    else:
        from sase.core.paths import sase_projects_dir
        from sase.core.project_lifecycle_facade import list_project_records

        record = next(
            (
                item
                for item in list_project_records(
                    sase_projects_dir(), "all", include_home=True
                )
                if item.project_name == project
            ),
            None,
        )
        if record is None or not record.workspace_dir:
            raise LookupError(f"project '{project}' has no configured workspace")
        cwd = Path(record.workspace_dir).expanduser()
    if not cwd.is_dir():
        raise FileNotFoundError(f"project workspace does not exist: {cwd}")
    return cwd


def _launch_launcher_prompt(
    prompt: str, extra_env: dict[str, str], cwd: Path | None
) -> Any:
    """Resubmit the original launcher prompt through the normal launch funnel."""

    import contextlib
    from types import SimpleNamespace

    from sase.agent.launcher import launch_agents_from_cwd

    if cwd is None:
        raise RuntimeError("launcher project workspace was not resolved")
    # The regular project launch path atomically claims a free numbered slot.
    # Leave the failed row's hold and artifacts untouched; its slot remains
    # occupied while the replacement claims a different one.
    with contextlib.chdir(cwd):
        results = launch_agents_from_cwd(
            prompt,
            extra_env=extra_env,
            origin="generated",
            source_surface="auto_restart",
        )
    if not results:
        raise RuntimeError("agent launch produced no results")
    launched_dir = getattr(results[0], "artifacts_dir", None) or None
    return SimpleNamespace(status="ok", launched_artifacts_dir=launched_dir, error=None)


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
    evidence_files: dict[str, Any] | None = None,
    witnesses: Any,
    facts: Any,
) -> None:
    from sase.agent.auto_restart.provenance import PROVENANCE_ENV

    env = _provenance_env(
        target,
        verdict=verdict,
        episode_id=episode_id,
        lineage_root=lineage_root,
        ledger_key=ledger_key,
        evidence_dir=evidence_dir,
        evidence_files=evidence_files,
        witnesses=witnesses,
        facts=facts,
    )
    try:
        segment_envs = plan.force_reuse_plan.segment_envs
        for index, overlay in enumerate(segment_envs):
            merged = dict(overlay or {})
            merged.setdefault(PROVENANCE_ENV, env[PROVENANCE_ENV])
            segment_envs[index] = merged
    except AttributeError:
        pass


def _provenance_env(
    target: HealerTarget,
    *,
    verdict: Any,
    episode_id: str | None,
    lineage_root: str,
    ledger_key: str,
    evidence_dir: str | None,
    evidence_files: dict[str, Any] | None = None,
    witnesses: Any,
    facts: Any,
) -> dict[str, str]:
    import datetime

    from sase.agent.auto_restart.provenance import provenance_segment_env
    from sase.core.time import get_timezone

    try:
        file_names = sorted(str(k) for k in (evidence_files or {}).keys())
    except Exception:
        file_names = []
    provenance = {
        "of_artifacts_dir": str(target.artifacts_dir),
        "of_timestamp": target.artifacts_dir.name,
        "lineage_root": lineage_root,
        "episode_id": episode_id,
        "ledger_key": ledger_key,
        "evidence_dir": evidence_dir,
        "evidence_files": file_names,
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
    return provenance_segment_env(provenance)


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
    """Preserve evidence before a relaunch; return the dir and bundle files.

    The ledger evidence directory is outside any artifacts dir, so it survives
    both named-row wipes and launcher-row resubmissions. The named-row restart
    path also copies this payload into its recovery bundle.
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
