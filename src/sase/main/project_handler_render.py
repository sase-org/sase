"""Human and JSON rendering for ``sase project`` record output."""

from __future__ import annotations

import os
import sys

from sase.core.project_lifecycle_wire import (
    ProjectRecordWire,
    effective_project_name,
    is_disabled_project_lifecycle_state,
    project_lifecycle_wire_to_json_dict,
)

_TAG_COLUMN_WIDTH = 16


def _tag_for_record(record: ProjectRecordWire) -> str | None:
    """Return the ``+<name>`` tag for *record*, or ``None`` (D1)."""
    try:
        from sase.project_tags.catalog import is_project_tag_name

        name = effective_project_name(record)
        return f"+{name}" if is_project_tag_name(name) else None
    except Exception:
        return None


def _accent_for_record(
    record: ProjectRecordWire,
    *,
    among: tuple[str, ...] | None = None,
) -> str | None:
    """Return the accent hex for *record*, or ``None`` (D6).

    Disabled projects and ``home`` carry no accent. Uses the D6 canonical
    ``among`` set when supplied, else a hash-only fallback so single-record
    callers never touch disk.
    """
    try:
        if record.project_name.casefold() == "home":
            return None
        if is_disabled_project_lifecycle_state(record.state):
            return None
        from sase.project_accents import project_accent

        if among is None:
            return project_accent(record.project_name)
        return project_accent(record.project_name, among=among)
    except Exception:
        return None


def among_for_records(
    records: list[ProjectRecordWire],
) -> tuple[str, ...]:
    """Return the D6 canonical accent set for *records* (fail-open)."""
    try:
        from sase.project_accents import accent_among_keys

        return accent_among_keys(records)
    except Exception:
        return ()


def _color_enabled() -> bool:
    """Return whether CLI color output is enabled."""
    try:
        if os.environ.get("NO_COLOR") is not None:
            return False
        return sys.stdout.isatty()
    except Exception:
        return False


def record_to_json_dict(
    record: ProjectRecordWire,
    *,
    among: tuple[str, ...] | None = None,
) -> dict[str, object]:
    """Return the JSON payload for one project lifecycle *record*."""
    data = project_lifecycle_wire_to_json_dict(record)
    if isinstance(data, dict):
        data["state_source"] = "explicit" if record.state_explicit else "defaulted"
        data["effective_project_name"] = effective_project_name(record)
        data["tag"] = _tag_for_record(record)
        data["workflow_type"] = record.vcs_kind
        data["accent"] = _accent_for_record(record, among=among)
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


def print_records_table(
    records: list[ProjectRecordWire],
    state_filter: str,
    *,
    among: tuple[str, ...] | None = None,
) -> None:
    """Print the ``sase project list`` table for *records*."""
    if not records:
        print(f"No {state_filter} projects.")
        return

    accent_among = among if among is not None else among_for_records(records)
    use_color = _color_enabled()

    print(
        f"{'PROJECT':<24} {'TAG':<{_TAG_COLUMN_WIDTH}} "
        f"{'STATE':<10} {'CLAIMS':>6} {'LAUNCH':<7} WORKSPACE"
    )
    if use_color:
        from rich.console import Console
        from rich.text import Text

        console = Console()
        for record in records:
            state = record.state + ("*" if record.state_explicit else "")
            launch = "yes" if record.launchable and record.state == "enabled" else "no"
            project_label = _project_display_label(record)
            tag = _tag_for_record(record) or "-"
            accent = _accent_for_record(record, among=accent_among)
            line = Text()
            line.append(f"{project_label:<24.24} ")
            if accent is not None and tag != "-":
                line.append(f"{tag:<{_TAG_COLUMN_WIDTH}}", style=accent)
            else:
                line.append(f"{tag:<{_TAG_COLUMN_WIDTH}}", style="dim")
            line.append(
                f" {state:<10} "
                f"{record.active_claim_count:>6} "
                f"{launch:<7} "
                f"{_workspace_display(record)}"
            )
            console.print(line, soft_wrap=True)
        return

    for record in records:
        state = record.state + ("*" if record.state_explicit else "")
        launch = "yes" if record.launchable and record.state == "enabled" else "no"
        project_label = _project_display_label(record)
        tag = _tag_for_record(record) or "-"
        print(
            f"{project_label:<24.24} "
            f"{tag:<{_TAG_COLUMN_WIDTH}} "
            f"{state:<10} "
            f"{record.active_claim_count:>6} "
            f"{launch:<7} "
            f"{_workspace_display(record)}"
        )


def print_record_detail(
    record: ProjectRecordWire,
    *,
    among: tuple[str, ...] | None = None,
) -> None:
    """Print the ``sase project show`` detail block for *record*."""
    source = "explicit" if record.state_explicit else "defaulted"
    launch = "yes" if record.launchable and record.state == "enabled" else "no"
    aliases = ", ".join(record.aliases) if record.aliases else "-"
    display = effective_project_name(record)
    print(f"Project: {display}")
    if display != record.project_name:
        print(f"Directory key: {record.project_name}")
    tag = _tag_for_record(record)
    accent = _accent_for_record(record, among=among)
    if tag is not None and _color_enabled() and accent is not None:
        from rich.console import Console
        from rich.text import Text

        line = Text()
        line.append("Tag: ")
        line.append(tag, style=f"bold {accent}")
        Console().print(line, soft_wrap=True)
    elif tag is not None:
        print(f"Tag: {tag}")
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
