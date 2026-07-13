"""Launch-time enablement helpers for known project refs."""

from __future__ import annotations

from collections.abc import Mapping

from sase.core.paths import sase_projects_dir
from sase.core.project_lifecycle_facade import list_project_records
from sase.core.project_lifecycle_wire import (
    ProjectRecordWire,
    is_disabled_project_lifecycle_state,
)


def _known_launch_records() -> dict[str, ProjectRecordWire]:
    projects_dir = sase_projects_dir()
    if not projects_dir.is_dir():
        return {}
    records = list_project_records(projects_dir, "all", include_home=False)
    return {
        record.project_name: record
        for record in records
        if record.is_project
        and record.project_name != "home"
        and not record.system_managed
    }


def _resolve_known_project_launch_record(
    ref: str,
    records: Mapping[str, ProjectRecordWire] | None = None,
) -> ProjectRecordWire | None:
    """Return the known lifecycle record for a launch ref, if any."""
    from sase.project_aliases import resolve_project_alias_ref
    from sase.xprompt._parsing import resolve_known_project_ref

    ref = resolve_project_alias_ref(ref)
    launch_records = records if records is not None else _known_launch_records()
    project_name = resolve_known_project_ref(ref, launch_records)
    if project_name is None:
        return None
    return launch_records.get(project_name)


def enable_known_project_for_launch_ref(ref: str) -> ProjectRecordWire | None:
    """Enable a known disabled project referenced by a launch ref.

    Unknown refs are ignored. Enabled records are returned without mutation.
    Enablement failures are raised as launch-friendly RuntimeErrors.
    """
    record = _resolve_known_project_launch_record(ref)
    if record is None:
        return None
    if not is_disabled_project_lifecycle_state(record.state):
        return record

    from sase.main.project_handler import set_project_state_locked

    try:
        return set_project_state_locked(record.project_name, "enabled")
    except Exception as exc:
        raise RuntimeError(
            f"failed to enable project '{record.project_name}' for launch: {exc}"
        ) from exc


def enable_known_project_vcs_refs_for_launch_prompt(prompt: str) -> tuple[str, ...]:
    """Enable every disabled known-project VCS ref in *prompt* once."""
    from sase.project_aliases import canonicalize_project_aliases_in_prompt
    from sase.xprompt._parsing import (
        iter_known_project_vcs_refs,
        resolve_known_project_ref,
    )

    prompt = canonicalize_project_aliases_in_prompt(prompt)
    records = _known_launch_records()
    refs = iter_known_project_vcs_refs(prompt, records)
    enabled: list[str] = []
    seen_projects: set[str] = set()
    for _workflow_type, ref in refs:
        project_name = resolve_known_project_ref(ref, records)
        if project_name is None or project_name in seen_projects:
            continue
        seen_projects.add(project_name)
        record = records[project_name]
        if not is_disabled_project_lifecycle_state(record.state):
            continue
        updated = enable_known_project_for_launch_ref(project_name)
        if updated is not None:
            enabled.append(updated.project_name)
    return tuple(enabled)


def extract_known_project_vcs_launch_ref(prompt: str) -> tuple[str, str] | None:
    """Return the first known-project VCS ref based on lifecycle records."""
    from sase.project_aliases import canonicalize_project_aliases_in_prompt
    from sase.xprompt._parsing import (
        extract_known_project_vcs_ref,
        iter_known_project_vcs_refs,
    )

    prompt = canonicalize_project_aliases_in_prompt(prompt)
    records = _known_launch_records()
    refs = iter_known_project_vcs_refs(prompt, records)
    if refs:
        return refs[0]
    return extract_known_project_vcs_ref(prompt, include_states="all")


activate_known_project_for_launch_ref = enable_known_project_for_launch_ref
activate_known_project_vcs_refs_for_launch_prompt = (
    enable_known_project_vcs_refs_for_launch_prompt
)


__all__ = [
    "activate_known_project_for_launch_ref",
    "activate_known_project_vcs_refs_for_launch_prompt",
    "enable_known_project_for_launch_ref",
    "enable_known_project_vcs_refs_for_launch_prompt",
    "extract_known_project_vcs_launch_ref",
]
