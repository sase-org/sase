"""Build copyable xprompt tags for active Patches."""

from __future__ import annotations

from dataclasses import dataclass

from sase.ace.patch import (
    find_all_patches,
    get_main_file_path,
    is_archive_file,
)
from sase.status_state_machine.constants import (
    ARCHIVE_STATUSES,
    remove_workspace_suffix,
)
from sase.workspace_provider import detect_workflow_type


@dataclass(frozen=True)
class PatchTagEntry:
    """A Patch with its corresponding VCS xprompt workflow tag."""

    project: str
    name: str
    status: str
    workflow_type: str
    tag: str


@dataclass(frozen=True)
class PatchTagListing:
    """Result of listing active Patch xprompt tags."""

    entries: list[PatchTagEntry]
    skipped: list[str]


def list_patch_xprompt_tags(project: str | None = None) -> PatchTagListing:
    """List active Patches and their copyable VCS xprompt tags.

    Terminal Patches are excluded after normalizing STATUS suffixes. The
    optional project filter is an exact match against the parsed project name.
    Entries with workflow detection failures are omitted and reported in
    ``skipped`` so callers can still show the rest of the list.
    """
    entries: list[PatchTagEntry] = []
    skipped: list[str] = []

    patches = sorted(
        find_all_patches(),
        key=lambda patch: (
            patch.project_basename,
            patch.name,
            remove_workspace_suffix(patch.status),
        ),
    )

    for patch in patches:
        project_name = patch.project_basename
        if project is not None and project_name != project:
            continue

        status = remove_workspace_suffix(patch.status)
        if status in ARCHIVE_STATUSES:
            continue

        project_file = _project_file_for_workflow(patch.file_path)
        try:
            workflow_type = detect_workflow_type(project_file)
        except Exception as exc:
            skipped.append(
                f"{project_name}/{patch.name}: could not detect workflow type: {exc}"
            )
            continue

        entries.append(
            PatchTagEntry(
                project=project_name,
                name=patch.name,
                status=status,
                workflow_type=workflow_type,
                tag=f"#{workflow_type}:{patch.name}",
            )
        )

    return PatchTagListing(entries=entries, skipped=skipped)


def _project_file_for_workflow(file_path: str) -> str:
    if is_archive_file(file_path):
        return get_main_file_path(file_path)
    return file_path
