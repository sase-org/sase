"""Fresh-interpreter owner facts and successor-custody proof.

Builds plain JSON-able owner/successor payloads without importing the
possibly-stale retention adapter or Rust binding, so a bounded fresh
interpreter can run the same Rust-backed settlement with recorded facts.

Successor proof requires a live matching receiver that already owns this
workspace and inherited its obligations. A delivery label or name is
historical evidence, not transfer.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

_NOT_A_REPO_MARKERS = ("not a git repository", "not a git repo")
_LIVE_DELIVERY_DISPOSITIONS = frozenset({"dispatching", "acknowledged", "settled"})


def monitor_owner_timestamp(artifacts_dir: str) -> str:
    """Return the monitor owner artifact timestamp.

    Settlement always uses the monitor artifacts directory name, never
    ``parent_timestamp``.
    """
    return os.path.basename(str(artifacts_dir or "").rstrip("/"))


def _classify_git_toplevel(path: str) -> tuple[str, str | None]:
    """Classify a git toplevel probe.

    Returns ``("repo", toplevel)``, ``("not_a_repo", None)``, or
    ``("failed", error)``. A successful "not a git repository" probe is
    absence of a work-tree, never operational uncertainty.
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
    except (OSError, subprocess.TimeoutExpired) as exc:
        return "failed", str(exc)
    except Exception as exc:  # noqa: BLE001 - evidence probes never block
        return "failed", str(exc)
    if result.returncode == 0 and result.stdout.strip():
        return "repo", result.stdout.strip()
    stderr = (result.stderr or "").strip().lower()
    if any(marker in stderr for marker in _NOT_A_REPO_MARKERS):
        return "not_a_repo", None
    detail = (result.stderr or result.stdout or "").strip() or (
        f"git rev-parse exited {result.returncode}"
    )
    return "failed", detail


def observe_checkout_dir(meta: dict[str, Any]) -> str | None:
    """Return the known workspace path even when a git preflight fails.

    A positively known plain non-repository directory is omitted so a
    repo-less command can release. An operational git failure or a missing
    owned path keeps the identity so dirt collection reports uncertainty.
    """
    for key in ("workspace_dir", "monitor_cwd"):
        candidate = meta.get(key)
        if not (isinstance(candidate, str) and candidate.strip()):
            continue
        if not os.path.isdir(candidate):
            return candidate
        kind, _detail = _classify_git_toplevel(candidate)
        if kind == "not_a_repo":
            continue
        return candidate
    return None


def collect_monitor_repo_observations(
    artifacts_dir: str,
    meta: dict[str, Any],
    checkout_dir: str | None,
) -> tuple[list[dict[str, Any]], list[str], str | None, tuple[str, ...]]:
    """Merge shared-discovery repos for monitor and starter evidence dirs.

    Starter evidence is folded in only when the starter ran in this same
    workspace (matching workspace number or checkout dir). A starter from a
    different workspace only contributes observations inside the monitor's
    own checkout, so terminal retention never probes the plan agent's
    former, possibly reused, workspace. Discovery exceptions become
    ``discovery_errors`` rather than silent omission of linked repositories.
    The known checkout identity is kept even when it is not a live directory.
    """
    starter = meta.get("monitor_starter_artifacts_dir")
    starter_dir = starter if isinstance(starter, str) and starter.strip() else None
    same_workspace = starter_same_workspace(meta, starter_dir, checkout_dir)
    by_path: dict[str, dict[str, Any]] = {}
    origin_ids: set[str] = set()
    discovery_errors: list[str] = []
    for evidence in (artifacts_dir, starter_dir):
        if not evidence:
            continue
        foreign = (
            starter_dir is not None and evidence == starter_dir and not same_workspace
        )
        repos, origins, error = _shared_repos(evidence, checkout_dir)
        if error and not foreign:
            discovery_errors.append(f"{evidence}: {error}")
        if foreign:
            repos, origins = _scope_foreign_starter_repos(repos, origins, checkout_dir)
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

        try:
            wanted = _norm(checkout_dir)
        except Exception:  # noqa: BLE001 - keep the raw identity
            wanted = checkout_dir
        existing_key = next(
            (k for k in by_path if _safe_norm(str(by_path[k]["path"])) == wanted),
            None,
        )
        if existing_key is not None:
            by_path[existing_key] = {
                **by_path[existing_key],
                "is_primary": True,
                "positive_custody": True,
            }
        else:
            by_path[checkout_dir] = {
                "repo_id": "primary",
                "path": checkout_dir,
                "is_primary": True,
                "positive_custody": True,
            }
            origin_ids.add("primary")
        for key in list(by_path):
            if key == (existing_key or checkout_dir):
                continue
            repo = by_path[key]
            if repo.get("is_primary") and _safe_norm(str(repo["path"])) != wanted:
                by_path[key] = {**repo, "is_primary": False}
    evidence_dir = (
        starter_dir
        if same_workspace and starter_dir and Path(starter_dir).is_dir()
        else artifacts_dir
    )
    ordered = sorted(
        by_path.values(), key=lambda r: (str(r["path"]), str(r["repo_id"]))
    )
    return ordered, sorted(origin_ids), evidence_dir, tuple(discovery_errors)


def starter_same_workspace(
    meta: dict[str, Any],
    starter_dir: str | None,
    checkout_dir: str | None,
) -> bool:
    """Return whether the starter evidence belongs to this workspace.

    The starter ran here when its recorded workspace number matches the
    monitor's, or when its recorded checkout matches the monitor's checkout.
    An unreadable starter identity keeps the legacy merge so evidence is
    never silently dropped for a workspace that cannot be told apart.
    """
    if not starter_dir:
        return True
    try:
        raw = Path(starter_dir, "agent_meta.json").read_text(encoding="utf-8")
    except OSError:
        return True
    try:
        import json as _json

        starter_meta = _json.loads(raw)
    except ValueError:
        return True
    if not isinstance(starter_meta, dict):
        return True
    if "workspace_num" not in starter_meta and not any(
        isinstance(starter_meta.get(key), str) and starter_meta.get(key)
        for key in ("workspace_dir", "monitor_cwd")
    ):
        return True
    monitor_num = meta.get("workspace_num")
    starter_num = starter_meta.get("workspace_num")
    if (
        isinstance(monitor_num, int)
        and not isinstance(monitor_num, bool)
        and isinstance(starter_num, int)
        and not isinstance(starter_num, bool)
        and monitor_num == starter_num
    ):
        return True
    if checkout_dir:
        wanted = _safe_norm(checkout_dir)
        for key in ("workspace_dir", "monitor_cwd"):
            candidate = starter_meta.get(key)
            if (
                isinstance(candidate, str)
                and candidate.strip()
                and _safe_norm(candidate) == wanted
            ):
                return True
    return False


def _scope_foreign_starter_repos(
    repos: list[dict[str, Any]],
    origins: set[str],
    checkout_dir: str | None,
) -> tuple[list[dict[str, Any]], set[str]]:
    """Keep only foreign-starter observations inside the monitor checkout.

    Baseline and opened-repo records from a different workspace usually name
    the starter's own checkout and its sibling sidecars. Those paths are
    dropped; a record that genuinely falls inside the monitor's checkout is
    kept without primary status.
    """
    if not checkout_dir:
        return [], set()
    wanted = _safe_norm(checkout_dir)
    kept: list[dict[str, Any]] = []
    kept_ids: set[str] = set()
    for repo in repos:
        path = str(repo.get("path") or "")
        if not path or not _is_within(path, wanted):
            continue
        repo_id = str(repo.get("repo_id") or "")
        kept_ids.add(repo_id)
        kept.append({**repo, "is_primary": False, "path": path})
    return kept, set(origins) & kept_ids


def _is_within(path: str, parent_norm: str) -> bool:
    """Return whether normalized *path* falls inside normalized *parent_norm*."""
    import os as _os

    candidate = _safe_norm(path)
    return candidate == parent_norm or candidate.startswith(parent_norm + _os.sep)


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
    artifacts_timestamp = monitor_owner_timestamp(artifacts_dir)
    if not artifacts_timestamp:
        return None
    checkout_dir = observe_checkout_dir(meta)
    repos, origin_ids, evidence_dir, discovery_errors = (
        collect_monitor_repo_observations(artifacts_dir, meta, checkout_dir)
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
        "origin_repo_ids": origin_ids,
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
        "discovery_errors": list(discovery_errors),
    }
    successor = _successor_payload(artifacts_dir, meta)
    return {"owner": owner, "successor": successor}


def has_transfer_proof(artifacts_dir: str, meta: dict[str, Any], agent: str) -> bool:
    """Require live successor custody, never a bare launch label.

    A ``dispatching``, ``acknowledged``, or ``settled`` delivery naming this
    agent is historical evidence. Proof also needs a live matching receiver
    process, a transferred claim on this workspace, and inherited repository
    custody. Missing, stale, mismatched, or unreadable evidence is not proof.
    """
    try:
        return _has_transfer_proof(artifacts_dir, meta, agent)
    except Exception:  # noqa: BLE001 - unreadable proof cannot authorize release
        return False


def _has_transfer_proof(artifacts_dir: str, meta: dict[str, Any], agent: str) -> bool:
    if not isinstance(agent, str) or not agent.strip():
        return False
    agent = agent.strip()
    monitor_id = meta.get("monitor_id")
    result_id = _monitor_result_id(meta)
    if not isinstance(monitor_id, str) or not monitor_id:
        return False
    from sase.monitor.delivery import load_delivery_records

    records = load_delivery_records(
        artifacts_dir,
        monitor_id=monitor_id,
        result_id=result_id,
    )
    matching: list[dict[str, Any]] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        if bool(record.get("workspace_degraded", False)):
            continue
        if str(record.get("disposition") or "") not in _LIVE_DELIVERY_DISPOSITIONS:
            continue
        key = record.get("key")
        if not isinstance(key, dict):
            continue
        if key.get("monitor_id") != monitor_id or key.get("result_id") != result_id:
            continue
        if _delivery_names_agent(record, agent):
            matching.append(record)
    if not matching:
        return False
    if not _receiver_is_live(artifacts_dir, meta, agent):
        return False
    if not _successor_owns_workspace_claim(artifacts_dir, meta):
        return False
    if not _successor_inherited_obligations(artifacts_dir, meta, agent, matching):
        return False
    return True


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


def _shared_repos(
    evidence_dir: str, checkout_dir: str | None
) -> tuple[list[dict[str, Any]], set[str], str | None]:
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
            None,
        )
    except Exception as exc:  # noqa: BLE001 - fall back, but record uncertainty
        fallback_repos, fallback_origins = _baseline_only_repos(
            evidence_dir, checkout_dir
        )
        return fallback_repos, fallback_origins, str(exc)


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


def _monitor_result_id(meta: dict[str, Any]) -> str:
    for key in ("continuation_monitor_result_id", "monitor_result_id"):
        value = meta.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return "result"


def _delivery_names_agent(record: dict[str, Any], agent: str) -> bool:
    from sase.monitor.resume_delivery_state import delivery_identity

    identity = delivery_identity(record)
    return identity == agent


def _receiver_is_live(artifacts_dir: str, meta: dict[str, Any], agent: str) -> bool:
    from sase.monitor.resume_adoption import receiver_is_live
    from sase.turns.settlement import project_name_from_artifacts_dir

    project_name = meta.get("project_name")
    if not isinstance(project_name, str) or not project_name.strip():
        project_name = project_name_from_artifacts_dir(artifacts_dir)
    if not isinstance(project_name, str) or not project_name.strip():
        return False
    return receiver_is_live(project_name, agent)


def _successor_owns_workspace_claim(artifacts_dir: str, meta: dict[str, Any]) -> bool:
    workspace_num = meta.get("workspace_num")
    origin_pid = meta.get("pid")
    origin_timestamp = monitor_owner_timestamp(artifacts_dir)
    if not isinstance(workspace_num, int) or not isinstance(origin_pid, int):
        return False
    if not origin_timestamp:
        return False
    project_file = _project_file_for_meta(artifacts_dir, meta)
    if not project_file:
        return False
    from sase.running_field import get_claimed_workspaces

    try:
        claims = get_claimed_workspaces(project_file)
    except OSError:
        return False
    origin_still_owns = False
    successor_owns = False
    for claim in claims:
        if claim.workspace_num != workspace_num:
            continue
        same_origin = (
            claim.pid == origin_pid
            and (claim.artifacts_timestamp or "") == origin_timestamp
        )
        if same_origin:
            origin_still_owns = True
        else:
            successor_owns = True
    return successor_owns and not origin_still_owns


def _successor_inherited_obligations(
    artifacts_dir: str,
    meta: dict[str, Any],
    agent: str,
    deliveries: list[dict[str, Any]],
) -> bool:
    workspace_num = meta.get("workspace_num")
    origin_pid = meta.get("pid")
    origin_timestamp = monitor_owner_timestamp(artifacts_dir)
    checkout = meta.get("workspace_dir") or meta.get("monitor_cwd")
    if isinstance(checkout, str) and checkout.strip():
        try:
            from sase.workspace_provider.occupant import read_occupant_record

            occupant = read_occupant_record(checkout)
        except Exception:  # noqa: BLE001 - occupant proof is best effort
            occupant = None
        if occupant is not None:
            different_owner = (
                occupant.pid != origin_pid
                or (occupant.artifacts_timestamp or "") != origin_timestamp
            )
            same_workspace = (
                not isinstance(workspace_num, int)
                or occupant.workspace_num == workspace_num
            )
            if different_owner and same_workspace:
                return True
    carried = meta.get("carried_repositories")
    if isinstance(carried, list):
        for record in carried:
            if not isinstance(record, dict):
                continue
            if record.get("carried_to") == agent:
                return True
    origin_identity = None
    if isinstance(checkout, str) and checkout.strip():
        origin_identity = checkout
    elif isinstance(workspace_num, int):
        origin_identity = str(workspace_num)
    for record in deliveries:
        identity = record.get("workspace_identity")
        if identity is None:
            continue
        if origin_identity is not None and str(identity) == str(origin_identity):
            return True
        if isinstance(workspace_num, int) and str(identity) == str(workspace_num):
            return True
    return _successor_owns_workspace_claim(artifacts_dir, meta)


def _project_file_for_meta(artifacts_dir: str, meta: dict[str, Any]) -> str | None:
    project_file = meta.get("project_file")
    if isinstance(project_file, str) and project_file:
        return project_file
    from sase.turns.settlement import project_name_from_artifacts_dir

    project_name = meta.get("project_name")
    if not isinstance(project_name, str) or not project_name.strip():
        project_name = project_name_from_artifacts_dir(artifacts_dir)
    if not isinstance(project_name, str) or not project_name.strip():
        return None
    try:
        from sase.workflows.utils import get_project_file_path

        return get_project_file_path(project_name)
    except Exception:  # noqa: BLE001 - project resolution is best effort
        return None


def _safe_norm(path: str) -> str:
    try:
        from sase.llm_provider.commit_finalizer_git import normalize_path as _norm

        return _norm(path)
    except Exception:  # noqa: BLE001 - keep the raw path
        return path


__all__ = [
    "collect_monitor_repo_observations",
    "fresh_owner_payload",
    "has_transfer_proof",
    "monitor_owner_timestamp",
    "observe_checkout_dir",
    "starter_same_workspace",
]
