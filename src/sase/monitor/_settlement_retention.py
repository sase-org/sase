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

    try:
        owner = _build_retention_owner(
            artifacts_dir, meta, project_name, project_file, workspace_num, pid
        )
    except (ImportError, AttributeError, TypeError) as exc:
        # Stale interpreter: the loaded adapter/binding or effect signature
        # is stale. Retry the same Rust-backed settlement in a bounded fresh
        # interpreter with the recorded owner facts; never retry spawn.
        return _settle_via_fresh_interpreter(
            artifacts_dir, meta, project_file, workspace_num, pid, exc
        )
    except Exception as exc:  # noqa: BLE001 - custody outranks discovery
        _pin_exact_claim_on_failure(project_file, workspace_num, meta, pid)
        return f"workspace retention settlement failed: {exc}"
    if owner is None:
        return (
            "workspace retention settlement failed: unresolved monitor owner; "
            "claim left untouched for guarded retry"
        )
    successor = _retention_successor_from_meta(artifacts_dir, meta)
    try:
        from sase.turns.workspace_retention import (
            clear_pending_retention,
            settle_stranded_workspace,
            write_pending_retention,
        )

        write_pending_retention(owner, "monitor_settlement")
        result = settle_stranded_workspace(owner, successor=successor)
        clear_pending_retention(artifacts_dir)
    except (ImportError, AttributeError, TypeError) as exc:
        return _settle_via_fresh_interpreter(
            artifacts_dir, meta, project_file, workspace_num, pid, exc
        )
    except Exception as exc:  # noqa: BLE001 - never drop a claim on error
        _pin_exact_claim_on_failure(project_file, workspace_num, meta, pid)
        try:
            from sase.turns.workspace_retention import write_pending_retention

            write_pending_retention(owner, f"settlement_failed: {exc}")
        except Exception:  # noqa: BLE001 - pending is best effort
            pass
        return f"workspace retention settlement failed: {exc}"
    if result.disposition == "release" and not result.claim_changed:
        return result.reason or "workspace release failed"
    return None


def _pin_exact_claim_on_failure(
    project_file: str, workspace_num: int, meta: dict[str, Any], pid: int
) -> None:
    """Pin the exact matching claim when settlement cannot complete."""
    try:
        from sase.running_field import hold_workspace_claim

        cl_name = meta.get("cl_name")
        artifacts_timestamp = meta.get("parent_timestamp")
        if not isinstance(artifacts_timestamp, str) or not artifacts_timestamp:
            import os

            artifacts_timestamp = os.path.basename(
                str(meta.get("artifacts_dir") or "").rstrip("/")
            )
        from sase.monitor.claims import MONITOR_WORKSPACE_CLAIM_WORKFLOW

        hold_workspace_claim(
            project_file,
            workspace_num,
            MONITOR_WORKSPACE_CLAIM_WORKFLOW,
            cl_name if isinstance(cl_name, str) else "",
            artifacts_timestamp if isinstance(artifacts_timestamp, str) else "",
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

    try:
        from sase.turns.workspace_retention import write_pending_retention

        from .settlement_fresh_owner import fresh_owner_payload
    except Exception:  # noqa: BLE001 - pending is best effort
        return f"workspace retention settlement failed: stale binding ({exc})"
    try:
        payload = fresh_owner_payload(
            artifacts_dir, meta, project_file, workspace_num, pid
        )
    except Exception as inner:  # noqa: BLE001 - owner facts unavailable
        return f"workspace retention settlement failed: stale binding ({exc}; {inner})"
    if payload is None:
        return f"workspace retention settlement failed: stale binding ({exc})"
    try:
        owner_repr = _json.dumps(payload["owner"])
        successor_repr = _json.dumps(payload["successor"])
    except (TypeError, ValueError) as inner:
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
        "notify_on_retain=bool(o.get('notify_on_retain',False)));"
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
        _pin_exact_claim_on_failure(project_file, workspace_num, meta, pid)
        return f"workspace retention settlement failed: stale binding ({exc}; {inner})"
    if proc.returncode != 0:
        _pin_exact_claim_on_failure(project_file, workspace_num, meta, pid)
        detail = (proc.stderr or proc.stdout or "").strip()[-500:]
        return f"workspace retention settlement failed: stale binding ({exc}; {detail})"
    try:
        outcome = _json.loads((proc.stdout or "").strip().splitlines()[-1])
    except (IndexError, ValueError) as inner:
        _pin_exact_claim_on_failure(project_file, workspace_num, meta, pid)
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
    import os

    from sase.turns.workspace_retention import (
        WorkspaceRetentionOwner,
        discover_workspace_retention_repos,
    )

    from .staged_owner import read_staged_owner_index

    cl_name = meta.get("cl_name")
    artifacts_timestamp = os.path.basename(artifacts_dir.rstrip("/"))
    checkout_dir = _retention_checkout_dir(meta)
    repos, origin_ids, evidence_dir = _monitor_retention_repos(
        artifacts_dir, meta, checkout_dir, discover_workspace_retention_repos
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
        )
    except Exception:  # noqa: BLE001 - malformed metadata falls back
        return None


def _monitor_retention_repos(
    artifacts_dir: str,
    meta: dict[str, Any],
    checkout_dir: str | None,
    discover: Any,
) -> tuple[tuple[Any, ...], tuple[str, ...], str | None]:
    """Merge shared-discovery repos for monitor and starter evidence."""
    from pathlib import Path

    starter = meta.get("monitor_starter_artifacts_dir")
    starter_dir = starter if isinstance(starter, str) and starter.strip() else None
    by_path: dict[str, Any] = {}
    origin_ids: set[str] = set()
    for evidence in (artifacts_dir, starter_dir):
        if not evidence:
            continue
        try:
            repos, origins = discover(evidence, checkout_dir)
        except Exception:  # noqa: BLE001 - discovery never blocks settlement
            continue
        origin_ids.update(origins)
        for repo in repos:
            key = str(getattr(repo, "path", ""))
            prior = by_path.get(key)
            if prior is None:
                by_path[key] = repo
            else:
                from sase.turns.workspace_retention import WorkspaceRetentionRepo

                by_path[key] = WorkspaceRetentionRepo(
                    repo_id=getattr(prior, "repo_id", ""),
                    path=getattr(prior, "path", ""),
                    is_primary=bool(
                        getattr(prior, "is_primary", False)
                        or getattr(repo, "is_primary", False)
                    ),
                    positive_custody=bool(
                        getattr(prior, "positive_custody", False)
                        or getattr(repo, "positive_custody", False)
                    ),
                )
    if checkout_dir:
        from sase.llm_provider.commit_finalizer_git import normalize_path
        from sase.turns.workspace_retention import WorkspaceRetentionRepo

        wanted = normalize_path(checkout_dir)
        match_key: str | None = None
        for key, repo in by_path.items():
            try:
                if normalize_path(str(getattr(repo, "path", ""))) == wanted:
                    match_key = key
                    break
            except Exception:  # noqa: BLE001 - path normalization is best effort
                continue
        if match_key is not None:
            current = by_path[match_key]
            by_path[match_key] = WorkspaceRetentionRepo(
                repo_id=getattr(current, "repo_id", "primary"),
                path=getattr(current, "path", checkout_dir),
                is_primary=True,
                positive_custody=True,
            )
        elif Path(checkout_dir).is_dir():
            by_path[checkout_dir] = WorkspaceRetentionRepo(
                repo_id="primary",
                path=checkout_dir,
                is_primary=True,
                positive_custody=True,
            )
            origin_ids.add("primary")
    ordered = tuple(
        sorted(by_path.values(), key=lambda r: (str(r.path), str(r.repo_id)))
    )
    evidence_dir = (
        starter_dir if starter_dir and Path(starter_dir).is_dir() else artifacts_dir
    )
    return ordered, tuple(sorted(origin_ids)), evidence_dir


def _monitor_claim_workflow() -> str:
    from sase.monitor.claims import MONITOR_WORKSPACE_CLAIM_WORKFLOW

    return MONITOR_WORKSPACE_CLAIM_WORKFLOW


def _retention_checkout_dir(meta: dict[str, Any]) -> str | None:
    """Return the workspace checkout the settling monitor ran in.

    Only an existing git-backed directory can carry retainable worktree
    evidence; a missing checkout (reboot-lost records, removed lanes) or a
    plain non-repo directory contributes no dirt and must not turn into a
    probe failure. The adapter probes ``checkout_dir`` when no explicit
    repos survive discovery, so this gate decides release-vs-retain for
    repo-less monitors.
    """
    import os

    for key in ("workspace_dir", "monitor_cwd"):
        candidate = meta.get(key)
        if (
            isinstance(candidate, str)
            and candidate.strip()
            and os.path.isdir(candidate)
            and _retention_git_toplevel(candidate) is not None
        ):
            return candidate
    return None


def _retention_git_toplevel(path: str) -> str | None:
    """Return the enclosing git work-tree root for *path*, if any.

    A directory outside any git repository cannot carry session-owned
    uncommitted work in the sense the retention policy protects, so it
    contributes no dirt evidence instead of a probe failure.
    """
    import subprocess

    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=path,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
            check=False,
        )
    except Exception:  # noqa: BLE001 - evidence probes never block settlement
        return None
    if result.returncode != 0:
        return None
    root = result.stdout.strip()
    return root or None


def _retention_successor_from_meta(artifacts_dir: str, meta: dict[str, Any]) -> Any:
    """Derive successor custody from delivery proofs, never a bare label.

    A recorded outcome, agent name, or historical ``carried_to`` is not
    proof. A real transferred claim needs a non-degraded delivery record
    naming the follow-up agent as the acknowledged or reserved receiver;
    a dirty original with only an old launch label retains. Degraded
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
