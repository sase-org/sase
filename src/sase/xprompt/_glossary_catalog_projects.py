"""Resolve which enabled project supplies glossary semantics for a workspace."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

from sase.core.project_lifecycle_wire import ProjectRecordWire, effective_project_name
from sase.xprompt._parsing_vcs_refs import resolve_known_project_ref


@dataclass(frozen=True, slots=True)
class EditorGlossaryProject:
    """The enabled project/workspace selected for glossary semantics."""

    key: str
    name: str
    aliases: tuple[str, ...]
    workspace_dir: Path

    def to_wire(self) -> dict[str, object]:
        return {
            "key": self.key,
            "name": self.name,
            "aliases": list(self.aliases),
            "workspace_dir": str(self.workspace_dir),
        }


def select_project(
    project_ref: str | None,
    records: Sequence[ProjectRecordWire],
    *,
    launch_workspace: str | Path | None,
) -> EditorGlossaryProject | None:
    if project_ref:
        record = _record_for_ref(project_ref, records)
        return None if record is None else project_from_record(record)

    record = glossary_project_record_for_workspace(launch_workspace, records)
    return None if record is None else project_from_record(record)


def glossary_project_record_for_workspace(
    launch_workspace: str | Path | None,
    records: Sequence[ProjectRecordWire],
) -> ProjectRecordWire | None:
    """Return the enabled record for *launch_workspace*, or CWD's.

    Resolution is cheapest-first: the record whose ProjectSpec workspace
    contains the path, then a managed-checkout marker, then the same CWD
    inference ``sase repo`` and ``sase workspace`` use. Shared by
    :func:`~sase.xprompt.glossary_catalog.editor_glossary_catalog_for_project`'s
    CWD-fallback resolution and the ACE glossary panel's project-ring builder,
    which needs the launch project even when it declares no glossary.
    """
    workspace = (
        Path(launch_workspace).expanduser()
        if launch_workspace is not None
        else _safe_cwd()
    )
    if workspace is None:
        return None
    record = _record_for_workspace(workspace, records)
    if record is not None:
        return record
    record = _record_for_checkout_marker(workspace, records)
    if record is not None:
        return record
    return _record_for_inferred_project(workspace, records)


def project_from_record(record: ProjectRecordWire) -> EditorGlossaryProject | None:
    if not record.workspace_dir:
        return None
    return EditorGlossaryProject(
        key=record.project_name,
        name=effective_project_name(record),
        aliases=tuple(dict.fromkeys(record.aliases)),
        workspace_dir=Path(record.workspace_dir).expanduser().resolve(strict=False),
    )


def sort_records_for_catalog(
    records: Iterable[ProjectRecordWire],
) -> list[ProjectRecordWire]:
    return sorted(
        records,
        key=lambda record: (
            effective_project_name(record).casefold(),
            record.project_name.casefold(),
        ),
    )


def _record_for_ref(
    project_ref: str,
    records: Sequence[ProjectRecordWire],
) -> ProjectRecordWire | None:
    folded = project_ref.casefold()
    for record in records:
        refs = (record.project_name, effective_project_name(record), *record.aliases)
        if any(ref.casefold() == folded for ref in refs if ref):
            return record

    known_projects = {
        record.project_name: Path(str(record.workspace_dir))
        for record in records
        if record.workspace_dir
    }
    resolved = resolve_known_project_ref(project_ref, known_projects)
    if resolved is None:
        return None
    return next(
        (record for record in records if record.project_name == resolved),
        None,
    )


def _record_for_workspace(
    workspace: Path,
    records: Sequence[ProjectRecordWire],
) -> ProjectRecordWire | None:
    try:
        resolved_workspace = workspace.resolve(strict=False)
    except (OSError, RuntimeError, ValueError):
        return None
    for record in records:
        if not record.workspace_dir:
            continue
        try:
            candidate = Path(record.workspace_dir).expanduser().resolve(strict=False)
        except (OSError, RuntimeError, ValueError):
            continue
        if _is_relative_to(resolved_workspace, candidate):
            return record
    return None


def _record_for_checkout_marker(
    workspace: Path,
    records: Sequence[ProjectRecordWire],
) -> ProjectRecordWire | None:
    """Join a managed-checkout marker to an enabled record, if any.

    The marker walker is imported lazily so ACE warmers and the LSP payload
    builder do not pull workspace-provider into this module's import graph.
    """
    try:
        from sase.workspace_provider import find_marker_from_cwd
    except Exception:
        return None
    try:
        found = find_marker_from_cwd(str(workspace))
    except Exception:
        return None
    if found is None:
        return None
    _, marker = found

    primary = marker.primary_workspace_dir.strip()
    if primary:
        record = _record_for_workspace(Path(primary).expanduser(), records)
        if record is not None:
            return record

    project_key = marker.project_key.strip()
    if project_key:
        record = _record_for_ref(project_key, records)
        if record is not None:
            return record

    project_name = marker.project_name.strip()
    if project_name:
        return _record_for_ref(project_name, records)
    return None


def _record_for_inferred_project(
    workspace: Path,
    records: Sequence[ProjectRecordWire],
) -> ProjectRecordWire | None:
    """Backstop via the canonical CWD project-name inference.

    Imported lazily for the same reason as :func:`_record_for_checkout_marker`.
    """
    try:
        from sase.bead.project_name import infer_project_name_from_cwd
    except Exception:
        return None
    try:
        inferred = infer_project_name_from_cwd(str(workspace))
    except Exception:
        return None
    if not inferred:
        return None
    return next(
        (record for record in records if record.project_name == inferred),
        None,
    )


def _safe_cwd() -> Path | None:
    try:
        return Path.cwd()
    except OSError:
        return None


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False
