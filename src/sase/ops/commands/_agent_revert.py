"""Agent revert operation helpers."""

from __future__ import annotations

import argparse
from collections.abc import Mapping
from typing import Any, Literal

from sase.ops.cli import load_request
from sase.ops.names import AGENT_REVERT


def run_revert(args: argparse.Namespace) -> tuple[bool, str, Mapping[str, Any]]:
    from sase.ace.revert_agent_execute import (
        execute_agent_revert,
        execute_agents_revert,
    )

    request = load_request(AGENT_REVERT, args)
    payload = dict(request.payload)
    artifacts_dir = payload.get("artifacts_dir")
    preview = payload.get("preview")
    result: Any
    if payload.get("bulk"):
        result = execute_agents_revert(_bulk_preview_from_payload(payload, args.name))
    elif isinstance(preview, dict):
        result = execute_agent_revert(_single_preview_from_payload(preview, args.name))
    else:
        workspace = payload.get("workspace_dir")
        shas = payload.get("shas")
        result = execute_agent_revert(
            str(workspace) if isinstance(workspace, str) else "",
            tuple(str(item) for item in shas) if isinstance(shas, list) else None,
            agent_name=args.name,
            artifacts_dir=str(artifacts_dir)
            if isinstance(artifacts_dir, str)
            else None,
        )
    success = bool(getattr(result, "success", False))
    message = str(
        getattr(result, "message", "") or ("Reverted" if success else "Revert failed")
    )
    error = getattr(result, "error", None)
    if not success and error:
        message = str(error)
    return (
        success,
        message,
        {
            "name": args.name,
            "reverted_shas": list(getattr(result, "reverted_shas", ()) or ()),
            "error": None if success else message,
        },
    )


def serialize_revert_preview(preview: Any) -> dict[str, Any]:
    """Serialize a single-agent revert preview for the durable request."""
    return {
        "agent_name": preview.agent_name,
        "commits": [_serialize_commit(item) for item in preview.commits],
        "repos": [_serialize_repo(item) for item in preview.repos],
        "scope": preview.scope,
        "workspace_dir": preview.workspace_dir,
    }


def serialize_bulk_revert_preview(preview: Any) -> dict[str, Any]:
    """Serialize a bulk revert preview for the durable request."""
    return {
        "bulk": True,
        "commits": [_serialize_commit(item) for item in preview.commits],
        "matched_target_names": list(preview.matched_target_names),
        "repos": [_serialize_repo(item) for item in preview.repos],
        "targets": [
            {
                "agent_name": item.agent_name,
                "artifacts_dir": item.artifacts_dir,
                "display_name": item.display_name,
                "family_base": item.family_base,
                "workspace_dir": item.workspace_dir,
            }
            for item in preview.targets
        ],
        "workspace_dir": preview.workspace_dir,
    }


def _serialize_commit(item: Any) -> dict[str, Any]:
    return {
        "commit_agent": item.agent_tag,
        "full_sha": item.full_sha,
        "sha": item.sha,
        "subject": item.subject,
    }


def _serialize_repo(item: Any) -> dict[str, Any]:
    return {
        "blocked_reason": item.blocked_reason,
        "commits": [_serialize_commit(commit) for commit in item.commits],
        "discard_local_changes": item.discard_local_changes,
        "is_primary": item.is_primary,
        "repo_kind": item.repo_kind,
        "repo_label": item.repo_label,
        "source_agent_names": list(item.source_agent_names),
        "workspace_dir": item.workspace_dir,
    }


def _commit_from_payload(item: Mapping[str, Any], name: str) -> Any:
    from sase.ace.revert_agent_models import RevertCommit

    return RevertCommit(
        sha=str(item.get("sha", "")),
        full_sha=str(item.get("full_sha") or item.get("sha", "")),
        subject=str(item.get("subject", "")),
        agent_tag=str(item.get("commit_agent") or item.get("agent_tag") or name),
    )


def _repo_kind_from_payload(raw: object) -> Literal["linked", "external"]:
    if raw == "external":
        return "external"
    return "linked"


def _repos_from_payload(raw: object, name: str) -> tuple[Any, ...]:
    from sase.ace.revert_agent_models import RepoRevertPlan

    if not isinstance(raw, list):
        return ()
    return tuple(
        RepoRevertPlan(
            repo_label=str(item.get("repo_label") or "primary"),
            workspace_dir=str(item.get("workspace_dir") or ""),
            is_primary=bool(item.get("is_primary", False)),
            commits=tuple(
                _commit_from_payload(commit, name)
                for commit in item.get("commits") or []
                if isinstance(commit, dict)
            ),
            blocked_reason=item.get("blocked_reason"),
            repo_kind=_repo_kind_from_payload(item.get("repo_kind")),
            discard_local_changes=bool(item.get("discard_local_changes", False)),
            source_agent_names=tuple(item.get("source_agent_names") or ()),
        )
        for item in raw
        if isinstance(item, dict)
    )


def _single_preview_from_payload(preview: Mapping[str, Any], name: str) -> Any:
    from sase.ace.revert_agent_models import RevertPreview

    return RevertPreview(
        agent_name=str(preview.get("agent_name") or name),
        scope=str(preview.get("scope") or "agent"),
        workspace_dir=str(preview.get("workspace_dir") or ""),
        commits=tuple(
            _commit_from_payload(item, name)
            for item in preview.get("commits") or []
            if isinstance(item, dict)
        ),
        repos=_repos_from_payload(preview.get("repos"), name),
    )


def _bulk_preview_from_payload(payload: Mapping[str, Any], name: str) -> Any:
    from sase.ace.revert_agent_models import BulkRevertPreview, RevertTarget

    targets = tuple(
        RevertTarget(
            agent_name=str(item.get("agent_name") or name),
            display_name=str(
                item.get("display_name") or item.get("agent_name") or name
            ),
            workspace_dir=str(item.get("workspace_dir") or ""),
            family_base=item.get("family_base"),
            artifacts_dir=item.get("artifacts_dir"),
        )
        for item in payload.get("targets") or []
        if isinstance(item, dict)
    )
    return BulkRevertPreview(
        workspace_dir=str(payload.get("workspace_dir") or ""),
        targets=targets,
        commits=tuple(
            _commit_from_payload(item, name)
            for item in payload.get("commits") or []
            if isinstance(item, dict)
        ),
        repos=_repos_from_payload(payload.get("repos"), name),
        matched_target_names=tuple(payload.get("matched_target_names") or ()),
    )


__all__ = [
    "run_revert",
    "serialize_bulk_revert_preview",
    "serialize_revert_preview",
]
