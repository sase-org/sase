"""Best-effort local entity context for artifact-reference resolution."""

from __future__ import annotations

from pathlib import Path

from sase._linked_repo_paths import hidden_sidecar_clone_dir
from sase.artifact_ref_models import (
    ArtifactRefAgentOwner,
    ArtifactRefAgentRoot,
    ArtifactRefBeadStore,
    ArtifactRefProject,
)
from sase.bead.config import load_config
from sase.sdd.store import (
    AGENTS_SIDECAR_ROLE,
    BEADS_SIDECAR_ROLE,
    SddStore,
)


def collect_entity_context(
    store: SddStore,
    project_ref: str | None,
    projects: tuple[ArtifactRefProject, ...],
) -> tuple[
    tuple[ArtifactRefBeadStore, ...],
    tuple[ArtifactRefAgentRoot, ...],
    ArtifactRefAgentOwner | None,
]:
    """Collect all entity namespaces for the context's selected project."""

    selected = _project_for_ref(project_ref, projects)
    if selected is None and len(projects) == 1:
        selected = projects[0]
    if selected is None:
        bead_stores: tuple[ArtifactRefBeadStore, ...] = ()
        agent_roots: tuple[ArtifactRefAgentRoot, ...] = ()
    else:
        try:
            bead_stores = collect_bead_stores(store, selected.name)
        except Exception:
            bead_stores = ()
        try:
            agent_roots = collect_agent_roots(selected.key, selected.name)
        except Exception:
            agent_roots = ()
    try:
        owner = local_agent_owner()
    except Exception:
        owner = None
    return bead_stores, agent_roots, owner


def collect_bead_stores(
    store: SddStore,
    project_name: str,
) -> tuple[ArtifactRefBeadStore, ...]:
    """Collect the current project's available bead store without reading issues."""

    try:
        root = store.kind_root(BEADS_SIDECAR_ROLE).expanduser().resolve(strict=False)
        if not root.is_dir() or not (root / "config.json").is_file():
            return ()
        config = load_config(root)
        prefix = config.get("issue_prefix")
        if not isinstance(prefix, str) or not prefix:
            return ()
    except (KeyError, OSError, TypeError, ValueError):
        return ()
    return (ArtifactRefBeadStore(project=project_name, prefix=prefix, root=root),)


def collect_agent_roots(
    project_key: str | None,
    project_name: str,
) -> tuple[ArtifactRefAgentRoot, ...]:
    """Collect the current project's locally materialized agents sidecar."""

    if not project_key:
        return ()
    try:
        root = (
            Path(hidden_sidecar_clone_dir(project_key, AGENTS_SIDECAR_ROLE))
            .expanduser()
            .resolve(strict=False)
        )
        if not root.is_dir():
            return ()
    except (OSError, TypeError, ValueError):
        return ()
    return (ArtifactRefAgentRoot(project=project_name, root=root),)


def local_agent_owner() -> ArtifactRefAgentOwner | None:
    """Return the configured local owner when identity is available."""

    try:
        from sase.config import get_agent_owner_identity

        owner = get_agent_owner_identity()
    except Exception:
        return None
    if owner is None:
        return None
    return ArtifactRefAgentOwner(
        username=owner.username,
        machine_name=owner.machine_name,
    )


def _project_for_ref(
    project_ref: str | None,
    projects: tuple[ArtifactRefProject, ...],
) -> ArtifactRefProject | None:
    if project_ref is None:
        return None
    folded = project_ref.casefold()
    for project in projects:
        if (
            project.name.casefold() == folded
            or project.key.casefold() == folded
            or any(alias.casefold() == folded for alias in project.aliases)
        ):
            return project
    return None


__all__ = [
    "collect_agent_roots",
    "collect_bead_stores",
    "collect_entity_context",
    "local_agent_owner",
]
