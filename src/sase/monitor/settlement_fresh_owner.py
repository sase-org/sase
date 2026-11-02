"""Fresh-interpreter owner facts for stale-binding retention retry.

Builds plain JSON-able owner/successor payloads without importing the
possibly-stale retention adapter or Rust binding, so a bounded fresh
interpreter can run the same Rust-backed settlement with recorded facts.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any


def fresh_owner_payload(
    artifacts_dir: str,
    meta: dict[str, Any],
    project_file: str,
    workspace_num: int,
    pid: int,
) -> dict[str, Any] | None:
    """Return JSON-able owner/successor facts for a fresh interpreter."""
    try:
        from sase.monitor.claims import MONITOR_WORKSPACE_CLAIM_WORKFLOW
    except Exception:  # noqa: BLE001 - workflow label has a stable fallback
        MONITOR_WORKSPACE_CLAIM_WORKFLOW = "ace-monitor"  # type: ignore[no-redef]
    cl_name = meta.get("cl_name")
    artifacts_timestamp = os.path.basename(artifacts_dir.rstrip("/"))
    checkout_dir = _checkout_dir(meta)
    repos, origin_ids, evidence_dir = _repos_and_evidence(
        artifacts_dir, meta, checkout_dir
    )
    monitor_id = meta.get("monitor_id")
    staged_id = meta.get("monitor_staged_id")
    if (not isinstance(staged_id, str) or not staged_id) and isinstance(
        monitor_id, str
    ):
        staged_id = _staged_id_for_monitor(monitor_id)
    session_id = meta.get("agent_session")
    terminal_reason = meta.get("monitor_state")
    owner = {
        "project_file": project_file,
        "workspace_num": workspace_num,
        "workflow": MONITOR_WORKSPACE_CLAIM_WORKFLOW,
        "cl_name": cl_name if isinstance(cl_name, str) else "",
        "artifacts_timestamp": artifacts_timestamp,
        "pid": pid,
        "artifacts_dir": artifacts_dir,
        "checkout_dir": checkout_dir,
        "repos": repos,
        "origin_repo_ids": sorted(origin_ids),
        "staged_id": staged_id if isinstance(staged_id, str) and staged_id else None,
        "session_id": session_id
        if isinstance(session_id, str) and session_id
        else None,
        "turn_id": monitor_id if isinstance(monitor_id, str) and monitor_id else None,
        "terminal_reason": terminal_reason
        if isinstance(terminal_reason, str) and terminal_reason
        else "terminal",
        "evidence_artifacts_dir": evidence_dir,
        "notify_on_retain": True,
    }
    successor = _successor_payload(artifacts_dir, meta)
    return {"owner": owner, "successor": successor}


def _checkout_dir(meta: dict[str, Any]) -> str | None:
    import subprocess

    for key in ("workspace_dir", "monitor_cwd"):
        candidate = meta.get(key)
        if not (isinstance(candidate, str) and candidate.strip()):
            continue
        if not os.path.isdir(candidate):
            continue
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--show-toplevel"],
                cwd=candidate,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=10,
                check=False,
            )
        except Exception:  # noqa: BLE001 - evidence probes never block
            continue
        if result.returncode == 0 and result.stdout.strip():
            return candidate
    return None


def _repos_and_evidence(
    artifacts_dir: str, meta: dict[str, Any], checkout_dir: str | None
) -> tuple[list[dict[str, Any]], set[str], str | None]:
    """Merge shared-discovery repos for monitor and starter evidence dirs."""
    starter = meta.get("monitor_starter_artifacts_dir")
    starter_dir = starter if isinstance(starter, str) and starter.strip() else None
    by_path: dict[str, dict[str, Any]] = {}
    origin_ids: set[str] = set()
    for evidence in (artifacts_dir, starter_dir):
        if not evidence:
            continue
        repos, origins = _shared_repos(evidence, checkout_dir)
        origin_ids.update(origins)
        for repo in repos:
            key = str(repo["path"])
            prior = by_path.get(key)
            if prior is None:
                by_path[key] = repo
            else:
                by_path[key] = {
                    "repo_id": prior["repo_id"],
                    "path": prior["path"],
                    "is_primary": bool(
                        prior.get("is_primary") or repo.get("is_primary")
                    ),
                    "positive_custody": bool(
                        prior.get("positive_custody") or repo.get("positive_custody")
                    ),
                }
    if checkout_dir:
        from sase.llm_provider.commit_finalizer_git import normalize_path as _norm

        key = _norm(checkout_dir)
        existing_key = next(
            (k for k in by_path if _norm(str(by_path[k]["path"])) == key), None
        )
        if existing_key is not None:
            by_path[existing_key] = {
                **by_path[existing_key],
                "is_primary": True,
                "positive_custody": True,
            }
        elif Path(checkout_dir).is_dir():
            by_path[checkout_dir] = {
                "repo_id": "primary",
                "path": checkout_dir,
                "is_primary": True,
                "positive_custody": True,
            }
            origin_ids.add("primary")
    evidence_dir = (
        starter_dir if starter_dir and Path(starter_dir).is_dir() else artifacts_dir
    )
    ordered = sorted(
        by_path.values(), key=lambda r: (str(r["path"]), str(r["repo_id"]))
    )
    return ordered, origin_ids, evidence_dir


def _shared_repos(
    evidence_dir: str, checkout_dir: str | None
) -> tuple[list[dict[str, Any]], set[str]]:
    try:
        from sase.turns.workspace_retention import (
            discover_workspace_retention_repos as _discover,
        )

        repos, origins = _discover(evidence_dir, checkout_dir)
        return (
            [
                {
                    "repo_id": r.repo_id,
                    "path": r.path,
                    "is_primary": bool(r.is_primary),
                    "positive_custody": bool(r.positive_custody),
                }
                for r in repos
            ],
            set(origins),
        )
    except Exception:  # noqa: BLE001 - fall back to baseline-only discovery
        return _baseline_only_repos(evidence_dir, checkout_dir)


def _baseline_only_repos(
    evidence_dir: str, checkout_dir: str | None
) -> tuple[list[dict[str, Any]], set[str]]:
    repos: list[dict[str, Any]] = []
    origin_ids: set[str] = set()
    try:
        from sase.llm_provider.commit_finalizer_baseline import (
            load_finalizer_baseline_records as _load,
        )
        from sase.llm_provider.commit_finalizer_git import normalize_path as _norm

        records = _load(Path(evidence_dir)) or ()
        for record in records:
            path = getattr(record, "path", None)
            repo_id = getattr(record, "repo_id", None)
            if not isinstance(path, str) or not path.strip():
                continue
            rid = repo_id if isinstance(repo_id, str) and repo_id else "primary"
            origin_ids.add(rid)
            repos.append(
                {
                    "repo_id": rid,
                    "path": path,
                    "is_primary": _norm(path) == _norm(checkout_dir)
                    if checkout_dir
                    else False,
                    "positive_custody": True,
                }
            )
    except Exception:  # noqa: BLE001 - baseline discovery is best effort
        pass
    return repos, origin_ids


def _staged_id_for_monitor(monitor_id: str) -> str | None:
    try:
        from sase.monitor.staged_owner import read_staged_owner_index

        staged = read_staged_owner_index(monitor_id)
    except Exception:  # noqa: BLE001 - staged index is best effort
        return None
    if isinstance(staged, dict):
        candidate = staged.get("staged_id")
        if isinstance(candidate, str) and candidate:
            return candidate
    return None


def _successor_payload(artifacts_dir: str, meta: dict[str, Any]) -> dict[str, bool]:
    from sase.monitor.models import MONITOR_FOLLOWUP_DEGRADED_OUTCOME

    outcome = meta.get("monitor_followup_outcome")
    if outcome == MONITOR_FOLLOWUP_DEGRADED_OUTCOME:
        degraded = meta.get("monitor_followup_degraded_reason")
        if isinstance(degraded, str) and degraded.strip():
            return {
                "confirmed_active": True,
                "same_workspace": False,
                "inherited_obligations": True,
            }
        return {
            "confirmed_active": False,
            "same_workspace": False,
            "inherited_obligations": False,
        }
    if outcome == "launched":
        agent = meta.get("monitor_followup_agent")
        if (
            isinstance(agent, str)
            and agent.strip()
            and has_transfer_proof(artifacts_dir, meta, agent.strip())
        ):
            return {
                "confirmed_active": True,
                "same_workspace": True,
                "inherited_obligations": True,
            }
    return {
        "confirmed_active": False,
        "same_workspace": False,
        "inherited_obligations": False,
    }


def has_transfer_proof(artifacts_dir: str, meta: dict[str, Any], agent: str) -> bool:
    """Require delivery proof, never a bare launch label.

    A recorded name or outcome alone is not proof: the delivery store must
    name this agent as the acknowledged or reserved receiver in a
    non-degraded dispatching/acknowledged/settled record. Process liveness
    is checked by the resume-adoption proofs; settlement here reuses the
    durable delivery facts so a stale launch label with a still-owned dirty
    original claim retains.
    """
    try:
        from sase.monitor.delivery import load_delivery_records

        monitor_id = meta.get("monitor_id")
        records = load_delivery_records(
            artifacts_dir,
            monitor_id=monitor_id if isinstance(monitor_id, str) else None,
        )
        for record in records:
            if not isinstance(record, dict):
                continue
            if bool(record.get("workspace_degraded", False)):
                continue
            if str(record.get("disposition") or "") not in {
                "dispatching",
                "acknowledged",
                "settled",
            }:
                continue
            for key in ("acknowledged_by", "reserved_identity"):
                value = record.get(key)
                if isinstance(value, str) and value.strip() == agent:
                    return True
    except Exception:  # noqa: BLE001 - delivery proof is best effort
        pass
    return False


__all__ = ["fresh_owner_payload", "has_transfer_proof"]
