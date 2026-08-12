"""Resolution and materialization helpers for launch-prompt artifact references."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

from sase.artifact_ref_models import (
    ArtifactRef,
    ArtifactRefContext,
    ArtifactRefRepository,
    ArtifactRefResolution,
)
from sase.artifact_ref_operations import resolve_artifact_ref
from sase.core.artifact_file_query_facade import query_artifact_files
from sase.core.artifact_file_vcs import materialize_artifact_file


def resolve_for_launch(
    reference: ArtifactRef,
    *,
    context: ArtifactRefContext,
    resolve_checkout_commit: Callable[[Path, str], str | None],
) -> ArtifactRefResolution:
    """Resolve a ref, consulting its checkout for an unindexed commit if needed."""

    resolution = resolve_artifact_ref(reference, context=context)
    if reference.kind_type != "commit" or resolution.status != "missing":
        return resolution

    repository = repository_for_ref(reference.payload.repo or "", context)
    if repository is None or repository.checkout_path is None:
        return resolution
    full_sha = resolve_checkout_commit(
        repository.checkout_path,
        reference.payload.sha or "",
    )
    if full_sha is None:
        return resolution
    repositories = tuple(
        replace(candidate, shas=(full_sha,)) if candidate is repository else candidate
        for candidate in context.repositories
    )
    return resolve_artifact_ref(
        reference,
        context=replace(context, repositories=repositories),
    )


def artifact_resolved_path(
    reference: ArtifactRef,
    resolution: ArtifactRefResolution,
    *,
    context: ArtifactRefContext,
    materialized_path: Path | None,
) -> Path | None:
    """Return the local path used to render a successfully resolved ref."""

    if reference.kind_type in {"document", "chat", "file", "bead", "agent"}:
        if reference.kind_type == "file" and resolution.status == "vcs_backed":
            if materialized_path is None:
                raise RuntimeError(
                    "VCS-backed artifact content is unavailable"
                    + ("" if resolution.locator is None else f" ({resolution.locator})")
                )
            return materialized_path
        if resolution.resolved_path is None:
            raise RuntimeError("resolver returned no artifact path")
        return resolution.resolved_path
    if reference.kind_type in {"commit", "stitch"}:
        if resolution.locator is None:
            raise RuntimeError(f"resolver returned no {reference.kind_type} locator")
        repository = repository_for_ref(reference.payload.repo or "", context)
        if repository is None or repository.checkout_path is None:
            raise RuntimeError("repository checkout is unavailable")
        return repository.checkout_path
    if reference.kind_type == "patch":
        return None
    if reference.kind_type == "bug":
        if resolution.locator is None or reference.payload.number is None:
            raise RuntimeError("resolver returned no bug locator")
        return None
    raise RuntimeError(f"unsupported artifact reference kind: {reference.kind}")


def materialized_artifact_path(
    reference: ArtifactRef,
    resolution: ArtifactRefResolution,
    *,
    context: ArtifactRefContext,
) -> Path | None:
    """Materialize VCS-backed file content when the resolution requires it."""

    if reference.kind_type != "file" or resolution.status != "vcs_backed":
        return None
    source = reference.payload.source
    digest = reference.payload.digest
    if source is None or digest is None:
        return None
    artifact_id = f"{source}:{digest}"
    row = next(
        (
            candidate
            for candidate in query_artifact_files(
                context.artifact_index_path,
                limit=None,
            )
            if candidate.id == artifact_id
        ),
        None,
    )
    if row is None:
        return None
    return materialize_artifact_file(row, repositories=context.repositories)


def resolve_checkout_commit(checkout_path: Path, sha: str) -> str | None:
    """Resolve and validate a commit SHA through the checkout's VCS provider."""

    try:
        from sase.vcs_provider import get_vcs_provider

        resolved = get_vcs_provider(str(checkout_path)).revision_id(
            f"{sha}^{{commit}}",
            str(checkout_path),
        )
    except Exception:
        return None
    normalized = resolved.strip().lower()
    if len(normalized) != 40 or any(
        character not in "0123456789abcdef" for character in normalized
    ):
        return None
    return normalized


def repository_for_ref(
    repo: str,
    context: ArtifactRefContext,
) -> ArtifactRefRepository | None:
    """Find a repository by its canonical name or an alias."""

    return next(
        (
            repository
            for repository in context.repositories
            if repository.name == repo or repo in repository.aliases
        ),
        None,
    )


def artifact_ref_resolution_hint(
    reference: ArtifactRef,
    resolution: ArtifactRefResolution,
    *,
    context: ArtifactRefContext | None = None,
) -> str | None:
    """Return an actionable publication hint for unresolved entity pages."""

    if resolution.status in {"exact", "drifted"}:
        return None
    if resolution.diagnostic is not None:
        return resolution.diagnostic
    if reference.kind_type == "bead":
        bead_id = reference.payload.id
        if not bead_id:
            return None
        if resolution.status == "unknown_project" and context is not None:
            project = _known_project_for_bead_id(bead_id, context)
            if project is not None:
                return (
                    f"hint: project {project} has no bead store in this "
                    "reference context"
                )
        return f"hint: no published page for {bead_id}; run `sase bead page refresh`"
    if reference.kind_type == "agent":
        name = reference.payload.name
        if not name:
            return None
        return f"hint: no published page for {name}; run `sase agent sync`"
    if (
        reference.kind_type == "document"
        and resolution.status == "missing"
        and context is not None
    ):
        roots = tuple(
            root.root for root in context.document_roots if root.kind == reference.kind
        )
        if not roots:
            return f"hint: no document root is configured for @{reference.kind}"
        label = "document root" if len(roots) == 1 else "document roots"
        searched = ", ".join(str(root) for root in roots)
        return f"hint: searched {label}: {searched}"
    return None


def _known_project_for_bead_id(
    bead_id: str,
    context: ArtifactRefContext,
) -> str | None:
    matches: list[tuple[int, str]] = []
    for project in context.projects:
        refs = (project.name, project.key, *project.aliases)
        for ref in refs:
            if not ref:
                continue
            if bead_id == ref or bead_id.startswith(f"{ref}-"):
                matches.append((len(ref), project.name))
                break
    if not matches:
        return None
    longest = max(length for length, _project in matches)
    names = {project for length, project in matches if length == longest}
    return next(iter(names)) if len(names) == 1 else None
