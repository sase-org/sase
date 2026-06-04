"""Handler implementation for the ``sase project`` CLI subcommand."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from collections.abc import Callable
from pathlib import Path

from sase.ace.changespec import changespec_lock, write_changespec_atomic
from sase.ace.changespec.project_spec_path import preferred_project_spec_path
from sase.running_field._model import WorkspaceClaim
from sase.core.agent_launch_claims import list_workspace_claims_from_content
from sase.core.paths import is_valid_sase_project_name, sase_projects_dir
from sase.core.project_lifecycle_facade import (
    apply_project_aliases_update,
    apply_project_lifecycle_update,
    list_project_records,
)
from sase.core.project_lifecycle_wire import (
    PROJECT_LIFECYCLE_STATES,
    ProjectRecordWire,
    is_inactive_project_lifecycle_state,
    normalize_project_lifecycle_state,
    normalize_project_lifecycle_state_filter,
    project_lifecycle_wire_to_json_dict,
)
from sase.project_aliases import validate_project_aliases

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
        return data
    raise TypeError(f"unexpected project lifecycle record: {type(data)!r}")


def _workspace_display(record: ProjectRecordWire) -> str:
    return record.workspace_dir or "-"


def _archive_display(record: ProjectRecordWire) -> str:
    return record.archive_file or "-"


def _print_records_table(records: list[ProjectRecordWire], state_filter: str) -> None:
    if not records:
        print(f"No {state_filter} projects.")
        return

    print(f"{'PROJECT':<24} {'STATE':<10} {'CLAIMS':>6} {'LAUNCH':<7} WORKSPACE")
    for record in records:
        state = record.state + ("*" if record.state_explicit else "")
        launch = "yes" if record.launchable and record.state == "active" else "no"
        print(
            f"{record.project_name:<24} "
            f"{state:<10} "
            f"{record.active_claim_count:>6} "
            f"{launch:<7} "
            f"{_workspace_display(record)}"
        )


def _print_record_detail(record: ProjectRecordWire) -> None:
    source = "explicit" if record.state_explicit else "defaulted"
    launch = "yes" if record.launchable and record.state == "active" else "no"
    aliases = ", ".join(record.aliases) if record.aliases else "-"
    print(f"Project: {record.project_name}")
    print(f"State: {record.state} ({source})")
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
    if is_inactive_project_lifecycle_state(record.state):
        print(
            f"Hint: run 'sase project activate {record.project_name}' "
            "before launching work."
        )


def _get_project_record(project: str) -> ProjectRecordWire:
    if not is_valid_sase_project_name(project):
        raise _ProjectLifecycleError(f"invalid project name: {project!r}")

    records = list_project_records(
        sase_projects_dir(),
        list(_ALL_STATES),
        include_home=True,
    )
    for record in records:
        if record.project_name == project:
            return record
    raise _ProjectLifecycleNotFoundError(f"project '{project}' was not found")


def _get_project_record_from_records(
    records: list[ProjectRecordWire],
    project: str,
) -> ProjectRecordWire:
    for record in records:
        if record.project_name == project:
            return record
    raise _ProjectLifecycleNotFoundError(f"project '{project}' was not found")


def _resolve_mutable_project_file(project: str) -> Path:
    if project == "home":
        raise _ProjectLifecycleError("project 'home' is system-managed")
    if not is_valid_sase_project_name(project):
        raise _ProjectLifecycleError(f"invalid project name: {project!r}")

    project_dir = sase_projects_dir() / project
    project_file = Path(preferred_project_spec_path(str(project_dir), project))
    if not project_file.is_file():
        raise _ProjectLifecycleNotFoundError(f"project '{project}' was not found")
    return project_file


def _reject_system_managed_record(record: ProjectRecordWire) -> None:
    if record.system_managed:
        raise _ProjectLifecycleError(
            f"project '{record.project_name}' is system-managed"
        )


def _resolve_deletable_project_dir(project: str, projects_root: Path) -> Path:
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

    project_file = _resolve_mutable_project_file(project)
    with changespec_lock(str(project_file)):
        content = project_file.read_text(encoding="utf-8")
        claims = list_workspace_claims_from_content(content)
        markers = _live_artifact_marker_paths(project_file.parent)
        if (
            is_inactive_project_lifecycle_state(state)
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

    return _get_project_record(project)


def delete_project_locked(
    project: str,
    *,
    projects_root: Path | None = None,
) -> Path:
    """Delete a SASE project state directory while holding the ProjectSpec lock."""
    root = (
        projects_root.expanduser() if projects_root is not None else sase_projects_dir()
    )
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

    return project_dir


def _alias_json_payload(record: ProjectRecordWire) -> dict[str, object]:
    return {
        "project_name": record.project_name,
        "aliases": list(record.aliases),
    }


def _print_alias_records(records: list[ProjectRecordWire]) -> None:
    if not records:
        print("No project aliases.")
        return
    for record in records:
        print(f"{record.project_name}: {', '.join(record.aliases)}")


def _print_alias_result(record: ProjectRecordWire) -> None:
    aliases = ", ".join(record.aliases) if record.aliases else "-"
    print(f"Project '{record.project_name}' aliases: {aliases}")


def _validate_alias_arg(alias: str) -> None:
    if not is_valid_sase_project_name(alias):
        raise _ProjectLifecycleError(f"invalid project alias: {alias!r}")


def _mutate_project_aliases_locked(
    project: str,
    update_aliases: Callable[[list[str]], list[str]],
    commit_msg: str,
) -> ProjectRecordWire:
    project_file = _resolve_mutable_project_file(project)
    with changespec_lock(str(project_file)):
        records = list_project_records(
            sase_projects_dir(),
            list(_ALL_STATES),
            include_home=True,
        )
        record = _get_project_record_from_records(records, project)
        _reject_system_managed_record(record)
        aliases = validate_project_aliases(
            record.project_name,
            update_aliases(list(record.aliases)),
            records,
        )
        content = project_file.read_text(encoding="utf-8")
        updated = apply_project_aliases_update(content, aliases)
        write_changespec_atomic(str(project_file), updated, commit_msg)

    return _get_project_record(project)


def set_project_aliases_locked(project: str, aliases: list[str]) -> ProjectRecordWire:
    """Replace aliases for *project* while holding the ProjectSpec lock."""
    return _mutate_project_aliases_locked(
        project,
        lambda _current: list(aliases),
        "Set project aliases",
    )


def _add_project_alias_locked(project: str, alias: str) -> ProjectRecordWire:
    """Add *alias* to *project* while holding the ProjectSpec lock."""
    _validate_alias_arg(alias)
    return _mutate_project_aliases_locked(
        project,
        lambda aliases: [*aliases, alias],
        f"Add project alias {alias}",
    )


def _remove_project_alias_locked(project: str, alias: str) -> ProjectRecordWire:
    """Remove *alias* from *project* while holding the ProjectSpec lock."""
    _validate_alias_arg(alias)
    return _mutate_project_aliases_locked(
        project,
        lambda aliases: [item for item in aliases if item != alias],
        f"Remove project alias {alias}",
    )


def _clear_project_aliases_locked(project: str) -> ProjectRecordWire:
    """Remove all aliases from *project* while holding the ProjectSpec lock."""
    return set_project_aliases_locked(project, [])


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
            if not record.system_managed and record.aliases
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

    print(f"Project '{record.project_name}' state is now {record.state}.")
    if is_inactive_project_lifecycle_state(record.state):
        print(
            f"Run 'sase project activate {record.project_name}' before "
            "launching new work."
        )
    return 0


def _handle_set_state(args: argparse.Namespace) -> int:
    return _set_and_print(args, str(args.state))


def _handle_activate(args: argparse.Namespace) -> int:
    return _set_and_print(args, "active")


def _handle_deactivate(args: argparse.Namespace) -> int:
    return _set_and_print(args, "inactive")


def _handle_archive(args: argparse.Namespace) -> int:
    return _set_and_print(args, "inactive")


def _handle_close(args: argparse.Namespace) -> int:
    return _set_and_print(args, "inactive")


_HANDLERS = {
    "alias": _handle_alias,
    "list": _handle_list,
    "show": _handle_show,
    "set-state": _handle_set_state,
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
            "Usage: sase project {alias,list,show,set-state,activate,deactivate}",
            file=sys.stderr,
        )
        sys.exit(2)
    sys.exit(handler(args))
