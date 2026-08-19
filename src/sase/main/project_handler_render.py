"""Human and JSON rendering for ``sase project`` record output."""

from __future__ import annotations

from sase.core.project_lifecycle_wire import (
    ProjectRecordWire,
    effective_project_name,
    is_disabled_project_lifecycle_state,
    project_lifecycle_wire_to_json_dict,
)


def record_to_json_dict(record: ProjectRecordWire) -> dict[str, object]:
    """Return the JSON payload for one project lifecycle *record*."""
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


def print_records_table(records: list[ProjectRecordWire], state_filter: str) -> None:
    """Print the ``sase project list`` table for *records*."""
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


def print_record_detail(record: ProjectRecordWire) -> None:
    """Print the ``sase project show`` detail block for *record*."""
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


def alias_json_payload(record: ProjectRecordWire) -> dict[str, object]:
    """Return the JSON payload describing *record*'s aliases."""
    return {
        "project_name": record.project_name,
        "effective_project_name": effective_project_name(record),
        "display_name": record.display_name,
        "aliases": list(record.aliases),
    }


def print_alias_records(records: list[ProjectRecordWire]) -> None:
    """Print one alias line per record for ``sase project alias list``."""
    if not records:
        print("No project aliases.")
        return
    for record in records:
        print(f"{_project_display_label(record)}: {', '.join(record.aliases)}")


def print_alias_result(record: ProjectRecordWire) -> None:
    """Print *record*'s aliases after an alias mutation."""
    aliases = ", ".join(record.aliases) if record.aliases else "-"
    print(f"Project '{effective_project_name(record)}' aliases: {aliases}")
