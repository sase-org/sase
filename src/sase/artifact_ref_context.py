"""Machine- and project-specific artifact-reference context assembly."""

from __future__ import annotations

from pathlib import Path

from sase.artifact_ref_entity_context import collect_entity_context
from sase.artifact_ref_models import (
    ArtifactRefContext,
    ArtifactRefDocumentRoot,
    ArtifactRefProject,
    ArtifactRefRepository,
)
from sase.core.artifact_file_facade import default_artifact_files_index_path
from sase.core.paths import sase_projects_dir, sase_subdir
from sase.core.project_lifecycle_facade import list_project_records
from sase.core.project_lifecycle_wire import effective_project_name
from sase.repo_inventory import collect_repo_inventory
from sase.sdd.plan_refs import workspace_context_for_plan_resolution
from sase.sdd.store import document_sidecar_roles, resolve_sdd_store


ARTIFACT_REF_LSP_CATALOG_SCHEMA_VERSION = 1


def artifact_ref_context(
    workspace_dir: str | Path,
    workspace_num: int,
    project: str | None = None,
) -> ArtifactRefContext:
    """Build resolution context for one project's managed workspace."""

    workspace = Path(workspace_dir).expanduser().resolve(strict=False)
    store = resolve_sdd_store(workspace, workspace_num)
    roles = document_sidecar_roles(
        store.split_sidecar_roles(),
        include_plans=True,
    )
    document_roots: list[ArtifactRefDocumentRoot] = []
    seen_roots: set[tuple[str, Path]] = set()
    for role in roles:
        try:
            root = store.kind_root(role)
        except (KeyError, OSError, ValueError):
            continue
        _append_document_root(document_roots, seen_roots, role, root)
        if role == "plans":
            _append_document_root(
                document_roots,
                seen_roots,
                role,
                sase_subdir("plans"),
            )

    project_filter = project or _workspace_project_ref(workspace)
    try:
        inventory = collect_repo_inventory(project=project_filter)
    except Exception:
        inventory = None
    repository_records = () if inventory is None else inventory.records
    repositories = tuple(
        ArtifactRefRepository(
            name=record.name,
            aliases=tuple(
                dict.fromkeys(
                    value for value in (record.slug,) if value and value != record.name
                )
            ),
            checkout_path=_repository_checkout_path(record, workspace_num),
        )
        for record in repository_records
    )

    try:
        project_records = list_project_records(
            sase_projects_dir(),
            "all",
            include_home=False,
            projects_only=True,
        )
    except Exception:
        project_records = []
    projects = tuple(
        ArtifactRefProject(
            name=effective_project_name(record),
            key=record.project_name,
            aliases=tuple(dict.fromkeys(record.aliases)),
        )
        for record in project_records
    )
    bead_stores, agent_roots, agent_owner = collect_entity_context(
        store,
        project_filter,
        projects,
    )
    return ArtifactRefContext(
        document_roots=tuple(document_roots),
        chats_root=sase_subdir("chats").expanduser().resolve(strict=False),
        artifact_index_path=default_artifact_files_index_path()
        .expanduser()
        .resolve(strict=False),
        repositories=repositories,
        projects=projects,
        bead_stores=bead_stores,
        agent_roots=agent_roots,
        agent_owner=agent_owner,
    )


def artifact_ref_lsp_catalog_payload(
    launch_workspace: str | Path | None = None,
) -> dict[str, object]:
    """Build the local artifact-reference catalog consumed by ``sase lsp``.

    Catalog construction is deliberately best-effort per project. A stale
    project record or unavailable workspace cannot prevent the other enabled
    projects from contributing editor context.
    """

    from sase.artifact_ref_lsp import build_artifact_ref_lsp_catalog_payload

    return build_artifact_ref_lsp_catalog_payload(
        launch_workspace,
        artifact_ref_context_fn=artifact_ref_context,
        effective_project_name_fn=effective_project_name,
        list_project_records_fn=list_project_records,
        projects_root=sase_projects_dir(),
        schema_version=ARTIFACT_REF_LSP_CATALOG_SCHEMA_VERSION,
        workspace_context_fn=workspace_context_for_plan_resolution,
        workspace_project_ref_fn=_workspace_project_ref,
    )


def launch_artifact_ref_context(
    *,
    is_home_mode: bool,
) -> ArtifactRefContext:
    """Build the same local resolution context used for prompt launches."""

    from sase.artifact_ref_launch_context import build_launch_artifact_ref_context

    return build_launch_artifact_ref_context(
        artifact_ref_context_fn=artifact_ref_context,
        is_home_mode=is_home_mode,
        workspace_project_ref_fn=_workspace_project_ref,
    )


def _repository_checkout_path(record: object, workspace_num: int) -> Path | None:
    clone_for_workspace = getattr(record, "clone_for_workspace", None)
    clone = (
        clone_for_workspace(workspace_num) if callable(clone_for_workspace) else None
    )
    raw_path = getattr(clone, "path", None)
    exists = bool(getattr(clone, "exists", False))
    if raw_path is None and workspace_num in {0, 1}:
        raw_path = getattr(record, "path", None)
        exists = bool(getattr(record, "exists", False))
    if not raw_path or not exists:
        return None
    return Path(str(raw_path)).expanduser().resolve(strict=False)


def _append_document_root(
    roots: list[ArtifactRefDocumentRoot],
    seen: set[tuple[str, Path]],
    kind: str,
    root: str | Path,
) -> None:
    normalized = Path(root).expanduser().resolve(strict=False)
    key = (kind, normalized)
    if key in seen:
        return
    seen.add(key)
    roots.append(ArtifactRefDocumentRoot(kind, normalized))


def _workspace_project_ref(workspace: Path) -> str | None:
    try:
        from sase.workspace_provider import find_marker_from_cwd

        found = find_marker_from_cwd(str(workspace))
    except Exception:
        return None
    if found is None:
        return None
    marker = found[1]
    return marker.project_key or marker.project_name or None


__all__ = [
    "ARTIFACT_REF_LSP_CATALOG_SCHEMA_VERSION",
    "artifact_ref_context",
    "artifact_ref_lsp_catalog_payload",
    "launch_artifact_ref_context",
]
