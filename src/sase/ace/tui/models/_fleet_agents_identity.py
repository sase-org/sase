"""Fleet row identity and project naming helpers."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ._fleet_agents_scalars import display_token, mapping, optional_str


def agent_family_name(
    summary: Mapping[str, Any],
    labels: Mapping[str, Any],
    logical_locator: Mapping[str, Any],
    *,
    family_role: str | None,
    parent_timestamp: str | None,
) -> str | None:
    explicit = optional_str(summary.get("agent_family"))
    if explicit is not None:
        return explicit
    if family_role == "root" and parent_timestamp is None:
        return None
    return optional_str(labels.get("family_label"), logical_locator.get("family_id"))


def agent_name(
    summary: Mapping[str, Any],
    labels: Mapping[str, Any],
    logical_locator: Mapping[str, Any],
    exact_locator: Mapping[str, Any],
    logical_key: str | None,
    exact_key: str | None,
    summary_index: int,
) -> str:
    name = optional_str(
        labels.get("agent_label"),
        summary.get("agent_label"),
        summary.get("agent_name"),
        summary.get("name"),
    )
    if name:
        return name
    logical_from_exact = mapping(exact_locator.get("logical"))
    locator_agent_id = optional_str(
        logical_locator.get("agent_id"),
        logical_from_exact.get("agent_id"),
    )
    if locator_agent_id:
        return display_token(locator_agent_id)
    key = logical_key or exact_key
    if key:
        return key.rsplit("/", 1)[-1].rsplit(":", 1)[-1] or key
    return f"remote-agent-{summary_index + 1}"


def role_suffix_from_name(
    agent_name: str | None, family_role: str | None
) -> str | None:
    if family_role in {None, "root", "historical_shell"} or not agent_name:
        return None
    for separator in ("--", "."):
        if separator not in agent_name:
            continue
        base, suffix = agent_name.rsplit(separator, 1)
        if base and suffix and not any(character.isspace() for character in suffix):
            return f"{separator}{suffix}"
    return None


def patch_name(
    summary: Mapping[str, Any],
    labels: Mapping[str, Any],
    logical_locator: Mapping[str, Any],
    agent_name: str,
) -> str:
    project = logical_locator.get("project")
    project_id = project.get("project_id") if isinstance(project, Mapping) else project
    patch = optional_str(
        project_id,
        summary.get("patch"),
        summary.get("patch_name"),
        logical_locator.get("patch"),
        logical_locator.get("patch_name"),
        summary.get("project_name"),
        labels.get("project_label"),
    )
    return display_token(patch or agent_name)


def project_display_name(
    summary: Mapping[str, Any],
    labels: Mapping[str, Any],
    logical_locator: Mapping[str, Any],
) -> str:
    project_id = optional_str(
        summary.get("project_name"),
        _logical_project_id(logical_locator),
    )
    owner_label = optional_str(labels.get("project_label"))
    if owner_label:
        return display_token(owner_label)
    # ``labels.project_label`` is a required, always-populated field on the
    # current wire schema (it falls back to the raw project id on the owner
    # side already), so this only helps a legacy (schema v1) payload from a
    # not-yet-upgraded remote host that omits the field entirely.
    if project_id:
        local_label = _local_project_display_name(project_id)
        if local_label and local_label != project_id:
            return display_token(local_label)
    return display_token(project_id or "fleet")


def _local_project_display_name(project_id: str) -> str | None:
    """Resolve *project_id* through this viewer's own project registry."""
    from sase.project_display_names import project_display_name_for

    return project_display_name_for(project_id)


def project_file(
    logical_locator: Mapping[str, Any],
    project_display_name: str,
) -> str:
    project_id = _logical_project_id(logical_locator) or project_display_name
    return f"/fleet/{display_token(project_id)}/project.yml"


def _logical_project_id(logical_locator: Mapping[str, Any]) -> str | None:
    project = logical_locator.get("project")
    if isinstance(project, Mapping):
        return optional_str(project.get("project_id"))
    return optional_str(project)
