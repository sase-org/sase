"""Build copyable xprompt tags for active ChangeSpecs."""

from __future__ import annotations

from dataclasses import dataclass

from sase.ace.changespec import (
    find_all_changespecs,
    get_main_file_path,
    is_archive_file,
)
from sase.status_state_machine.constants import (
    ARCHIVE_STATUSES,
    remove_workspace_suffix,
)
from sase.workspace_provider import detect_workflow_type


# pyvision: public_api_methods.txt
@dataclass(frozen=True)
class ChangeSpecTagEntry:
    """A ChangeSpec with its corresponding VCS xprompt workflow tag."""

    project: str
    name: str
    status: str
    workflow_type: str
    tag: str


# pyvision: public_api_methods.txt
@dataclass(frozen=True)
class ChangeSpecTagListing:
    """Result of listing active ChangeSpec xprompt tags."""

    entries: list[ChangeSpecTagEntry]
    skipped: list[str]


# pyvision: public_api_methods.txt
def list_changespec_xprompt_tags(project: str | None = None) -> ChangeSpecTagListing:
    """List active ChangeSpecs and their copyable VCS xprompt tags.

    Terminal ChangeSpecs are excluded after normalizing STATUS suffixes. The
    optional project filter is an exact match against the parsed project name.
    Entries with workflow detection failures are omitted and reported in
    ``skipped`` so callers can still show the rest of the list.
    """
    entries: list[ChangeSpecTagEntry] = []
    skipped: list[str] = []

    changespecs = sorted(
        find_all_changespecs(),
        key=lambda cs: (
            cs.project_basename,
            cs.name,
            remove_workspace_suffix(cs.status),
        ),
    )

    for cs in changespecs:
        project_name = cs.project_basename
        if project is not None and project_name != project:
            continue

        status = remove_workspace_suffix(cs.status)
        if status in ARCHIVE_STATUSES:
            continue

        project_file = _project_file_for_workflow(cs.file_path)
        try:
            workflow_type = detect_workflow_type(project_file)
        except Exception as exc:
            skipped.append(
                f"{project_name}/{cs.name}: could not detect workflow type: {exc}"
            )
            continue

        entries.append(
            ChangeSpecTagEntry(
                project=project_name,
                name=cs.name,
                status=status,
                workflow_type=workflow_type,
                tag=f"#{workflow_type}:{cs.name}",
            )
        )

    return ChangeSpecTagListing(entries=entries, skipped=skipped)


def _project_file_for_workflow(file_path: str) -> str:
    if is_archive_file(file_path):
        return get_main_file_path(file_path)
    return file_path
