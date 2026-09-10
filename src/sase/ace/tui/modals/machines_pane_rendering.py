"""Rendering helpers for the Admin Center Machines pane."""

from __future__ import annotations

import platform

from rich.text import Text
from textual.widgets.option_list import Option

from sase.ace.tui.keymaps import MachinesPaneKeymaps
from sase.ace.tui.models.agent_runner_slots import format_capacity_value
from sase.config import get_agent_owner_config_snapshot, get_max_running_agents
from sase.core.time import format_local

from .machines_pane_keybindings import primary_key_display
from .machines_pane_types import MachineFlow, MachineRow, MachineStatusSnapshot

_ALIAS_WIDTH = 18
_STATE_WIDTH = 13
_HEALTH_WIDTH = 15
_CAPACITY_WIDTH = 18
_OBSERVED_WIDTH = 19


def local_machine_label() -> str:
    try:
        snapshot = get_agent_owner_config_snapshot()
        if snapshot.owner is not None:
            return snapshot.owner.machine_name
        if snapshot.selector:
            return snapshot.selector
    except Exception:
        pass
    return platform.node() or "here"


def column_header_text() -> Text:
    text = Text(style="bold dim")
    text.append(f"{'ALIAS':<{_ALIAS_WIDTH}}")
    text.append(f"{'STATE':<{_STATE_WIDTH}}")
    text.append(f"{'HEALTH':<{_HEALTH_WIDTH}}")
    text.append(f"{'CAPACITY':<{_CAPACITY_WIDTH}}")
    text.append(f"{'LAST OBSERVED':<{_OBSERVED_WIDTH}}")
    text.append("ENDPOINT")
    return text


def _record_label(
    row: MachineRow,
    statuses: dict[str, MachineStatusSnapshot],
) -> Text:
    snapshot = statuses.get(row.alias)
    health, health_style = _health_label(row, snapshot)
    state = "here" if row.kind == "here" else _state_label(row, snapshot)
    text = Text()
    text.append(f"{row.alias:<{_ALIAS_WIDTH}.{_ALIAS_WIDTH}}", style="bold")
    text.append(f"{state:<{_STATE_WIDTH}.{_STATE_WIDTH}}", style=_state_style(state))
    text.append(f"{health:<{_HEALTH_WIDTH}.{_HEALTH_WIDTH}}", style=health_style)
    text.append(f"{_capacity_label(row):<{_CAPACITY_WIDTH}.{_CAPACITY_WIDTH}}")
    text.append(
        f"{_observed_label(row, snapshot):<{_OBSERVED_WIDTH}.{_OBSERVED_WIDTH}}",
        style="dim",
    )
    text.append(_endpoint_label(row), style="dim")
    return text


def create_options(
    filtered_records: list[MachineRow],
    records: list[MachineRow],
    statuses: dict[str, MachineStatusSnapshot],
    *,
    loading: bool,
    text_filter: str,
) -> list[Option]:
    if not filtered_records:
        if loading and not records:
            message = "Loading machine inventory..."
        elif text_filter.strip():
            message = "No machines match the current search"
        else:
            message = "No machine rows available"
        return [Option(Text(message, style="dim"), id="empty")]
    return [
        Option(_record_label(record, statuses), id=record.identity)
        for record in filtered_records
    ]


def summary_text(
    records: list[MachineRow],
    statuses: dict[str, MachineStatusSnapshot],
    *,
    checking_alias: str,
    loading: bool,
    load_error: str,
) -> Text:
    remotes = [row for row in records if row.kind == "remote"]
    ok = sum(
        1
        for row in remotes
        if (snapshot := statuses.get(row.alias)) is not None and snapshot.status.ok
    )
    unknown = len([row for row in remotes if row.alias not in statuses])
    errors = sum(
        1
        for row in remotes
        if (snapshot := statuses.get(row.alias)) is not None and not snapshot.status.ok
    )
    text = Text()
    text.append("machines:", style="dim")
    text.append(str(1 + len(remotes)), style="bold")
    text.append("  ·  enrolled:", style="dim")
    text.append(str(len(remotes)), style="bold #87D7FF")
    text.append("  ·  ok:", style="dim")
    text.append(str(ok), style="bold #00D7AF")
    text.append("  ·  unknown:", style="dim")
    text.append(str(unknown), style="bold #FFD700")
    if errors:
        text.append("  ·  issues:", style="dim")
        text.append(str(errors), style="bold red")
    if checking_alias:
        text.append(f"  ·  checking {checking_alias}...", style="#87D7FF")
    if loading:
        text.append("  ·  refreshing...", style="#87D7FF")
    if load_error:
        text.append(f"  ·  {load_error}", style="bold red")
    return text


def detail_text(
    row: MachineRow | None,
    statuses: dict[str, MachineStatusSnapshot],
    last_success_by_alias: dict[str, float],
) -> Text:
    text = Text()
    if row is None:
        text.append("No machine selected", style="dim")
        return text
    snapshot = statuses.get(row.alias)
    text.append(row.alias, style="bold")
    text.append("   ")
    text.append("local controller" if row.kind == "here" else "enrolled origin")
    text.append("\nHealth: ", style="dim")
    text.append(_health_label(row, snapshot)[0], style=_health_label(row, snapshot)[1])
    text.append("    Last successful observation: ", style="dim")
    text.append(_last_success_label(row, snapshot, last_success_by_alias))
    text.append("\nCapacity: ", style="dim")
    text.append(_capacity_label(row))
    text.append("\nCapabilities: ", style="dim")
    text.append(_capabilities_label(snapshot))
    if row.record is not None:
        record = row.record
        text.append("\nEndpoint: ", style="dim")
        text.append(record.endpoint)
        text.append("    Provider: ", style="dim")
        text.append(record.provider_ref)
        text.append("\nPinned installation: ", style="dim")
        text.append(record.pinned_installation_id)
        if record.quarantined:
            text.append("\nQuarantine: ", style="bold red")
            text.append(
                record.quarantine_reason or "installation quarantined", style="red"
            )
    if snapshot is not None:
        status = snapshot.status
        text.append("\nStatus message: ", style="dim")
        text.append(status.message or "-")
        if status.machine_selector:
            text.append("    Selector: ", style="dim")
            text.append(status.machine_selector)
        text.append("\nChecked: ", style="dim")
        text.append(format_local(snapshot.checked_at, "%Y-%m-%d %H:%M:%S", default="-"))
    return text


def flow_text(flow: MachineFlow | None) -> Text:
    text = Text()
    if flow is None:
        text.append("Choose an action for the selected machine.", style="dim")
        return text
    text.append(flow.title, style="bold")
    for line in flow.body:
        text.append(f"\n{line}")
    if flow.commands:
        text.append("\n\nCommands", style="bold")
        for command in flow.commands:
            text.append("\n  ")
            text.append(command, style="#87D7FF")
    return text


def connect_flow() -> MachineFlow:
    return MachineFlow(
        title="Connect a machine",
        body=(
            "Prepare the target, issue a bootstrap bundle into a protected file, review it on this controller, activate, then verify.",
            "Bootstrap bytes stay in the protected file path; do not paste them into prompts, argv, logs, or notes.",
            "If setup partially succeeds, rerun the controller command with the same protected file to resume at the recovery step.",
        ),
        commands=(
            "sase machine bootstrap --json > /path/protected/sase-bootstrap.json",
            "sase machine init -B /path/protected/sase-bootstrap.json",
            "sase machine status <alias>",
        ),
    )


def repair_flow(alias: str) -> MachineFlow:
    return MachineFlow(
        title=f"Repair {alias}",
        body=(
            "Repair rotates this controller's enrollment with a fresh one-time bundle.",
            "Changed installation identity must be reviewed and activated; cached rows are not rebound just because the alias matches.",
        ),
        commands=(
            f"sase machine bootstrap --json > /path/protected/sase-{alias}-bootstrap.json",
            f"sase machine repair {alias} -B /path/protected/sase-{alias}-bootstrap.json",
            f"sase machine status {alias}",
        ),
    )


def hints_text(keymaps: MachinesPaneKeymaps) -> str:
    d = primary_key_display
    return (
        f"{d(keymaps.next_option)}/{d(keymaps.prev_option)} move  "
        f"{d(keymaps.focus_filter)} filter  {d(keymaps.connect_machine)} connect  "
        f"{d(keymaps.check_status)} status  {d(keymaps.show_agents)} agents  "
        f"{d(keymaps.copy_command)} copy command"
    )


def _last_success_label(
    row: MachineRow,
    snapshot: MachineStatusSnapshot | None,
    last_success_by_alias: dict[str, float],
) -> str:
    if row.kind == "here":
        return "local"
    if snapshot is not None and snapshot.status.ok:
        return format_local(snapshot.checked_at, "%Y-%m-%d %H:%M:%S", default="-")
    last_ok = last_success_by_alias.get(row.alias)
    if last_ok is not None:
        return format_local(last_ok, "%Y-%m-%d %H:%M:%S", default="-")
    return "not observed in this session"


def _state_label(
    row: MachineRow,
    snapshot: MachineStatusSnapshot | None,
) -> str:
    if row.record is not None and row.record.quarantined:
        return "quarantined"
    if snapshot is None:
        return "not checked"
    return snapshot.status.state


def _state_style(state: str) -> str:
    if state in {"here", "ok"}:
        return "#00D7AF"
    if state in {"not checked", "skipped"}:
        return "#FFD700"
    return "bold red"


def _health_label(
    row: MachineRow,
    snapshot: MachineStatusSnapshot | None,
) -> tuple[str, str]:
    if row.kind == "here":
        return "local", "#00D7AF"
    if row.record is not None and row.record.quarantined:
        return "quarantined", "bold red"
    if snapshot is None:
        return "unknown", "#FFD700"
    if snapshot.status.ok:
        return "hello ok", "#00D7AF"
    return snapshot.status.state, "bold red"


def _capacity_label(row: MachineRow) -> str:
    if row.kind == "here":
        try:
            return (
                "local capacity "
                f"{format_capacity_value(float(get_max_running_agents()))}"
            )
        except Exception:
            return "local capacity unknown"
    return "not reported"


def _observed_label(
    row: MachineRow,
    snapshot: MachineStatusSnapshot | None,
) -> str:
    if row.kind == "here":
        return "local"
    if snapshot is None:
        return "never checked"
    return format_local(snapshot.checked_at, "%H:%M:%S", default="-")


def _endpoint_label(row: MachineRow) -> str:
    if row.kind == "here":
        return "local controller"
    return row.record.endpoint if row.record is not None else "-"


def _capabilities_label(snapshot: MachineStatusSnapshot | None) -> str:
    if snapshot is None or not snapshot.status.capabilities:
        return "not reported"
    groups: list[str] = []
    for name, values in sorted(snapshot.status.capabilities.items()):
        if values:
            groups.append(f"{name}: {', '.join(values)}")
        else:
            groups.append(name)
    return "; ".join(groups)


def row_haystack(row: MachineRow) -> str:
    record = row.record
    return " ".join(
        part
        for part in (
            row.alias,
            row.kind,
            record.provider_ref if record is not None else "",
            record.endpoint if record is not None else "",
            record.pinned_installation_id if record is not None else "",
            "quarantined" if record is not None and record.quarantined else "",
        )
        if part
    )


__all__ = [
    "column_header_text",
    "connect_flow",
    "create_options",
    "detail_text",
    "flow_text",
    "hints_text",
    "local_machine_label",
    "repair_flow",
    "row_haystack",
    "summary_text",
]
