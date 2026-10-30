"""Carried-repository custody records for staged-handoff adoption."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from sase.agent.staged_handoff import StagedHandoffError
from sase.axe._run_agent_exec_staged_shared import (
    proven_ids_for_settlement,
    read_json_object,
)

#: Agent-meta key holding carried-repository custody records. Each record is
#: ``{"repo_id": str, "digest": str, "staged_id": str, "origin_run": str,
#: "carried_to": str | None}``. ``carried_to`` is ``None`` while the origin
#: retains custody and holds the actual successor identity after adoption.
CARRIED_CUSTODY_META_KEY = "carried_repositories"


def _origin_run_id(run_metadata: Mapping[str, Any], artifacts_dir: str) -> str:
    summary = run_metadata.get("finalizer_status")
    if isinstance(summary, Mapping):
        run_id = summary.get("run_id")
        if isinstance(run_id, str) and run_id:
            return run_id
    name = run_metadata.get("name")
    if isinstance(name, str) and name:
        return name
    return Path(artifacts_dir).name


def _collect_carried_custody_records(
    staged_record: Mapping[str, Any],
    *,
    result_payload: Mapping[str, Any],
    current_context: Any,
    origin_run: str,
) -> list[dict[str, Any]]:
    """Build custody records for every proven carried/prepared repository."""
    staged_id = staged_record.get("staged_id")
    if not isinstance(staged_id, str) or not staged_id:
        return []
    try:
        proven = proven_ids_for_settlement(result_payload, current_context, staged_id)
    except Exception:
        return []
    digest_by_id = {
        obligation.obligation_id: obligation.digest or ""
        for obligation in getattr(current_context, "obligations", ())
        if getattr(obligation, "kind", "") == "repository"
    }
    return [
        {
            "repo_id": repo_id,
            "digest": digest_by_id.get(repo_id, ""),
            "staged_id": staged_id,
            "origin_run": origin_run,
            "carried_to": None,
        }
        for repo_id in sorted(proven)
    ]


def persist_origin_custody(
    staged_record: Mapping[str, Any],
    *,
    artifacts_dir: str,
    run_metadata: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Persist origin custody records for proven carry/prepared coverage."""
    from sase.axe.run_agent_helpers_artifacts import update_meta_fields

    root = Path(artifacts_dir)
    try:
        result_payload = read_json_object(
            root / "finalizer_result.json", label="finalizer result"
        )
    except StagedHandoffError:
        return []
    from sase.finalizers.declaration import load_latest_finalizer_context

    try:
        current_context = load_latest_finalizer_context(root)
    except Exception:
        return []
    records = _collect_carried_custody_records(
        staged_record,
        result_payload=result_payload,
        current_context=current_context,
        origin_run=_origin_run_id(run_metadata, artifacts_dir),
    )
    if not records:
        return []
    try:
        meta = read_json_object(root / "agent_meta.json", label="agent metadata")
    except StagedHandoffError:
        return []
    existing = meta.get(CARRIED_CUSTODY_META_KEY)
    merged: dict[tuple[str, str], dict[str, Any]] = {}
    if isinstance(existing, list):
        for item in existing:
            if not isinstance(item, Mapping):
                continue
            repo_id = item.get("repo_id")
            staged_id = item.get("staged_id")
            if not isinstance(repo_id, str) or not isinstance(staged_id, str):
                continue
            merged[(staged_id, repo_id)] = dict(item)
    for record in records:
        key = (str(record["staged_id"]), str(record["repo_id"]))
        prior = merged.get(key)
        if isinstance(prior, dict) and isinstance(prior.get("carried_to"), str):
            # A completed transfer is durable; never clear it on re-persist.
            continue
        merged[key] = record
    update_meta_fields(
        artifacts_dir,
        {
            CARRIED_CUSTODY_META_KEY: sorted(
                merged.values(),
                key=lambda r: (str(r.get("staged_id")), str(r.get("repo_id"))),
            )
        },
    )
    return records


def mark_custody_transferred(
    staged_record: Mapping[str, Any],
    *,
    artifacts_dir: str,
    carried_to: str,
) -> None:
    """Record the actual successor identity on this stage's custody records."""
    from sase.axe.run_agent_helpers_artifacts import update_meta_fields

    if not carried_to.strip():
        return
    staged_id = staged_record.get("staged_id")
    if not isinstance(staged_id, str) or not staged_id:
        return
    root = Path(artifacts_dir)
    try:
        meta = read_json_object(root / "agent_meta.json", label="agent metadata")
    except StagedHandoffError:
        return
    existing = meta.get(CARRIED_CUSTODY_META_KEY)
    if not isinstance(existing, list) or not existing:
        return
    updated: list[dict[str, Any]] = []
    changed = False
    for item in existing:
        if (
            isinstance(item, Mapping)
            and item.get("staged_id") == staged_id
            and isinstance(item.get("repo_id"), str)
        ):
            record = dict(item)
            if record.get("carried_to") != carried_to:
                record["carried_to"] = carried_to
                changed = True
            updated.append(record)
        elif isinstance(item, Mapping):
            updated.append(dict(item))
    if changed:
        update_meta_fields(artifacts_dir, {CARRIED_CUSTODY_META_KEY: updated})


__all__ = [
    "CARRIED_CUSTODY_META_KEY",
    "mark_custody_transferred",
    "persist_origin_custody",
]
