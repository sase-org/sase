"""Handler implementation for the ``sase project`` CLI subcommand."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

from sase.ace.changespec import changespec_lock, write_changespec_atomic
from sase.ace.changespec.project_spec_path import preferred_project_spec_path
from sase.running_field._model import WorkspaceClaim
from sase.core.agent_launch_claims import list_workspace_claims_from_content
from sase.core.paths import is_valid_sase_project_name, sase_projects_dir
from sase.core.project_lifecycle_facade import (
    apply_project_lifecycle_update,
    list_project_records,
)
from sase.core.project_lifecycle_wire import (
    PROJECT_LIFECYCLE_STATES,
    ProjectRecordWire,
    effective_project_name,
    is_disabled_project_lifecycle_state,
    normalize_project_lifecycle_state,
    normalize_project_lifecycle_state_filter,
    project_lifecycle_wire_to_json_dict,
)
from sase.project_aliases import (
    ProjectAliasError,
    add_project_alias_locked as _add_project_alias_locked,
    clear_project_aliases_locked as _clear_project_aliases_locked,
    remove_project_alias_locked as _remove_project_alias_locked,
    resolve_project_alias_ref,
    set_project_aliases_locked,
)

_ALL_STATES = tuple(PROJECT_LIFECYCLE_STATES)
_LIVE_ARTIFACT_MARKERS = ("running.json", "waiting.json", "pending_question.json")


class _ProjectLifecycleError(RuntimeError):
    """Base class for project lifecycle command failures."""


class _ProjectLifecycleNotFoundError(_ProjectLifecycleError):
    """Raised when a requested project cannot be resolved."""


class _ProjectLifecycleBlockedError(_ProjectLifecycleError):
    """Raised when a lifecycle mutation is blocked by live work."""

    def __init__(
        self,
        project: str,
        state: str,
        claims: list[WorkspaceClaim],
        markers: list[Path],
    ) -> None:
        self.project = project
        self.state = state
        self.claims = claims
        self.markers = markers
        pieces: list[str] = []
        if claims:
            pieces.append(f"{len(claims)} RUNNING claim(s)")
        if markers:
            pieces.append(f"{len(markers)} live artifact marker(s)")
        live_summary = ", ".join(pieces) if pieces else "live work"
        if state == "delete":
            action = "remove live work before deleting it"
        else:
            action = f"pass --force to set state to {state}"
        super().__init__(f"project '{project}' has {live_summary}; {action}")


ProjectLifecycleError = _ProjectLifecycleError
ProjectLifecycleNotFoundError = _ProjectLifecycleNotFoundError
ProjectLifecycleBlockedError = _ProjectLifecycleBlockedError


def _states_for_filter(state_filter: str) -> list[str]:
    try:
        return normalize_project_lifecycle_state_filter(state_filter)
    except ValueError as exc:
        raise ValueError(f"invalid project state: {state_filter}") from exc


def _record_to_json_dict(record: ProjectRecordWire) -> dict[str, object]:
    data = project_lifecycle_wire_to_json_dict(record)
    if isinstance(data, dict):
        data["state_source"] = "explicit" if record.state_explicit else "defaulted"
        data["effective_project_name"] = effective_project_name(record)
        return data
    raise TypeError(f"unexpected project lifecycle record: {type(data)!r}")


def _workspace_display(record: ProjectRecordWire) -> str:
    return record.workspace_dir or "-"


def _archive_display(record: ProjectRecordWire) -> str:
    return record.archive_file or "-"


def _project_display_label(record: ProjectRecordWire) -> str:
    display = effective_project_name(record)
    if display == record.project_name:
        return display
    return f"{display} ({record.project_name})"


def _print_records_table(records: list[ProjectRecordWire], state_filter: str) -> None:
    if not records:
        print(f"No {state_filter} projects.")
        return

    print(f"{'PROJECT':<24} {'STATE':<10} {'CLAIMS':>6} {'LAUNCH':<7} WORKSPACE")
    for record in records:
        state = record.state + ("*" if record.state_explicit else "")
        launch = "yes" if record.launchable and record.state == "enabled" else "no"
        project_label = _project_display_label(record)
        print(
            f"{project_label:<24.24} "
            f"{state:<10} "
            f"{record.active_claim_count:>6} "
            f"{launch:<7} "
            f"{_workspace_display(record)}"
        )


def _print_record_detail(record: ProjectRecordWire) -> None:
    source = "explicit" if record.state_explicit else "defaulted"
    launch = "yes" if record.launchable and record.state == "enabled" else "no"
    aliases = ", ".join(record.aliases) if record.aliases else "-"
    display = effective_project_name(record)
    print(f"Project: {display}")
    if display != record.project_name:
        print(f"Directory key: {record.project_name}")
    print(f"State: {record.state} ({source})")
    print(f"VCS: {record.vcs_kind or '-'}")
    print(f"Aliases: {aliases}")
    print(f"Project file: {record.project_file}")
    print(f"Archive file: {_archive_display(record)}")
    print(f"Workspace: {_workspace_display(record)}")
    print(f"Active claims: {record.active_claim_count}")
    print(f"Launchable: {launch}")
    warnings = [*record.warnings, *record.parse_warnings]
    if warnings:
        print("Warnings:")
        for warning in warnings:
            print(f"  - {warning}")
    if is_disabled_project_lifecycle_state(record.state):
        print(f"Hint: run 'sase project enable {display}' before launching work.")


def _canonical_project_ref(
    project: str,
    projects_root: Path | None = None,
) -> str:
    if not is_valid_sase_project_name(project):
        raise _ProjectLifecycleError(f"invalid project name: {project!r}")
    root = (
        projects_root.expanduser() if projects_root is not None else sase_projects_dir()
    )
    try:
        return resolve_project_alias_ref(project, root)
    except (ProjectAliasError, ValueError) as exc:
        raise _ProjectLifecycleError(str(exc)) from exc


def _invalidate_project_identity(projects_root: Path | None = None) -> None:
    from sase.project_display_names import invalidate_project_display_snapshot

    invalidate_project_display_snapshot(projects_root)


def _get_project_record(
    project: str,
    *,
    projects_only: bool = True,
) -> ProjectRecordWire:
    canonical_project = _canonical_project_ref(project)

    records = list_project_records(
        sase_projects_dir(),
        list(_ALL_STATES),
        include_home=True,
    )
    for record in records:
        if (
            record.is_project or not projects_only
        ) and record.project_name == canonical_project:
            return record
    raise _ProjectLifecycleNotFoundError(f"project '{project}' was not found")


def _resolve_mutable_project_file(
    project: str,
    projects_root: Path | None = None,
) -> Path:
    root = (
        projects_root.expanduser() if projects_root is not None else sase_projects_dir()
    )
    project = _canonical_project_ref(project, root)
    if project == "home":
        raise _ProjectLifecycleError("project 'home' is system-managed")
    if not is_valid_sase_project_name(project):
        raise _ProjectLifecycleError(f"invalid project name: {project!r}")
    project_dir = root / project
    project_file = Path(preferred_project_spec_path(str(project_dir), project))
    if not project_file.is_file():
        raise _ProjectLifecycleNotFoundError(f"project '{project}' was not found")
    return project_file


def _resolve_deletable_project_dir(project: str, projects_root: Path) -> Path:
    project = _canonical_project_ref(project, projects_root)
    if project == "home":
        raise _ProjectLifecycleError("project 'home' is system-managed")
    if not is_valid_sase_project_name(project):
        raise _ProjectLifecycleError(f"invalid project name: {project!r}")

    root = projects_root.expanduser()
    root_resolved = root.resolve(strict=False)
    project_dir = root / project
    if project_dir.parent.resolve(strict=False) != root_resolved:
        raise _ProjectLifecycleError(
            f"project '{project}' is not a direct child of {root_resolved}"
        )
    if project_dir.is_symlink():
        raise _ProjectLifecycleError(
            f"project '{project}' is not an actual project directory"
        )
    if not project_dir.is_dir():
        raise _ProjectLifecycleNotFoundError(f"project '{project}' was not found")
    if project_dir.resolve(strict=True).parent != root_resolved:
        raise _ProjectLifecycleError(
            f"project '{project}' is not a direct child of {root_resolved}"
        )
    return project_dir


def _reject_system_managed_project(project: str, projects_root: Path) -> None:
    project = _canonical_project_ref(project, projects_root)
    if project == "home":
        raise _ProjectLifecycleError("project 'home' is system-managed")

    records = list_project_records(
        projects_root,
        list(_ALL_STATES),
        include_home=True,
    )
    for record in records:
        if record.project_name == project and record.system_managed:
            raise _ProjectLifecycleError(f"project '{project}' is system-managed")


def _live_artifact_marker_paths(project_dir: Path) -> list[Path]:
    artifacts_dir = project_dir / "artifacts"
    if not artifacts_dir.is_dir():
        return []

    markers: list[Path] = []
    for marker_name in _LIVE_ARTIFACT_MARKERS:
        markers.extend(
            path for path in artifacts_dir.rglob(marker_name) if path.is_file()
        )
    return sorted(markers)


def set_project_state_locked(
    project: str,
    state: str,
    *,
    force: bool = False,
) -> ProjectRecordWire:
    """Set lifecycle state for *project* while holding the ProjectSpec lock."""
    try:
        state = normalize_project_lifecycle_state(state)
    except ValueError as exc:
        raise _ProjectLifecycleError(f"invalid project state: {state}") from exc

    project = _canonical_project_ref(project)
    project_file = _resolve_mutable_project_file(project)
    with changespec_lock(str(project_file)):
        content = project_file.read_text(encoding="utf-8")
        claims = list_workspace_claims_from_content(content)
        markers = _live_artifact_marker_paths(project_file.parent)
        if (
            is_disabled_project_lifecycle_state(state)
            and not force
            and (claims or markers)
        ):
            raise _ProjectLifecycleBlockedError(project, state, claims, markers)

        updated = apply_project_lifecycle_update(content, state)
        write_changespec_atomic(
            str(project_file),
            updated,
            f"Set PROJECT_STATE to {state}",
        )

    _invalidate_project_identity()
    return _get_project_record(project, projects_only=False)


def delete_project_locked(
    project: str,
    *,
    projects_root: Path | None = None,
) -> Path:
    """Delete a SASE project state directory while holding the ProjectSpec lock."""
    root = (
        projects_root.expanduser() if projects_root is not None else sase_projects_dir()
    )
    project = _canonical_project_ref(project, root)
    project_dir = _resolve_deletable_project_dir(project, root)
    _reject_system_managed_project(project, root)
    project_file = Path(preferred_project_spec_path(str(project_dir), project))

    with changespec_lock(str(project_file)):
        project_dir = _resolve_deletable_project_dir(project, root)
        _reject_system_managed_project(project, root)
        project_file = Path(preferred_project_spec_path(str(project_dir), project))
        markers = _live_artifact_marker_paths(project_dir)
        claims: list[WorkspaceClaim] = []
        if project_file.is_file():
            content = project_file.read_text(encoding="utf-8")
            claims = list_workspace_claims_from_content(content)
        if claims or markers:
            raise _ProjectLifecycleBlockedError(project, "delete", claims, markers)

        shutil.rmtree(project_dir)

    _invalidate_project_identity(root)
    return project_dir


def _alias_json_payload(record: ProjectRecordWire) -> dict[str, object]:
    return {
        "project_name": record.project_name,
        "effective_project_name": effective_project_name(record),
        "display_name": record.display_name,
        "aliases": list(record.aliases),
    }


def _print_alias_records(records: list[ProjectRecordWire]) -> None:
    if not records:
        print("No project aliases.")
        return
    for record in records:
        print(f"{_project_display_label(record)}: {', '.join(record.aliases)}")


def _print_alias_result(record: ProjectRecordWire) -> None:
    aliases = ", ".join(record.aliases) if record.aliases else "-"
    print(f"Project '{effective_project_name(record)}' aliases: {aliases}")


def _handle_alias_list(args: argparse.Namespace) -> int:
    project = getattr(args, "project", None)
    try:
        if project:
            record = _get_project_record(str(project))
            if args.json:
                print(json.dumps(_alias_json_payload(record), indent=2, sort_keys=True))
            else:
                _print_alias_result(record)
            return 0

        records = [
            record
            for record in list_project_records(
                sase_projects_dir(),
                list(_ALL_STATES),
                include_home=False,
            )
            if record.is_project and not record.system_managed and record.aliases
        ]
    except (_ProjectLifecycleError, ImportError, AttributeError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    if args.json:
        print(
            json.dumps(
                [_alias_json_payload(record) for record in records],
                indent=2,
                sort_keys=True,
            )
        )
    else:
        _print_alias_records(records)
    return 0


def _handle_alias_add(args: argparse.Namespace) -> int:
    try:
        record = _add_project_alias_locked(str(args.project), str(args.alias))
    except (
        ValueError,
        ProjectAliasError,
        _ProjectLifecycleError,
        ImportError,
        AttributeError,
    ) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    _print_alias_result(record)
    return 0


def _handle_alias_remove(args: argparse.Namespace) -> int:
    try:
        record = _remove_project_alias_locked(str(args.project), str(args.alias))
    except (
        ValueError,
        ProjectAliasError,
        _ProjectLifecycleError,
        ImportError,
        AttributeError,
    ) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    _print_alias_result(record)
    return 0


def _handle_alias_clear(args: argparse.Namespace) -> int:
    try:
        record = _clear_project_aliases_locked(str(args.project))
    except (
        ValueError,
        ProjectAliasError,
        _ProjectLifecycleError,
        ImportError,
        AttributeError,
    ) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    _print_alias_result(record)
    return 0


_ALIAS_HANDLERS = {
    "list": _handle_alias_list,
    "add": _handle_alias_add,
    "remove": _handle_alias_remove,
    "clear": _handle_alias_clear,
}


def _handle_alias(args: argparse.Namespace) -> int:
    sub = getattr(args, "alias_subcommand", None)
    handler = _ALIAS_HANDLERS.get(sub) if isinstance(sub, str) else None
    if handler is None:
        print(
            "Usage: sase project alias {add,clear,list,remove}",
            file=sys.stderr,
        )
        return 2
    return handler(args)


def _handle_list(args: argparse.Namespace) -> int:
    state_filter = str(args.state)
    try:
        records = list_project_records(
            sase_projects_dir(),
            _states_for_filter(state_filter),
            include_home=False,
        )
        records = [record for record in records if record.is_project]
    except (ValueError, _ProjectLifecycleError, ImportError, AttributeError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    if args.json:
        print(
            json.dumps(
                [_record_to_json_dict(record) for record in records],
                indent=2,
                sort_keys=True,
            )
        )
    else:
        _print_records_table(records, state_filter)
    return 0


def _handle_show(args: argparse.Namespace) -> int:
    try:
        record = _get_project_record(str(args.project))
    except (_ProjectLifecycleError, ImportError, AttributeError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(_record_to_json_dict(record), indent=2, sort_keys=True))
    else:
        _print_record_detail(record)
    return 0


def _set_and_print(args: argparse.Namespace, state: str) -> int:
    try:
        record = set_project_state_locked(
            str(args.project),
            state,
            force=bool(args.force),
        )
    except (_ProjectLifecycleError, ImportError, AttributeError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    display = effective_project_name(record)
    print(f"Project '{display}' state is now {record.state}.")
    if is_disabled_project_lifecycle_state(record.state):
        print(f"Run 'sase project enable {display}' before launching new work.")
    return 0


def _handle_set_state(args: argparse.Namespace) -> int:
    return _set_and_print(args, str(args.state))


def _handle_enable(args: argparse.Namespace) -> int:
    return _set_and_print(args, "enabled")


def _handle_disable(args: argparse.Namespace) -> int:
    return _set_and_print(args, "disabled")


def _handle_activate(args: argparse.Namespace) -> int:
    return _handle_enable(args)


def _handle_deactivate(args: argparse.Namespace) -> int:
    return _handle_disable(args)


def _handle_archive(args: argparse.Namespace) -> int:
    return _handle_disable(args)


def _handle_close(args: argparse.Namespace) -> int:
    return _handle_disable(args)


_HANDLERS = {
    "alias": _handle_alias,
    "list": _handle_list,
    "show": _handle_show,
    "set-state": _handle_set_state,
    "disable": _handle_disable,
    "enable": _handle_enable,
    "activate": _handle_activate,
    "deactivate": _handle_deactivate,
    "archive": _handle_archive,
    "close": _handle_close,
}


def handle_project_command(args: argparse.Namespace) -> None:
    """Dispatch a parsed ``sase project ...`` command to its handler."""
    sub = getattr(args, "project_subcommand", None)
    handler = _HANDLERS.get(sub) if isinstance(sub, str) else None
    if handler is None:
        print(
            "Usage: sase project {alias,disable,enable,list,set-state,show}",
            file=sys.stderr,
        )
        sys.exit(2)
    sys.exit(handler(args))
