"""Runner-side hijack latch boundaries.

The runner is the latch owner: it reached a safe agent-turn boundary and
must suppress its own follow-up instead of launching a successor. These
helpers let ``sase.axe`` funnels observe, apply, and moot the durable latch
without reimplementing core policy.

Lock order (parent-approved): ``adoption -> ... -> hijack ledger/target
index -> patch_lock``. Callers must hold the adoption lock before calling
the staged-adoption checkpoint; the checkpoint acquires only hijack locks.
Never call these helpers while holding ``patch_lock``.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

HIJACK_BOUNDARY_STAGED_ADOPTION = "staged_adoption"
HIJACK_BOUNDARY_ADOPTION_REPLAY = "adoption_replay"
HIJACK_BOUNDARY_INPROCESS_SUCCESSOR = "inprocess_successor"
HIJACK_BOUNDARY_RUN_END = "run_end"
HIJACK_BOUNDARY_RETRY = "retry"
HIJACK_BOUNDARY_DETACHED_DELIVERY = "detached_delivery"

_HIJACK_REASON_MARK = "hijack latch"

_SUPPRESSED_INPROCESS_FILENAME = ".sase_suppressed_inprocess_prompt.md"


def is_hijack_suppressed_reason(reason: str | None) -> bool:
    """Return whether a held reason reports a suppressed hijack handoff."""
    return isinstance(reason, str) and _HIJACK_REASON_MARK in reason.lower()


def _read_meta(artifacts_dir: str) -> dict[str, Any]:
    try:
        import json

        with open(Path(artifacts_dir) / "agent_meta.json", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _runner_target_key(artifacts_dir: str) -> str | None:
    """Return the latch target key for the runner that owns *artifacts_dir*."""
    from sase.agent.hijack import ledger

    meta = _read_meta(artifacts_dir)
    project_file = meta.get("project_file")
    if not isinstance(project_file, str) or not project_file.strip():
        project_file = os.environ.get("SASE_AGENT_PROJECT_FILE")
    if not isinstance(project_file, str) or not project_file.strip():
        return None
    home = bool(meta.get("is_home_mode") or meta.get("is_home"))
    session = meta.get("agent_session")
    session_name = (
        session.strip() if isinstance(session, str) and session.strip() else None
    )
    if session_name is None:
        name = meta.get("name")
        session_name = name.strip() if isinstance(name, str) and name.strip() else None
    # Fall back to the run metadata file the staged dispatcher already trusts.
    if session_name is None or not project_file:
        try:
            import json

            run_meta_path = Path(artifacts_dir) / "agent_meta.json"
            _ = run_meta_path
        except Exception:
            pass
    if session_name is None:
        return None
    project = None if home else project_file
    return ledger.target_key_for(project, session_name)


def _runner_identity(artifacts_dir: str) -> tuple[int | None, str | None]:
    pid = os.getpid()
    meta = _read_meta(artifacts_dir)
    recorded = meta.get("process_identity")
    recorded_identity = recorded.strip() if isinstance(recorded, str) else ""
    try:
        from sase.core.process_identity import process_identity_token

        current = process_identity_token(pid)
    except (OSError, RuntimeError, ValueError):
        current = ""
    if not current or (recorded_identity and current != recorded_identity):
        return pid, None
    return pid, current


def _build_runner_target(artifacts_dir: str) -> Any | None:
    """Build the latch :class:`HijackTarget` for the calling runner.

    Returns ``None`` when no active latch record owns this target or when
    the runner cannot prove it is the recorded owner.
    """
    from sase.agent.hijack import ledger
    from sase.agent.hijack._stop_models import HijackTarget

    target_key = _runner_target_key(artifacts_dir)
    if not target_key:
        return None
    record = ledger.find_active_record_by_target_key(target_key)
    if record is None:
        return None
    meta = _read_meta(artifacts_dir)
    pid, _identity = _runner_identity(artifacts_dir)
    if pid is None or record.get("owner_pid") != pid:
        return None
    if str(record.get("artifacts_dir") or "") != artifacts_dir:
        return None
    name = str(record.get("agent_name") or "")
    if not name:
        return None
    artifacts_timestamp = Path(artifacts_dir).name
    project_file = meta.get("project_file")
    if not isinstance(project_file, str) or not project_file:
        project_file = record.get("project_file") or os.environ.get(
            "SASE_AGENT_PROJECT_FILE", ""
        )
    if not isinstance(project_file, str) or not project_file:
        return None
    claim_pid = record.get("owner_pid")
    workspace_num = meta.get("workspace_num", record.get("workspace_num"))
    try:
        workspace_num_int = int(workspace_num) if workspace_num is not None else None
    except (TypeError, ValueError):
        workspace_num_int = None
    cl_name = meta.get("cl_name") or meta.get("patch_name") or record.get("cl_name")
    workflow = meta.get("workflow_name") or record.get("workflow")
    claim_owner_pid = (
        claim_pid
        if isinstance(claim_pid, int) and not isinstance(claim_pid, bool)
        else None
    )
    if not workflow and workspace_num_int is not None and claim_owner_pid is not None:
        try:
            from sase.running_field import get_claimed_workspaces

            matching_claims = [
                claim
                for claim in get_claimed_workspaces(project_file)
                if claim.workspace_num == workspace_num_int
                and claim.pid == claim_owner_pid
                and (claim.cl_name or "") == (cl_name or "")
                and (claim.artifacts_timestamp or "") == artifacts_timestamp
            ]
        except Exception:
            matching_claims = []
        if len(matching_claims) == 1:
            workflow = matching_claims[0].workflow
    workspace_dir = meta.get("workspace_dir") or record.get("workspace_dir")
    capabilities = meta.get("runner_capabilities")
    capability_list = (
        [str(item) for item in capabilities] if isinstance(capabilities, list) else []
    )

    def _meta_str(*keys: str) -> str | None:
        for key in keys:
            value = meta.get(key)
            if isinstance(value, str) and value:
                return value
        return None

    return HijackTarget(
        name=name,
        artifacts_dir=artifacts_dir,
        project_name=meta.get("project_name") or record.get("project_name") or "",
        project_file=project_file,
        artifacts_timestamp=artifacts_timestamp,
        is_home=bool(meta.get("is_home_mode") or meta.get("is_home") or False),
        pid=pid,
        claim_pid=claim_owner_pid,
        claim_pinned=False,
        cl_name=cl_name if isinstance(cl_name, str) else None,
        workflow=workflow if isinstance(workflow, str) else None,
        workspace_num=workspace_num_int,
        workspace_dir=workspace_dir if isinstance(workspace_dir, str) else None,
        status="RUNNING",
        lifecycle_phase=None,
        is_monitor_turn=False,
        is_gate_turn=False,
        gate_state=None,
        agent_session=(
            _meta_str("agent_session") or str(record.get("agent_session") or "") or None
        ),
        capabilities=capability_list,
        model_alias=_meta_str("model_alias"),
        model_alias_trail=[],
        model_origin=_meta_str("prompt_origin", "model_origin"),
        provider=_meta_str("llm_provider", "exec_llm_provider", "provider"),
        model=_meta_str("model", "agent_model"),
        effort=None,
        run_started_at=None,
        done_outcome=None,
        done_recovery=None,
    )


def observe_runner_latch(artifacts_dir: str, boundary: str) -> dict[str, Any]:
    """Return the Rust-validated latch verdict for the calling runner."""
    from sase.agent.hijack import latch

    target_key = _runner_target_key(artifacts_dir)
    if not target_key:
        return {
            "verdict": "no_latch",
            "code": "no_latch",
            "message": "the runner has no latch target identity",
            "hijack_id": None,
            "target_key": None,
            "record": None,
        }
    meta = _read_meta(artifacts_dir)
    name = meta.get("name")
    member = name.strip() if isinstance(name, str) and name.strip() else ""
    pid, identity = _runner_identity(artifacts_dir)
    return latch.observe_hijack_latch(
        target_key,
        boundary,
        member=member or None,
        artifacts_dir=artifacts_dir,
        owner_pid=pid,
        owner_identity=identity,
    )


def _raise_if_latched(verdict: dict[str, Any], *, boundary: str) -> None:
    from sase.agent.hijack.spawn_guard import HijackLatchedError

    state = str(verdict.get("verdict") or "")
    if state not in {"pending", "applied"}:
        return
    hijack_id = verdict.get("hijack_id")
    raise HijackLatchedError(
        f"hijack latch {hijack_id or 'unknown'} is {state}; "
        f"{boundary} progression suppressed",
        hijack_id=hijack_id if isinstance(hijack_id, str) else None,
        target_key=(str(verdict.get("target_key") or "") or None),
        verdict=state,
    )


def enforce_staged_adoption_latch(
    artifacts_dir: str,
    staged_id: str,
    staged_kind: str,
) -> dict[str, Any]:
    """Apply a pending latch before any staged adopter runs.

    Must be called while holding the adoption lock. A pending latch is
    applied with the staged payload retained as the suppressed follow-up;
    pending and applied latches raise :class:`HijackLatchedError` so the
    caller records a hijacked (not failed) outcome and never runs an adopter.
    """
    from sase.agent.hijack import latch

    observed = observe_runner_latch(artifacts_dir, HIJACK_BOUNDARY_STAGED_ADOPTION)
    verdict = str(observed.get("verdict") or "")
    if verdict == "no_latch":
        return observed
    if verdict not in {"pending", "applied"}:
        return observed
    if verdict == "pending":
        from sase.agent._staged_handoff_store import STAGED_HANDOFF_FILENAME

        target = _build_runner_target(artifacts_dir)
        if target is None:
            _raise_if_latched(observed, boundary=HIJACK_BOUNDARY_STAGED_ADOPTION)
            return observed
        applied = latch.apply_latch_at_boundary(
            str(observed.get("target_key") or ""),
            HIJACK_BOUNDARY_STAGED_ADOPTION,
            "handoff",
            target=target,
            suppressed_followup={
                "kind": str(staged_kind or "staged"),
                "ref": str(Path(artifacts_dir) / STAGED_HANDOFF_FILENAME),
            },
        )
        _raise_if_latched(applied, boundary=HIJACK_BOUNDARY_STAGED_ADOPTION)
        return applied
    _raise_if_latched(observed, boundary=HIJACK_BOUNDARY_STAGED_ADOPTION)
    return observed


def enforce_adoption_replay_latch(artifacts_dir: str) -> dict[str, Any]:
    """Refuse to replay an already-suppressed staged progression."""
    observed = observe_runner_latch(artifacts_dir, HIJACK_BOUNDARY_ADOPTION_REPLAY)
    _raise_if_latched(observed, boundary=HIJACK_BOUNDARY_ADOPTION_REPLAY)
    return observed


def enforce_inprocess_successor_latch(
    artifacts_dir: str,
    *,
    prompt: str | None = None,
) -> dict[str, Any]:
    """Apply a pending latch before mutating in-process member identity.

    Call before any ``before_state_change`` or artifact creation. The
    suppressed in-process prompt is retained on disk and referenced from the
    latch record; applied latches raise without re-applying.
    """
    from sase.agent.hijack import latch

    observed = observe_runner_latch(artifacts_dir, HIJACK_BOUNDARY_INPROCESS_SUCCESSOR)
    verdict = str(observed.get("verdict") or "")
    if verdict == "pending":
        ref = artifacts_dir
        if isinstance(prompt, str) and prompt.strip():
            try:
                suppressed_path = Path(artifacts_dir) / _SUPPRESSED_INPROCESS_FILENAME
                suppressed_path.write_text(prompt, encoding="utf-8")
                ref = str(suppressed_path)
            except OSError:
                ref = artifacts_dir
        target = _build_runner_target(artifacts_dir)
        if target is None:
            _raise_if_latched(observed, boundary=HIJACK_BOUNDARY_INPROCESS_SUCCESSOR)
            return observed
        applied = latch.apply_latch_at_boundary(
            str(observed.get("target_key") or ""),
            HIJACK_BOUNDARY_INPROCESS_SUCCESSOR,
            "handoff",
            target=target,
            suppressed_followup={"kind": "inprocess", "ref": ref},
        )
        _raise_if_latched(applied, boundary=HIJACK_BOUNDARY_INPROCESS_SUCCESSOR)
        return applied
    _raise_if_latched(observed, boundary=HIJACK_BOUNDARY_INPROCESS_SUCCESSOR)
    return observed


def moot_runner_latch_at_run_end(
    artifacts_dir: str,
    outcome: str,
) -> dict[str, Any]:
    """Moot a still-pending latch when a settled turn has no handoff.

    The real outcome is preserved and nothing is held solely for the latch.
    Already-applied latches are left alone so the hijacked marker survives.
    """
    from sase.agent.hijack import latch

    observed = observe_runner_latch(artifacts_dir, HIJACK_BOUNDARY_RUN_END)
    if str(observed.get("verdict") or "") != "pending":
        return observed
    target = _build_runner_target(artifacts_dir)
    if target is None:
        return observed
    return latch.moot_latch(
        str(observed.get("target_key") or ""),
        HIJACK_BOUNDARY_RUN_END,
        outcome,
        target=target,
    )


def check_retry_latch(artifacts_dir: str) -> dict[str, Any]:
    """Refuse retry progression once a latch has applied.

    Raises :class:`HijackLatchedError` for pending and applied latches so a
    spawned-retry failure surfaces as a latch refusal instead of falling back
    to an in-process retry. Returns the observation for all other verdicts.
    """
    observed = observe_runner_latch(artifacts_dir, HIJACK_BOUNDARY_RETRY)
    _raise_if_latched(observed, boundary=HIJACK_BOUNDARY_RETRY)
    return observed


def check_detached_delivery_latch(
    origin_artifacts_dir: str,
) -> dict[str, Any] | None:
    """Observe the origin latch before detached successor delivery.

    Returns the observation when a latch owns the origin (the caller must
    hold delivery without launching), else ``None``.
    """
    observed = observe_runner_latch(
        origin_artifacts_dir, HIJACK_BOUNDARY_DETACHED_DELIVERY
    )
    if str(observed.get("verdict") or "") in {"pending", "applied"}:
        return observed
    return None


__all__ = [
    "HIJACK_BOUNDARY_ADOPTION_REPLAY",
    "HIJACK_BOUNDARY_DETACHED_DELIVERY",
    "HIJACK_BOUNDARY_INPROCESS_SUCCESSOR",
    "HIJACK_BOUNDARY_RETRY",
    "HIJACK_BOUNDARY_RUN_END",
    "HIJACK_BOUNDARY_STAGED_ADOPTION",
    "check_detached_delivery_latch",
    "check_retry_latch",
    "enforce_adoption_replay_latch",
    "enforce_inprocess_successor_latch",
    "enforce_staged_adoption_latch",
    "is_hijack_suppressed_reason",
    "moot_runner_latch_at_run_end",
    "observe_runner_latch",
]
