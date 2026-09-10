"""Machine-local durable store for ownerless artifact-link events."""

from __future__ import annotations

from pathlib import Path

from sase.core.paths import sase_projects_dir, validate_sase_project_name
from sase.sdd._artifact_link_event_canonical import ArtifactLinkEventObject
from sase.sdd._artifact_link_event_install import install_artifact_link_event_object


def artifact_link_local_event_root(project_key: str) -> Path:
    """Return the machine-local root for durable ownerless link events."""

    validate_sase_project_name(project_key)
    return sase_projects_dir() / project_key


def install_local_artifact_link_event(
    project_key: str,
    item: ArtifactLinkEventObject,
) -> bool:
    """Install one ownerless event in the machine-local durable event root."""

    return install_artifact_link_event_object(
        artifact_link_local_event_root(project_key),
        item,
    )


def local_artifact_link_event_is_durable(
    project_key: str,
    item: ArtifactLinkEventObject,
) -> bool:
    """Return whether the machine-local event root has *item*'s exact bytes."""

    path = artifact_link_local_event_root(project_key) / item.relative_path
    try:
        return path.read_bytes() == item.payload
    except OSError:
        return False


__all__ = [
    "artifact_link_local_event_root",
    "install_local_artifact_link_event",
    "local_artifact_link_event_is_durable",
]
