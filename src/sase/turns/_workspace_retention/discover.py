"""Resolve the repositories that belong to a settling workspace owner."""

from __future__ import annotations

import json
from pathlib import Path

from sase.llm_provider.commit_finalizer_baseline import (
    load_finalizer_baseline_records,
)
from sase.llm_provider.commit_finalizer_git import normalize_path

from .types import WorkspaceRetentionRepo


def discover_workspace_retention_repos(
    artifacts_dir: str,
    checkout_dir: str | None,
) -> tuple[tuple[WorkspaceRetentionRepo, ...], tuple[str, ...]]:
    """Resolve only repositories recorded for this owner and its checkout.

    Finalizer baselines are authoritative for repository paths. Opened-repo
    markers cover repositories whose baseline capture failed, while staged
    custody records keep the repository identities available for the terminal
    record. This never searches neighboring checkouts.
    """
    from sase._linked_repo_markers import opened_repo_records

    evidence_root = Path(artifacts_dir)
    baseline_records = load_finalizer_baseline_records(evidence_root) or ()
    opened_records = opened_repo_records(evidence_root)
    custody_ids = _custody_repo_ids(evidence_root)
    by_path: dict[str, WorkspaceRetentionRepo] = {}
    origin_ids: set[str] = set(custody_ids)

    primary_path = normalize_path(checkout_dir) if checkout_dir else None
    for baseline in baseline_records:
        path = normalize_path(baseline.path)
        is_primary = path == primary_path or (
            baseline.scope == "run_start" and baseline.kind == "main"
        )
        origin_ids.add(baseline.repo_id)
        prior = by_path.get(path)
        by_path[path] = WorkspaceRetentionRepo(
            repo_id=baseline.repo_id,
            path=baseline.path,
            is_primary=is_primary or bool(prior and prior.is_primary),
            positive_custody=(
                baseline.repo_id in custody_ids
                or baseline.scope == "opened_repo"
                or bool(prior and prior.positive_custody)
            ),
        )

    for name, record in opened_records.items():
        repo_kind = record.get("kind") or "linked"
        repo_id = f"{repo_kind}:{name}"
        opened_path = record.get("workspace_dir")
        if not opened_path:
            continue
        normalized = normalize_path(opened_path)
        origin_ids.add(repo_id)
        prior = by_path.get(normalized)
        by_path[normalized] = WorkspaceRetentionRepo(
            repo_id=prior.repo_id if prior else repo_id,
            path=prior.path if prior else opened_path,
            is_primary=bool(prior and prior.is_primary),
            positive_custody=True,
        )

    if checkout_dir:
        normalized = normalize_path(checkout_dir)
        existing = by_path.get(normalized)
        if existing is not None:
            by_path[normalized] = WorkspaceRetentionRepo(
                repo_id=existing.repo_id,
                path=existing.path,
                is_primary=True,
                positive_custody=True,
            )
        elif Path(checkout_dir).is_dir():
            by_path[normalized] = WorkspaceRetentionRepo(
                repo_id="primary",
                path=checkout_dir,
                is_primary=True,
                positive_custody=True,
            )
            origin_ids.add("primary")

    repos = tuple(
        sorted(
            by_path.values(), key=lambda repo: (normalize_path(repo.path), repo.repo_id)
        )
    )
    return repos, tuple(sorted(origin_ids))


def _custody_repo_ids(artifacts_dir: Path) -> set[str]:
    try:
        payload = json.loads(
            (artifacts_dir / "agent_meta.json").read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError):
        return set()
    if not isinstance(payload, dict):
        return set()
    records = payload.get("carried_repositories")
    if not isinstance(records, list):
        return set()
    return {
        repo_id
        for record in records
        if isinstance(record, dict)
        and isinstance((repo_id := record.get("repo_id")), str)
        and repo_id
    }


__all__ = ["discover_workspace_retention_repos"]
