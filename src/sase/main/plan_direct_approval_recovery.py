"""Coder recovery evidence for gateless ``sase plan approve`` runs.

When a plan was already approved but the coder that approval owed failed, was
killed, or never launched, approving the plan again starts one replacement
coder instead of refusing. This module gathers the coder evidence behind that
decision; it never launches anything and never raises.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from sase.main.plan_pending_diagnosis import PlanGateHistory

RecoveryVerdict = Literal["live", "succeeded", "recover"]
PriorCoderState = Literal["live", "succeeded", "ended", "missing"]

#: Approval actions that owe a coder. Anything else (epic, reject, feedback,
#: cancel) keeps today's refusal.
CODER_OWING_ACTIONS = frozenset({"tale", "approve", "commit"})


@dataclass(frozen=True)
class PriorCoder:
    """One earlier coder an approval produced, with its observed state."""

    name: str
    state: PriorCoderState
    outcome: str | None = None
    age: str = ""


@dataclass(frozen=True)
class CoderRecovery:
    """The aggregated recovery decision for one already-approved plan."""

    verdict: RecoveryVerdict
    prior_coders: tuple[PriorCoder, ...] = ()
    approved_action: str = "tale"
    approved_age: str = ""
    gate_id: str | None = None
    plan_argument: str = ""
    refusal_code: str = ""


def evaluate_approval_recovery(
    *,
    local_plan: Path,
    history: PlanGateHistory,
    project: str,
    cwd: Path | None = None,
) -> CoderRecovery | None:
    """Decide whether an approved plan's coder should be relaunched.

    Returns ``None`` when the history is not an approval that owed a coder,
    leaving the caller to keep today's refusal. Otherwise aggregates every
    coder source (receipt, gate follow-up, committed status) as live, else
    succeeded, else recover.
    """
    from sase.main.plan_pending_diagnosis import (
        gate_history_for_plan,
        gate_history_committed_ref,
        refined_gate_history_action,
    )
    from sase.plan_approval_receipts import read_direct_approval_receipt

    kind = getattr(history, "kind", "none")
    try:
        receipt = read_direct_approval_receipt(local_plan)
    except Exception:
        receipt = None

    gate_entry: dict[str, object] | None = None
    committed_ref: str | None = None
    gate_id: str | None = None
    if kind == "handled":
        try:
            entries = gate_history_for_plan(local_plan)
        except Exception:
            entries = []
        for entry in entries:
            if (
                isinstance(entry, dict)
                and str(entry.get("state") or "") == "already_handled"
            ):
                gate_entry = entry
                break
        if gate_entry is None:
            return None
        handled_action = str(getattr(history, "action", None) or "").strip().lower()
        try:
            real_action = refined_gate_history_action(history) or handled_action
        except Exception:
            real_action = handled_action
        if real_action not in CODER_OWING_ACTIONS:
            return None
        gate_id = _history_gate_id(history)
        try:
            committed_ref = gate_history_committed_ref(history)
        except Exception:
            committed_ref = None
        approved_age = _bare_age_text(getattr(history, "age", "") or "")
        approved_action = real_action
    elif kind == "direct":
        if receipt is None:
            return None
        action = (receipt.action or "").strip().lower()
        if action not in CODER_OWING_ACTIONS:
            return None
        gate_id = receipt.retired_gate_id or receipt.recovered_gate_id
        committed_ref = receipt.plan_archive_ref
        approved_age = _receipt_age(receipt.approved_at)
        approved_action = action
        gate_entry = _gate_entry_for_plan(local_plan, gate_id)
    else:
        return None

    candidate_names = _candidate_coder_names(receipt, gate_entry, project)
    priors = tuple(_classify_prior_coder(name) for name in candidate_names)
    if receipt is not None and receipt.coder_agent is None and receipt.coder_pid:
        priors = priors + (_classify_pid_coder(receipt.coder_pid),)

    for prior in priors:
        if prior.state == "live":
            return CoderRecovery(
                verdict="live",
                prior_coders=priors,
                approved_action=approved_action,
                approved_age=approved_age,
                gate_id=gate_id,
                plan_argument=committed_ref or str(local_plan),
                refusal_code="coder_running",
            )
    for prior in priors:
        if prior.state == "succeeded":
            return CoderRecovery(
                verdict="succeeded",
                prior_coders=priors,
                approved_action=approved_action,
                approved_age=approved_age,
                gate_id=gate_id,
                plan_argument=committed_ref or str(local_plan),
                refusal_code="already_implemented",
            )
    if committed_ref and _committed_plan_is_done(committed_ref, cwd):
        return CoderRecovery(
            verdict="succeeded",
            prior_coders=priors,
            approved_action=approved_action,
            approved_age=approved_age,
            gate_id=gate_id,
            plan_argument=committed_ref,
            refusal_code="already_implemented",
        )
    return CoderRecovery(
        verdict="recover",
        prior_coders=priors,
        approved_action=approved_action,
        approved_age=approved_age,
        gate_id=gate_id,
        plan_argument=committed_ref or str(local_plan),
        refusal_code="",
    )


def prior_coder_word(prior: PriorCoder) -> str:
    """Return the display word for one prior coder, such as ``failed 14m ago``."""
    if prior.state == "live":
        return (prior.outcome or "running").replace("_", " ") or "running"
    if prior.state == "succeeded":
        return f"completed {prior.age}".strip()
    if prior.state == "ended":
        return f"{prior.outcome or 'failed'} {prior.age}".strip()
    return "not found"


def _candidate_coder_names(
    receipt: object | None,
    gate_entry: dict[str, object] | None,
    project: str,
) -> tuple[str, ...]:
    """Return prior coder names, newest first, without duplicates."""
    names: list[str] = []
    coder_agent = getattr(receipt, "coder_agent", None)
    if isinstance(coder_agent, str) and coder_agent.strip():
        names.append(coder_agent.strip())
    if gate_entry is not None:
        try:
            gate_coder = _gate_followup_coder(gate_entry, project)
        except Exception:
            gate_coder = None
        if gate_coder and gate_coder not in names:
            names.append(gate_coder)
    # A launch failure with no coder means "never launched": the error is
    # evidence, not a coder, so no name is added for it.
    replaced = getattr(receipt, "replaced_coders", ()) or ()
    for old in replaced:
        if isinstance(old, str) and old.strip() and old.strip() not in names:
            names.append(old.strip())
    return tuple(names)


def _gate_followup_coder(entry: dict[str, object], project: str) -> str | None:
    """Return the coder a handled gate entry's follow-up produced, if any."""
    action_data = entry.get("action_data")
    if not isinstance(action_data, dict):
        return None
    notification_id = entry.get("notification_id")
    gate_id = notification_id.strip() if isinstance(notification_id, str) else None
    raw_suffix = action_data.get("raw_suffix")
    if isinstance(raw_suffix, str) and raw_suffix.strip():
        try:
            shell_dir = _gate_shell_dir(project, raw_suffix.strip())
            meta = _read_agent_meta_file(shell_dir)
            if meta is not None and (
                gate_id is None or meta.get("gate_notification_id") == gate_id
            ):
                followup = meta.get("gate_followup_agent")
                if isinstance(followup, str) and followup.strip():
                    return followup.strip()
        except Exception:
            pass
    agent_name: str | None = None
    for key in ("agent_name", "agent_cl_name"):
        value = action_data.get(key)
        if isinstance(value, str) and value.strip():
            agent_name = value.strip()
            break
    if agent_name:
        gate_shell = f"{agent_name}--gate"
        if _registered_coder_matches_gate(gate_shell, gate_id):
            return gate_shell
        if _is_coder_registered(f"{agent_name}--code"):
            return f"{agent_name}--code"
    return None


def _gate_shell_dir(project: str, raw_suffix: str) -> Path:
    from sase.core.agent_artifact_paths import resolve_agent_artifact_timestamp_path

    return resolve_agent_artifact_timestamp_path(project, "ace-run", raw_suffix)


def _read_agent_meta_file(artifact_dir: Path) -> dict[str, object] | None:
    try:
        raw = json.loads((artifact_dir / "agent_meta.json").read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        return None
    return raw if isinstance(raw, dict) else None


def _registered_coder_matches_gate(name: str, gate_id: str | None) -> bool:
    try:
        from sase.agent.names import lookup_registered_name
    except Exception:
        return False
    try:
        entry = lookup_registered_name(name)
    except Exception:
        return False
    if not isinstance(entry, dict):
        return False
    artifacts_dir = entry.get("artifacts_dir")
    if not isinstance(artifacts_dir, str) or not artifacts_dir:
        return False
    if gate_id is None:
        return True
    meta = _read_agent_meta_file(Path(artifacts_dir))
    return meta is not None and meta.get("gate_notification_id") == gate_id


def _is_coder_registered(name: str) -> bool:
    try:
        from sase.agent.names import lookup_registered_name
    except Exception:
        return False
    try:
        return lookup_registered_name(name) is not None
    except Exception:
        return False


def _classify_prior_coder(name: str) -> PriorCoder:
    """Classify one coder by name with a cheap, targeted read."""
    try:
        from sase.agent.names import lookup_registered_name
    except Exception:
        return PriorCoder(name=name, state="missing")
    try:
        entry = lookup_registered_name(name)
    except Exception:
        return PriorCoder(name=name, state="missing")
    if not isinstance(entry, dict):
        return PriorCoder(name=name, state="missing")
    artifacts_dir = entry.get("artifacts_dir")
    if not isinstance(artifacts_dir, str) or not artifacts_dir:
        return PriorCoder(name=name, state="missing")
    if entry.get("state") == "dismissed":
        return _classify_dismissed_coder(name, artifacts_dir)
    return _classify_scanned_coder(name, artifacts_dir)


def _classify_dismissed_coder(name: str, artifacts_dir: str) -> PriorCoder:
    """Classify a dismissed coder from its archived completion, if any."""
    from sase.core.dismissed_agent_completion import (
        WAIT_SUCCESS_OUTCOMES,
        load_archived_agent_completions,
    )

    directory = Path(artifacts_dir)
    meta = _read_agent_meta_file(directory) or {}
    project = _project_for_artifact_dir(directory)
    try:
        completions = load_archived_agent_completions(
            [(directory, meta, project or "")]
        )
    except Exception:
        completions = {}
    completion = completions.get(str(directory))
    age = _mtime_age(directory)
    if completion is None:
        return PriorCoder(name=name, state="ended", outcome=None, age=age)
    if completion.outcome in WAIT_SUCCESS_OUTCOMES:
        return PriorCoder(name=name, state="succeeded", outcome="completed", age=age)
    return PriorCoder(
        name=name, state="ended", outcome=completion.outcome or "failed", age=age
    )


def _classify_scanned_coder(name: str, artifacts_dir: str) -> PriorCoder:
    """Classify one registered coder from its artifact directory snapshot."""
    from sase.agent.wait_watch import (
        WaitState,
        WaitTarget,
        WaitTargetKind,
        classify_wait_target,
        wait_scan_options,
    )
    from sase.core.agent_scan_facade import scan_agent_artifact_dirs
    from sase.core.paths import sase_projects_dir

    directory = Path(artifacts_dir)
    scan_dirs: list[Path | str] = [directory]
    successor = _retry_successor_dir(directory)
    if successor is not None:
        scan_dirs.append(successor)
    try:
        snapshot = scan_agent_artifact_dirs(
            sase_projects_dir(), scan_dirs, wait_scan_options()
        )
        target = WaitTarget(
            raw_name=name,
            name=name,
            kind=WaitTargetKind.AGENT,
            artifact_dir=str(directory),
        )
        classified = classify_wait_target(target, snapshot.records)
    except Exception:
        return PriorCoder(name=name, state="ended", outcome=None, age="")
    state = classified.state
    if state == WaitState.SUCCEEDED:
        outcome = classified.members[0].outcome if classified.members else None
        return PriorCoder(
            name=name,
            state="succeeded",
            outcome=outcome or "completed",
            age=_done_age(directory),
        )
    if state in (
        WaitState.RUNNING,
        WaitState.STARTING,
        WaitState.QUEUED,
        WaitState.WAITING,
        WaitState.NEEDS_INPUT,
        WaitState.NEEDS_REVIEW,
    ):
        return PriorCoder(name=name, state="live", outcome=str(state.value))
    if state in (WaitState.FAILED, WaitState.TERMINAL_OTHER, WaitState.STALLED):
        outcome = classified.members[0].outcome if classified.members else None
        return PriorCoder(
            name=name, state="ended", outcome=outcome, age=_done_age(directory)
        )
    return PriorCoder(name=name, state="ended", outcome=None, age="")


def _classify_pid_coder(pid: int) -> PriorCoder:
    """Classify a receipt coder recorded with a PID but no name."""
    try:
        os.kill(pid, 0)
    except (OSError, ValueError, OverflowError):
        return PriorCoder(name=f"PID {pid}", state="ended", outcome=None, age="")
    return PriorCoder(name=f"PID {pid}", state="live", outcome="running")


def _retry_successor_dir(directory: Path) -> Path | None:
    """Return the ``retried_as_timestamp`` successor directory, if named."""
    try:
        raw = json.loads((directory / "done.json").read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        return None
    if not isinstance(raw, dict):
        return None
    successor = raw.get("retried_as_timestamp")
    if not isinstance(successor, str) or not successor.strip():
        return None
    candidate = directory.parent / successor.strip()
    try:
        if candidate.is_dir():
            return candidate
    except OSError:
        return None
    return None


def _project_for_artifact_dir(directory: Path) -> str | None:
    try:
        from sase.core.agent_artifact_paths import parse_agent_artifact_path

        info = parse_agent_artifact_path(directory)
    except Exception:
        return None
    return info.project_name if info is not None else None


def _committed_plan_is_done(committed_ref: str, cwd: Path | None) -> bool:
    """Best-effort safety net: a committed plan with ``status: done`` succeeded."""
    try:
        from sase.core.paths import sase_home
        from sase.sdd.frontmatter import parse_frontmatter
        from sase.sdd.plan_refs import (
            resolve_plan_reference_from_roots,
            resolve_plan_roots,
            workspace_context_for_plan_resolution,
        )
    except Exception:
        return False
    try:
        base = cwd if cwd is not None else Path.cwd()
        workspace_dir, workspace_num = workspace_context_for_plan_resolution(base)
        roots = resolve_plan_roots(workspace_dir, workspace_num)
        resolution = resolve_plan_reference_from_roots(committed_ref, roots=roots)
        if resolution.status not in ("exact", "drifted"):
            return False
        if resolution.resolved_path is None:
            return False
        resolved = Path(resolution.resolved_path)
        try:
            resolved.relative_to(
                sase_home().expanduser().resolve(strict=False) / "plans"
            )
            return False
        except (ValueError, OSError):
            pass
        frontmatter, _body, _had_frontmatter = parse_frontmatter(
            resolved.read_text(encoding="utf-8")
        )
    except Exception:
        return False
    status = frontmatter.get("status")
    return isinstance(status, str) and status.strip().lower() == "done"


def _gate_entry_for_plan(
    local_plan: Path, gate_id: str | None
) -> dict[str, object] | None:
    """Return the newest already-handled gate entry for *local_plan* or *gate_id*."""
    from sase.main.plan_pending_diagnosis import gate_history_for_plan

    try:
        entries = gate_history_for_plan(local_plan)
    except Exception:
        entries = []
    for entry in entries:
        if (
            isinstance(entry, dict)
            and str(entry.get("state") or "") == "already_handled"
        ):
            return entry
    if gate_id:
        found = _gate_entry_for_notification(gate_id)
        if found is not None:
            return found
    return None


def _gate_entry_for_notification(gate_id: str) -> dict[str, object] | None:
    try:
        from sase.notifications.pending_actions import read_pending_action_store
    except Exception:
        return None
    try:
        store = read_pending_action_store(include_legacy=True)
    except Exception:
        return None
    actions = store.get("actions", {})
    if not isinstance(actions, dict):
        return None
    for key, entry in actions.items():
        if not isinstance(entry, dict):
            continue
        entry_id = entry.get("notification_id")
        if isinstance(entry_id, str) and (
            entry_id == gate_id
            or entry_id.startswith(gate_id)
            or gate_id.startswith(entry_id)
        ):
            return entry
        if isinstance(key, str) and (
            key == gate_id or gate_id.startswith(key) or key.startswith(gate_id)
        ):
            return entry
    return None


def _history_gate_id(history: object) -> str | None:
    notification_id = getattr(history, "notification_id", None)
    if isinstance(notification_id, str) and notification_id.strip():
        return notification_id.strip()
    return None


def _bare_age_text(age: str) -> str:
    """Strip the ``(…)`` wrapper from a ``_relative_age`` string."""
    text = age.strip()
    if text.startswith("(") and text.endswith(")"):
        return text[1:-1].strip()
    return text


def _receipt_age(approved_at: str) -> str:
    from datetime import datetime

    try:
        parsed = datetime.fromisoformat(approved_at.strip())
    except (ValueError, AttributeError):
        return ""
    try:
        stamp = parsed.timestamp()
    except (OverflowError, OSError, ValueError):
        return ""
    return _bare_age_text(_relative_age(stamp))


def _relative_age(created_at_unix: float) -> str:
    if created_at_unix <= 0:
        return ""
    age_seconds = int(time.time() - created_at_unix)
    if age_seconds < 0:
        return ""
    if age_seconds < 60:
        return f" ({age_seconds}s ago)"
    minutes = age_seconds // 60
    if minutes < 60:
        return f" ({minutes}m ago)"
    hours = minutes // 60
    if hours < 48:
        return f" ({hours}h ago)"
    return f" ({hours // 24}d ago)"


def _mtime_age(path: Path) -> str:
    try:
        stamp = path.stat().st_mtime
    except OSError:
        return ""
    return _bare_age_text(_relative_age(stamp))


def _done_age(directory: Path) -> str:
    done = directory / "done.json"
    try:
        if done.is_file():
            return _mtime_age(done)
    except OSError:
        pass
    return ""


__all__ = [
    "CODER_OWING_ACTIONS",
    "CoderRecovery",
    "PriorCoder",
    "PriorCoderState",
    "RecoveryVerdict",
    "evaluate_approval_recovery",
    "prior_coder_word",
]
