"""Project-key resolution for artifact-link storage."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from sase.sdd._artifact_link_store_support import artifact_link_aggregate_path

if TYPE_CHECKING:
    from sase.sdd._artifact_link_store_impl import ArtifactLinkStore


def resolve_artifact_link_store(cwd: Path | None = None) -> ArtifactLinkStore:
    """Resolve the current checkout's artifact-link adapter."""

    from sase.sdd._artifact_link_store_impl import ArtifactLinkStore
    from sase.sdd.checkout_anchor import resolve_checkout_anchor
    from sase.sdd.plan_refs import workspace_context_for_plan_resolution
    from sase.sdd.store import resolve_sdd_store

    start = (cwd or Path.cwd()).expanduser().resolve(strict=False)
    project_key = resolve_artifact_link_project_key(start)
    if not project_key:
        raise RuntimeError("could not resolve the current project for artifact links")
    anchor = resolve_checkout_anchor(start)
    primary_root, workspace_num = workspace_context_for_plan_resolution(
        anchor.primary_root
    )
    store = resolve_sdd_store(primary_root, workspace_num)
    return ArtifactLinkStore.from_sdd_store(store, project_key)


def resolve_artifact_link_project_key(
    cwd: Path | None = None,
    *,
    fallback: str | None = None,
) -> str | None:
    """Resolve *cwd* or *fallback* to a canonical ProjectSpec key."""

    start = (cwd or Path.cwd()).expanduser().resolve(strict=False)
    candidates: list[tuple[str, bool]] = []
    try:
        from sase.workspace_provider.marker import find_marker_from_cwd

        found = find_marker_from_cwd(str(start))
    except Exception:  # noqa: BLE001 - CLI resolution is best-effort
        found = None
    if found is not None:
        marker = found[1]
        if isinstance(marker.project_key, str) and marker.project_key.strip():
            candidates.append((marker.project_key, True))
        if isinstance(marker.project_name, str) and marker.project_name.strip():
            candidates.append((marker.project_name, False))
    if fallback:
        candidates.append((fallback, True))
    try:
        from sase.bead.project_name import infer_project_name_from_cwd

        inferred = infer_project_name_from_cwd(str(start))
    except Exception:  # noqa: BLE001 - CLI resolution is best-effort
        inferred = None
    if inferred:
        candidates.append((inferred, False))
    seen: set[str] = set()
    for candidate, allow_direct in candidates:
        ref = candidate.strip()
        if not ref or ref in seen:
            continue
        seen.add(ref)
        resolved = _project_key_for_ref(ref, allow_direct=allow_direct)
        if resolved is not None:
            return resolved
    return None


def _project_key_for_ref(ref: str, *, allow_direct: bool) -> str | None:
    try:
        from sase.core.paths import sase_projects_dir
        from sase.core.project_lifecycle_facade import list_project_records
        from sase.core.project_lifecycle_wire import effective_project_name

        records = list_project_records(
            sase_projects_dir(),
            "all",
            include_home=False,
            projects_only=True,
        )
    except Exception:  # noqa: BLE001 - fall back to direct key validation
        records = []

    folded = ref.casefold()
    for record in records:
        aliases = {alias.casefold() for alias in getattr(record, "aliases", ())}
        display = effective_project_name(record)
        if folded in {
            record.project_name.casefold(),
            display.casefold(),
            _project_provider_slug(record.project_name).casefold(),
            *aliases,
        }:
            return record.project_name

    if allow_direct and not records:
        try:
            artifact_link_aggregate_path(ref)
        except ValueError:
            return None
        return ref
    return None


def _project_provider_slug(project_key: str) -> str:
    if not project_key.startswith("gh_") or "__" not in project_key:
        return project_key
    owner, repository = project_key.removeprefix("gh_").split("__", 1)
    return f"{owner}/{repository}"
