"""Guarded workspace claim retention for settled monitor members."""

from __future__ import annotations

from typing import Any

from .models import MONITOR_FOLLOWUP_DEGRADED_OUTCOME


def release_monitor_claim(
    meta: dict[str, Any],
    *,
    project_name: str | None,
    artifacts_dir: str,
) -> str | None:
    """Settle this monitor member's workspace claim through guarded retention.

    Routes every terminal monitor claim disposal — stopped/lost states,
    no-follow-up outcomes, launch failures, blocked continuation capture,
    frozen-policy branches, and degraded follow-ups — through
    :func:`sase.turns.workspace_retention.settle_stranded_workspace`. A
    confirmed same-workspace successor keeps custody (no hold); a degraded
    follow-up in another checkout retains the original dirty workspace; a
    missing or moved claim is a no-op. Returns ``None`` when settlement
    succeeded (retained, released, or stale); returns an error string only
    when settlement itself fails before custody is protected.

    Owner discovery, Rust classification, snapshot/claim effects, and
    metadata writes share one failure boundary: any failure pins the exact
    matching claim through the guarded claim API and persists terminal
    evidence instead of releasing a potentially replaced claim. Unresolved
    owner metadata never authorizes a legacy ownership-blind release.
    """
    workspace_num = meta.get("workspace_num")
    if not project_name or not isinstance(workspace_num, int):
        return None
    try:
        from sase.workflows.utils import get_project_file_path

        project_file = get_project_file_path(project_name)
    except Exception:
        return None

    pid = meta.get("pid")
    if not isinstance(pid, int):
        return (
            "workspace retention settlement failed: unresolved monitor owner "
            "(missing pid); claim left untouched for guarded retry"
        )

    pending_ok = _bootstrap_pending_retention(
        artifacts_dir, meta, workspace_num, pid, "monitor_settlement"
    )
    if not pending_ok:
        _pin_exact_claim_on_failure(
            project_file, workspace_num, meta, pid, artifacts_dir
        )

    try:
        owner = _build_retention_owner(
            artifacts_dir, meta, project_name, project_file, workspace_num, pid
        )
        successor = _retention_successor_from_meta(artifacts_dir, meta)
    except (ImportError, AttributeError, TypeError) as exc:
        # Stale interpreter: the loaded adapter/binding or effect signature
        # is stale. Retry the same Rust-backed settlement in a bounded fresh
        # interpreter with the recorded owner facts; never retry spawn.
        return _settle_via_fresh_interpreter(
            artifacts_dir, meta, project_file, workspace_num, pid, exc
        )
    except Exception as exc:  # noqa: BLE001 - custody outranks discovery
        _pin_exact_claim_on_failure(
            project_file, workspace_num, meta, pid, artifacts_dir
        )
        return f"workspace retention settlement failed: {exc}"
    if owner is None:
        _pin_exact_claim_on_failure(
            project_file, workspace_num, meta, pid, artifacts_dir
        )
        return (
            "workspace retention settlement failed: unresolved monitor owner; "
            "claim left untouched for guarded retry"
        )
    try:
        from sase.turns.workspace_retention import (
            clear_pending_retention,
            settle_stranded_workspace,
        )

        result = settle_stranded_workspace(owner, successor=successor)
        clear_pending_retention(artifacts_dir)
    except (ImportError, AttributeError, TypeError) as exc:
        return _settle_via_fresh_interpreter(
            artifacts_dir, meta, project_file, workspace_num, pid, exc
        )
    except Exception as exc:  # noqa: BLE001 - never drop a claim on error
        _pin_exact_claim_on_failure(
            project_file, workspace_num, meta, pid, artifacts_dir
        )
        _bootstrap_pending_retention(
            artifacts_dir, meta, workspace_num, pid, f"settlement_failed: {exc}"
        )
        return f"workspace retention settlement failed: {exc}"
    if result.disposition == "release" and not result.claim_changed:
        return result.reason or "workspace release failed"
    return None


def _bootstrap_pending_retention(
    artifacts_dir: str,
    meta: dict[str, Any],
    workspace_num: int,
    pid: int,
    reason: str,
) -> bool:
    """Persist exact-owner pending evidence without importing the adapter."""
    from sase.turns.workspace_retention_pending import write_pending_retention_identity

    from .settlement_fresh_owner import monitor_owner_timestamp

    timestamp = monitor_owner_timestamp(artifacts_dir)
    cl_name = meta.get("cl_name")
    terminal_reason = meta.get("monitor_state")
    try:
        path = write_pending_retention_identity(
            artifacts_dir,
            workspace_num=workspace_num,
            workflow=_monitor_claim_workflow(),
            cl_name=cl_name if isinstance(cl_name, str) else "",
            artifacts_timestamp=timestamp,
            pid=pid,
            reason=reason,
            terminal_reason=terminal_reason
            if isinstance(terminal_reason, str) and terminal_reason
            else "terminal",
        )
    except Exception:  # noqa: BLE001 - pending is best effort
        return False
    return path is not None


def _pin_exact_claim_on_failure(
    project_file: str,
    workspace_num: int,
    meta: dict[str, Any],
    pid: int,
    artifacts_dir: str,
) -> None:
    """Pin the exact matching claim when settlement cannot complete.

    The owner timestamp comes from the monitor artifacts directory, never
    ``parent_timestamp``. Incomplete identity is left untouched rather than
    pinning another owner with an empty wildcard.
    """
    from .settlement_fresh_owner import monitor_owner_timestamp

    timestamp = monitor_owner_timestamp(artifacts_dir)
    cl_name = meta.get("cl_name")
    if not timestamp or not isinstance(pid, int) or not isinstance(workspace_num, int):
        return
    try:
        from sase.monitor.claims import MONITOR_WORKSPACE_CLAIM_WORKFLOW
        from sase.running_field import hold_workspace_claim

        hold_workspace_claim(
            project_file,
            workspace_num,
            MONITOR_WORKSPACE_CLAIM_WORKFLOW,
            cl_name if isinstance(cl_name, str) else "",
            timestamp,
            caller_tag="workspace-retention-failure",
            expected_pid=pid,
        )
    except Exception:  # noqa: BLE001 - pinning is best effort
        return


def _settle_via_fresh_interpreter(
    artifacts_dir: str,
    meta: dict[str, Any],
    project_file: str,
    workspace_num: int,
    pid: int,
    exc: BaseException,
) -> str | None:
    """Retry Rust-backed settlement in a bounded fresh interpreter.

    Records a durable pending-retention fact before the attempt so stale
    cleanup honors the exact owner until a guarded decision completes. Never
    retries follow-up spawn or the monitored command. An unavailable fresh
    binding leaves visible, retryable protected custody.
    """
    import json as _json
    import subprocess as _subprocess
    import sys as _sys

    _bootstrap_pending_retention(
        artifacts_dir, meta, workspace_num, pid, "fresh_interpreter_retry"
    )
    try:
        from .settlement_fresh_owner import fresh_owner_payload
    except Exception as inner:  # noqa: BLE001 - payload helper unavailable
        _pin_exact_claim_on_failure(
            project_file, workspace_num, meta, pid, artifacts_dir
        )
        return f"workspace retention settlement failed: stale binding ({exc}; {inner})"
    try:
        payload = fresh_owner_payload(
            artifacts_dir, meta, project_file, workspace_num, pid
        )
    except Exception as inner:  # noqa: BLE001 - owner facts unavailable
        _pin_exact_claim_on_failure(
            project_file, workspace_num, meta, pid, artifacts_dir
        )
        return f"workspace retention settlement failed: stale binding ({exc}; {inner})"
    if payload is None:
        _pin_exact_claim_on_failure(
            project_file, workspace_num, meta, pid, artifacts_dir
        )
        return f"workspace retention settlement failed: stale binding ({exc})"
    try:
        owner_repr = _json.dumps(payload["owner"])
        successor_repr = _json.dumps(payload["successor"])
    except (TypeError, ValueError) as inner:
        _pin_exact_claim_on_failure(
            project_file, workspace_num, meta, pid, artifacts_dir
        )
        return f"workspace retention settlement failed: stale binding ({exc}; {inner})"
    code = (
        "import json,sys;"
        "from sase.turns.workspace_retention import "
        "WorkspaceRetentionOwner,WorkspaceRetentionRepo,WorkspaceRetentionSuccessor,"
        "settle_stranded_workspace,write_pending_retention,clear_pending_retention;"
        "o=json.loads(sys.argv[1]);s=json.loads(sys.argv[2]);"
        "owner=WorkspaceRetentionOwner(project_file=o['project_file'],"
        "workspace_num=o['workspace_num'],workflow=o['workflow'],"
        "cl_name=o['cl_name'],artifacts_timestamp=o['artifacts_timestamp'],"
        "pid=o['pid'],artifacts_dir=o['artifacts_dir'],"
        "checkout_dir=o.get('checkout_dir'),"
        "repos=tuple(WorkspaceRetentionRepo(**r) for r in o.get('repos',[])),"
        "origin_repo_ids=tuple(o.get('origin_repo_ids',())),"
        "staged_id=o.get('staged_id'),session_id=o.get('session_id'),"
        "turn_id=o.get('turn_id'),terminal_reason=o.get('terminal_reason',''),"
        "evidence_artifacts_dir=o.get('evidence_artifacts_dir'),"
        "notify_on_retain=bool(o.get('notify_on_retain',False)),"
        "discovery_errors=tuple(o.get('discovery_errors',())));"
        "succ=WorkspaceRetentionSuccessor(confirmed_active=s.get('confirmed_active',False),"
        "same_workspace=s.get('same_workspace',False),"
        "inherited_obligations=s.get('inherited_obligations',False));"
        "write_pending_retention(owner,'fresh_interpreter_retry');"
        "r=settle_stranded_workspace(owner,successor=succ);"
        "clear_pending_retention(owner.artifacts_dir);"
        "print(json.dumps({'disposition':r.disposition,'reason':r.reason,"
        "'claim_changed':r.claim_changed}))"
    )
    try:
        proc = _subprocess.run(
            [_sys.executable, "-c", code, owner_repr, successor_repr],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except Exception as inner:  # noqa: BLE001 - fresh attempt unavailable
        _pin_exact_claim_on_failure(
            project_file, workspace_num, meta, pid, artifacts_dir
        )
        return f"workspace retention settlement failed: stale binding ({exc}; {inner})"
    if proc.returncode != 0:
        _pin_exact_claim_on_failure(
            project_file, workspace_num, meta, pid, artifacts_dir
        )
        detail = (proc.stderr or proc.stdout or "").strip()[-500:]
        return f"workspace retention settlement failed: stale binding ({exc}; {detail})"
    try:
        outcome = _json.loads((proc.stdout or "").strip().splitlines()[-1])
    except (IndexError, ValueError) as inner:
        _pin_exact_claim_on_failure(
            project_file, workspace_num, meta, pid, artifacts_dir
        )
        return f"workspace retention settlement failed: stale binding ({exc}; {inner})"
    if outcome.get("disposition") == "release" and not outcome.get("claim_changed"):
        return str(outcome.get("reason") or "workspace release failed")
    return None


def _build_retention_owner(
    artifacts_dir: str,
    meta: dict[str, Any],
    project_name: str,
    project_file: str,
    workspace_num: int,
    pid: int,
) -> Any | None:
    """Build a concrete retention owner from monitor metadata.

    Repository evidence comes from the shared discovery adapter over both
    the monitor member's evidence dir and the starter's evidence dir, so
    real repo IDs, opened-repo markers, and the starter baseline path are
    preserved. There is no eight-repository cutoff: a bounded probe that
    fails yields uncertainty for that known repo instead of disappearing.
    ``evidence_artifacts_dir`` points at the starter evidence when present
    so dirt is compared against the starter baseline, not the monitor
    member's own baseline.
    """
    from sase.turns.workspace_retention import (
        WorkspaceRetentionOwner,
        WorkspaceRetentionRepo,
    )

    from .settlement_fresh_owner import (
        collect_monitor_repo_observations,
        monitor_owner_timestamp,
        observe_checkout_dir,
    )
    from .staged_owner import read_staged_owner_index

    cl_name = meta.get("cl_name")
    artifacts_timestamp = monitor_owner_timestamp(artifacts_dir)
    if not artifacts_timestamp:
        return None
    checkout_dir = observe_checkout_dir(meta)
    repo_dicts, origin_ids, evidence_dir, discovery_errors = (
        collect_monitor_repo_observations(artifacts_dir, meta, checkout_dir)
    )
    repos = tuple(
        WorkspaceRetentionRepo(
            repo_id=str(item.get("repo_id") or ""),
            path=str(item.get("path") or ""),
            is_primary=bool(item.get("is_primary")),
            positive_custody=bool(item.get("positive_custody")),
        )
        for item in repo_dicts
        if item.get("path")
    )
    monitor_id = meta.get("monitor_id")
    staged_id = meta.get("monitor_staged_id")
    if not isinstance(staged_id, str) or not staged_id:
        staged_id = None
        if isinstance(monitor_id, str) and monitor_id:
            try:
                staged = read_staged_owner_index(monitor_id)
            except Exception:  # noqa: BLE001 - staged index is best effort
                staged = None
            if isinstance(staged, dict):
                candidate = staged.get("staged_id")
                if isinstance(candidate, str) and candidate:
                    staged_id = candidate
    session_id = meta.get("agent_session")
    if not isinstance(session_id, str) or not session_id:
        session_id = None
    turn_id = monitor_id if isinstance(monitor_id, str) and monitor_id else None
    terminal_reason = meta.get("monitor_state")
    if not isinstance(terminal_reason, str) or not terminal_reason:
        terminal_reason = "terminal"
    try:
        return WorkspaceRetentionOwner(
            project_file=project_file,
            workspace_num=workspace_num,
            workflow=_monitor_claim_workflow(),
            cl_name=cl_name if isinstance(cl_name, str) else "",
            artifacts_timestamp=artifacts_timestamp,
            pid=pid,
            artifacts_dir=artifacts_dir,
            checkout_dir=checkout_dir,
            repos=repos,
            origin_repo_ids=tuple(origin_ids),
            staged_id=staged_id,
            session_id=session_id,
            turn_id=turn_id,
            terminal_reason=terminal_reason,
            evidence_artifacts_dir=evidence_dir,
            notify_on_retain=True,
            discovery_errors=discovery_errors,
        )
    except Exception:  # noqa: BLE001 - malformed metadata falls back
        return None


def _monitor_claim_workflow() -> str:
    from sase.monitor.claims import MONITOR_WORKSPACE_CLAIM_WORKFLOW

    return MONITOR_WORKSPACE_CLAIM_WORKFLOW


def _retention_successor_from_meta(artifacts_dir: str, meta: dict[str, Any]) -> Any:
    """Derive successor custody from live transfer proof, never a bare label.

    A recorded outcome, agent name, or historical ``carried_to`` is not
    proof. A real transferred claim needs a live matching receiver that
    already owns this workspace and inherited its obligations. Degraded
    follow-ups keep the original dirty workspace.
    """
    from sase.turns.workspace_retention import WorkspaceRetentionSuccessor

    from .settlement_fresh_owner import has_transfer_proof as _has_proof

    outcome = meta.get("monitor_followup_outcome")
    if outcome == MONITOR_FOLLOWUP_DEGRADED_OUTCOME:
        degraded = meta.get("monitor_followup_degraded_reason")
        if isinstance(degraded, str) and degraded.strip():
            return WorkspaceRetentionSuccessor(
                confirmed_active=True,
                same_workspace=False,
                inherited_obligations=True,
            )
        return WorkspaceRetentionSuccessor()
    if outcome == "launched":
        agent = meta.get("monitor_followup_agent")
        if (
            isinstance(agent, str)
            and agent.strip()
            and _has_proof(artifacts_dir, meta, agent.strip())
        ):
            return WorkspaceRetentionSuccessor(
                confirmed_active=True,
                same_workspace=True,
                inherited_obligations=True,
            )
    return WorkspaceRetentionSuccessor()
