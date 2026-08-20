"""Plan Referenced By write-back requests from one prepared prompt archive."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from sase._linked_repo_config import resolution_config
from sase.agents_sync.models import ProjectTarget
from sase.agents_sync.prompt_archive.render import RenderedPromptArchive
from sase.agents_sync.referenced_by_outbox_models import (
    ReferencedByLogicalKey,
    ReferencedByOutboxItem,
)
from sase.core.artifact_ref_uses import (
    ARTIFACT_REF_USE_MANIFEST_NAME,
    ArtifactRefUseRecord,
    read_artifact_ref_uses,
)
from sase.core.prompt_artifact_staging import PromptArtifactRecord
from sase.sdd.store import SddStore, document_sidecar_roles
from sase.sidecar_ref_config import SidecarRefPolicy, effective_sidecar_ref_policies


def plan_referenced_by_requests(
    *,
    target: ProjectTarget,
    rendered: RenderedPromptArchive,
    agent_artifacts_dir: Path,
    global_agent: str,
    primary_revision: str,
    store: SddStore,
    workspace_root: Path,
    repository_roots: Mapping[str, Path],
    agent_url: str | None,
    now: datetime | None = None,
) -> tuple[ReferencedByOutboxItem, ...]:
    """Return durable write-back requests implied by *rendered*."""

    policies = _referenced_by_policies(store, workspace_root)
    if not policies or not rendered.linked_records:
        return ()
    role_roots = _role_roots(store, policies)
    if not role_roots:
        return ()

    use_counts = _use_counts(agent_artifacts_dir)
    destinations = _reference_destinations(rendered)
    published_date = (now or datetime.now(tz=UTC)).date().isoformat()
    by_key: dict[ReferencedByLogicalKey, ReferencedByOutboxItem] = {}
    for record in rendered.linked_records:
        uses = max(1, use_counts.get(record["raw_ref"], 1))
        document_path = _record_document_path(record, repository_roots)
        if document_path is None:
            continue
        for role, (role_root, repo_root, policy) in role_roots.items():
            if not document_path.is_relative_to(role_root):
                continue
            if not document_path.is_relative_to(repo_root):
                continue
            repo_relpath = document_path.relative_to(repo_root).as_posix()
            provider = policy.provider_id or policy.ref_kind
            artifact_id = f"{provider}:{repo_relpath}"
            item = ReferencedByOutboxItem(
                project_key=target.project_key,
                project=target.project,
                global_agent=global_agent,
                agent_url=agent_url,
                primary_revision=primary_revision,
                sidecar_role=role,
                provider=provider,
                artifact_id=artifact_id,
                repo_relpath=repo_relpath,
                identity_value=None,
                canonical_ref=artifact_id,
                destination=destinations.get(record["raw_ref"]),
                uses=uses,
                published_date=published_date,
                relation="cites",
                origin="prompt_ref",
                description=_prompt_ref_description(record["raw_ref"], artifact_id),
            )
            key = item.logical_key
            existing = by_key.get(key)
            by_key[key] = (
                item
                if existing is None
                else replace(
                    existing,
                    uses=existing.uses + item.uses,
                    destination=existing.destination or item.destination,
                )
            )
    return tuple(by_key.values())


def _referenced_by_policies(
    store: SddStore,
    workspace_root: Path,
) -> dict[str, SidecarRefPolicy]:
    try:
        config = resolution_config(str(workspace_root), None)
    except Exception:
        config = {}
    roles = document_sidecar_roles(store.split_sidecar_roles(), include_plans=True)
    policies = effective_sidecar_ref_policies(
        config,
        primary_workspace_dir=workspace_root,
        roles=roles,
    )
    return {
        role: policy
        for role, policy in policies.items()
        if policy.is_document and _referenced_by_mode(policy) == "markdown_table"
    }


def _referenced_by_mode(policy: SidecarRefPolicy) -> str | None:
    spec = policy.spec or {}
    ref = spec.get("ref") if isinstance(spec, Mapping) else None
    publication = ref.get("publication") if isinstance(ref, Mapping) else None
    mode = (
        publication.get("referenced_by") if isinstance(publication, Mapping) else None
    )
    return str(mode) if isinstance(mode, str) else None


def _role_roots(
    store: SddStore,
    policies: Mapping[str, SidecarRefPolicy],
) -> dict[str, tuple[Path, Path, SidecarRefPolicy]]:
    roots: dict[str, tuple[Path, Path, SidecarRefPolicy]] = {}
    for role, policy in policies.items():
        try:
            role_root = store.kind_root(role).expanduser().resolve(strict=False)
            repo_root = (
                store.repo_root_for_kind(role).expanduser().resolve(strict=False)
            )
        except (OSError, ValueError):
            continue
        roots[role] = (role_root, repo_root, policy)
    return roots


def _use_counts(agent_artifacts_dir: Path) -> Counter[str]:
    manifest = agent_artifacts_dir / ARTIFACT_REF_USE_MANIFEST_NAME
    try:
        rows: list[ArtifactRefUseRecord] = read_artifact_ref_uses(manifest)
    except Exception:
        return Counter()
    return Counter(row.raw_ref for row in rows)


def _reference_destinations(
    rendered: RenderedPromptArchive,
) -> dict[str, str | None]:
    result: dict[str, str | None] = {}
    for row in rendered.reference_labels:
        raw_ref = row.get("raw_ref")
        if isinstance(raw_ref, str) and raw_ref:
            destination = row.get("destination")
            result[raw_ref] = destination if isinstance(destination, str) else None
    return result


def _prompt_ref_description(raw_ref: str, artifact_id: str) -> str:
    cleaned = " ".join(raw_ref.split())
    if not cleaned:
        cleaned = artifact_id
    description = f"prompt reference {cleaned}"
    return description[:240]


def _record_document_path(
    record: PromptArtifactRecord,
    repository_roots: Mapping[str, Path],
) -> Path | None:
    source_path = record.get("source_path")
    if isinstance(source_path, str) and source_path:
        return Path(source_path).expanduser().resolve(strict=False)
    vcs_repo = record.get("vcs_repo")
    vcs_relpath = record.get("vcs_relpath")
    if not vcs_repo or not vcs_relpath:
        return None
    root = repository_roots.get(vcs_repo)
    if root is None:
        return None
    return (root / vcs_relpath).expanduser().resolve(strict=False)


__all__ = ["plan_referenced_by_requests"]
