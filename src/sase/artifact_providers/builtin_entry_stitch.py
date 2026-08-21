"""Python-owned resolution for ``@stitch`` (and its ``commit:`` alias).

``ArtifactRefPayloadWire::Stitch { repo, sha }`` already parses both
spellings and Rust's ``validate_sha`` already enforces 7-40 lowercase hex, so
no grammar work happens here -- only checkout-backed hash resolution.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from sase.artifact_providers.builtin_entries import (
    BuiltinEntryOutcome,
    validate_builtin_entry,
)
from sase.artifact_ref_models import (
    ArtifactEntry,
    ArtifactRef,
    ArtifactRefContext,
    ArtifactRefRepository,
)
from sase.artifact_ref_prompt_context import PromptRefContext
from sase.artifact_ref_prompt_resolution import (
    repository_for_ref,
    resolve_checkout_commit,
)


def resolve_stitch_entry(
    reference: ArtifactRef,
    *,
    context: ArtifactRefContext,
    ref_context: PromptRefContext,
) -> BuiltinEntryOutcome:
    """Resolve ``@stitch:<sha>`` / ``@stitch:<repo>@<sha>`` against a checkout.

    "Error on ambiguity" for a short sha is satisfied by ``git`` itself: an
    ambiguous prefix is refused by the VCS provider and surfaces here as
    ``missing`` with an actionable, longer-prefix diagnostic, rather than a
    dedicated disambiguation probe that would break VCS neutrality.
    """

    payload = reference.payload
    sha = payload.sha or ""

    repository = _pick_repository(
        payload.repo, context=context, ref_context=ref_context
    )
    if isinstance(repository, BuiltinEntryOutcome):
        return repository

    checkout_path = next(
        (path for path in repository.checkout_paths if path.exists()), None
    )
    full_sha = (
        None if checkout_path is None else resolve_checkout_commit(checkout_path, sha)
    )
    if checkout_path is None or full_sha is None:
        return BuiltinEntryOutcome(
            status="missing",
            diagnostic=(
                f"no commit matching {sha} in {repository.name}; git reports it as "
                "unknown or ambiguous — use a longer prefix"
            ),
        )

    entry = validate_builtin_entry(
        ArtifactEntry(
            stable_id=f"stitch:{repository.name}@{full_sha}",
            ref_kind="stitch",
            canonical_argument=f"{repository.name}@{full_sha}",
            display_label=full_sha[:12],
            origin="prompt_ref",
            repository=repository.name,
            captured_revision=full_sha,
            properties=_stitch_properties(repository.name, full_sha, checkout_path),
        )
    )
    return BuiltinEntryOutcome(
        status="exact",
        entry=entry,
        locator=f"{repository.name}@{full_sha}",
        resolved_path=checkout_path,
        canonical_reference=f"stitch:{repository.name}@{full_sha}",
    )


def _pick_repository(
    repo: str | None,
    *,
    context: ArtifactRefContext,
    ref_context: PromptRefContext,
) -> ArtifactRefRepository | BuiltinEntryOutcome:
    if repo is not None:
        found = repository_for_ref(repo, context)
        if found is not None:
            return found
        known = ", ".join(sorted(candidate.name for candidate in context.repositories))
        return BuiltinEntryOutcome(
            status="unknown_repo",
            diagnostic=f"@stitch: unknown repository {repo!r}; known repositories: {known}",
            candidates=tuple(
                sorted(candidate.name for candidate in context.repositories)
            ),
        )

    primary = ref_context.primary_repo
    found = None if primary is None else repository_for_ref(primary, context)
    if found is not None:
        return found
    return BuiltinEntryOutcome(
        status="unknown_repo",
        diagnostic=(
            "@stitch:<sha> needs a project; write @stitch:<repo>@<sha> or "
            "add a #git/#gh workflow"
        ),
    )


def _stitch_properties(
    repo: str,
    full_sha: str,
    checkout_path: Path,
) -> dict[str, str]:
    properties = {"repo": repo, "sha": full_sha}
    try:
        from sase.vcs_provider import get_vcs_provider

        commits = get_vcs_provider(str(checkout_path)).log(
            str(checkout_path), 1, revs=(full_sha,), merges="show"
        )
    except Exception:
        return properties
    if not commits:
        return properties
    commit = commits[0]
    properties["subject"] = commit.subject
    properties["author"] = commit.author_name
    properties["authored_at"] = datetime.fromtimestamp(
        commit.timestamp, tz=UTC
    ).isoformat()
    return properties


__all__ = ["resolve_stitch_entry"]
