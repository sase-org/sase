"""Keyboard-first view of the authoritative machine capacity report."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Literal

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Container, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import OptionList, Static
from textual.widgets.option_list import Option

from sase.ace.tui.actions.clipboard import schedule_copy_delivery
from sase.core.runner_slots import capacity_view

from .base import CopyModeForwardingMixin, OptionListNavigationMixin

_OPTION_LIST_ID = "capacity-inspector-options"
_DEFAULT_IDLE_GROUP_LIMIT = 10


@dataclass(frozen=True, slots=True)
class CapacityInspectorSelection:
    """Agent selected for a jump from the capacity inspector."""

    name: str
    artifact_dir: str


@dataclass(frozen=True, slots=True)
class _OptionAction:
    kind: Literal["jump", "toggle_group"]
    name: str | None = None
    artifact_dir: str | None = None
    group_code: str | None = None


class CapacityInspectorModal(
    CopyModeForwardingMixin,
    OptionListNavigationMixin,
    ModalScreen[CapacityInspectorSelection | None],
):
    """Render the shared capacity view with selectable agent rows."""

    _option_list_id = _OPTION_LIST_ID
    BINDINGS = [
        *OptionListNavigationMixin.NAVIGATION_BINDINGS,
        ("enter", "select_highlighted", "Jump or expand"),
        ("y", "copy_snapshot", "Copy snapshot"),
    ]

    def __init__(
        self,
        report: Any | None,
        *,
        running_nodes: int | None,
    ) -> None:
        super().__init__()
        self._report = report
        self._running_nodes = running_nodes
        self._expanded_idle_groups: set[str] = set()
        self._view: Any | None = None
        self._option_actions: dict[str, _OptionAction] = {}
        self._next_option_id = 0
        self._project_view()

    @property
    def report(self) -> Any | None:
        """Return the newest report currently displayed."""
        return self._report

    @property
    def running_nodes(self) -> int | None:
        """Return the display-derived running node count."""
        return self._running_nodes

    def compose(self) -> ComposeResult:
        with Container(id="capacity-inspector-container"):
            yield Static(self._title_text(), id="capacity-inspector-title")
            yield Static(self._summary_text(), id="capacity-inspector-summary")
            with VerticalScroll(id="capacity-inspector-scroll"):
                yield OptionList(*self._build_options(), id=_OPTION_LIST_ID)
            yield Static(
                "j/k move · Enter jump or expand · y copy `sase agent load -j` · Esc close",
                id="capacity-inspector-footer",
            )

    def on_mount(self) -> None:
        self.query_one(f"#{_OPTION_LIST_ID}", OptionList).focus()

    def update_capacity_report(
        self,
        report: Any,
        *,
        running_nodes: int | None,
    ) -> None:
        """Install a newly arrived report without re-reading capacity inputs."""
        self._report = report
        self._running_nodes = running_nodes
        self._project_view()
        self._refresh_widgets()

    def action_select_highlighted(self) -> None:
        options = self.query_one(f"#{_OPTION_LIST_ID}", OptionList)
        index = options.highlighted
        if index is None or index < 0 or index >= len(options.options):
            return
        option_id = options.options[index].id
        if option_id is not None:
            self._activate_option(option_id)

    def action_copy_snapshot(self) -> None:
        if self._report is None:
            self.notify(
                "Capacity report is not ready to copy",
                severity="warning",
            )
            return
        from sase.core.runner_slots import machine_capacity_report_to_json_dict

        payload = (
            json.dumps(
                machine_capacity_report_to_json_dict(self._report),
                indent=2,
            )
            + "\n"
        )
        schedule_copy_delivery(
            self,
            payload,
            copied_label="capacity snapshot (sase agent load -j)",
            task_name="sase-copy-capacity-snapshot",
        )

    def on_option_list_option_selected(
        self,
        event: OptionList.OptionSelected,
    ) -> None:
        event.stop()
        if event.option.id is not None:
            self._activate_option(event.option.id)

    def _project_view(self) -> None:
        self._view = (
            None
            if self._report is None
            else capacity_view(
                self._report,
                running_nodes=self._running_nodes,
                expanded_idle_groups=self._expanded_idle_groups,
            )
        )

    def _title_text(self) -> Text:
        text = Text("CAPACITY INSPECTOR", style="bold #87D7FF")
        if self._report is not None:
            machine = getattr(self._report, "machine", None)
            if isinstance(machine, str) and machine:
                text.append(f"  ·  {machine}", style="dim")
        return text

    def _summary_text(self) -> Text:
        view = self._view
        if view is None:
            return Text(
                "Authoritative capacity report is loading.\n"
                "This inspector waits for the shared report; it does not estimate "
                "capacity from visible rows.",
                style="yellow",
            )

        headline_style = (
            "bold red"
            if view.over_limit_note is not None
            else "bold yellow"
            if view.admission_blocked
            else "bold green"
        )
        text = Text(view.headline, style=headline_style)
        text.append(f"\n{view.limit_line}", style="dim")
        text.append(f"\n{view.snapshot_line}", style="dim")
        if view.running_line is not None:
            text.append(f"\n{view.running_line}", style="dim")
        if view.over_limit_note is not None:
            text.append(f"\n▲ {view.over_limit_note}", style="bold red")
        if view.admission_blocked:
            text.append(
                "\nAdmission blocked: accounting is invalid; the occupied value is "
                "a known subtotal, not free capacity.",
                style="bold red",
            )
        if view.accounting_unavailable:
            text.append(
                "\nCapacity accounting unavailable: this core cannot explain "
                "individual holders yet.",
                style="bold yellow",
            )
        return text

    def _build_options(self) -> list[Option]:
        self._option_actions = {}
        self._next_option_id = 0
        if self._view is None:
            return [
                Option(
                    "  Waiting for the first authoritative report…",
                    id="capacity-waiting",
                    disabled=True,
                )
            ]

        view = self._view
        options: list[Option] = []
        self._add_section(options, "Holding capacity")
        for row in view.holdings:
            details = [row.kind, f"+{_number(row.charged_weight)}", row.weight_source]
            if row.since:
                details.append(f"since {row.since[:19]}")
            if row.authored_budget is not None:
                details.append(f"budget c{row.authored_budget}")
            self._add_agent_option(
                options, row.name, row.artifact_dir, " · ".join(details)
            )
        if view.holdings:
            self._add_disabled_option(
                options,
                f"  Total charged: {_number(view.total_charged)}",
            )
        else:
            self._add_disabled_option(options, "  No capacity claims")

        if view.riders:
            self._add_section(options, "Shared claims")
            for row in view.riders:
                self._add_agent_option(
                    options,
                    row.name,
                    row.artifact_dir,
                    f"shared with {row.holder_name}",
                )

        self._add_section(options, "Live, holding nothing")
        if not view.idle_groups:
            self._add_disabled_option(options, "  No live records in this category")
        for group in view.idle_groups:
            shown = len(group.members)
            group_note = (
                f"{group.reason_label} · {shown} of {group.count} shown"
                if group.truncated
                else f"{group.reason_label} · {group.count}"
            )
            self._add_disabled_option(options, f"  {group_note}")
            for name, artifact_dir in zip(
                group.members,
                group.member_artifact_dirs,
                strict=False,
            ):
                self._add_agent_option(options, name, artifact_dir, group.reason_label)
            if group.truncated:
                self._add_toggle_option(
                    options,
                    group.reason_code,
                    f"Show {group.hidden} more · Enter to expand",
                )
            elif group.count > _DEFAULT_IDLE_GROUP_LIMIT:
                self._add_toggle_option(
                    options,
                    group.reason_code,
                    "Show first 10 · Enter to collapse",
                )

        self._add_section(options, "Queued for capacity")
        if not view.queued:
            self._add_disabled_option(options, "  No queued capacity waiters")
        for row in view.queued:
            queued_details = (
                f"queue #{row.queue_position} · requests "
                f"{_number(row.requested_weight)} · {row.blocker}"
            )
            self._add_agent_option(options, row.name, row.artifact_dir, queued_details)

        if view.diagnostics:
            self._add_section(options, "Diagnostics")
            for diagnostic in view.diagnostics:
                self._add_disabled_option(options, f"  {diagnostic}")
        return options

    def _add_section(self, options: list[Option], label: str) -> None:
        self._add_disabled_option(options, label.upper(), style="bold #87D7FF")

    def _add_disabled_option(
        self,
        options: list[Option],
        label: str,
        *,
        style: str = "dim",
    ) -> None:
        options.append(
            Option(
                Text(label, style=style),
                id=self._option_id("label"),
                disabled=True,
            )
        )

    def _add_agent_option(
        self,
        options: list[Option],
        name: str,
        artifact_dir: str,
        details: str,
    ) -> None:
        label = Text("  ")
        label.append(name, style="bold")
        label.append(f"  {details}", style="dim")
        option_id = self._option_id("agent")
        self._option_actions[option_id] = _OptionAction(
            kind="jump",
            name=name,
            artifact_dir=artifact_dir,
        )
        options.append(Option(label, id=option_id))

    def _add_toggle_option(
        self,
        options: list[Option],
        group_code: str,
        label: str,
    ) -> None:
        option_id = self._option_id("toggle")
        self._option_actions[option_id] = _OptionAction(
            kind="toggle_group",
            group_code=group_code,
        )
        options.append(Option(f"  {label}", id=option_id))

    def _option_id(self, kind: str) -> str:
        option_id = f"{kind}-{self._next_option_id}"
        self._next_option_id += 1
        return option_id

    def _activate_option(self, option_id: str) -> None:
        action = self._option_actions.get(option_id)
        if action is None:
            return
        if action.kind == "toggle_group" and action.group_code is not None:
            if action.group_code in self._expanded_idle_groups:
                self._expanded_idle_groups.remove(action.group_code)
            else:
                self._expanded_idle_groups.add(action.group_code)
            self._project_view()
            self._refresh_widgets()
            self.query_one(f"#{_OPTION_LIST_ID}", OptionList).focus()
            return
        if action.name is not None and action.artifact_dir is not None:
            self.dismiss(
                CapacityInspectorSelection(
                    name=action.name,
                    artifact_dir=action.artifact_dir,
                )
            )

    def _refresh_widgets(self) -> None:
        try:
            self.query_one("#capacity-inspector-title", Static).update(
                self._title_text()
            )
            self.query_one("#capacity-inspector-summary", Static).update(
                self._summary_text()
            )
            options = self.query_one(f"#{_OPTION_LIST_ID}", OptionList)
        except Exception:
            return
        options.clear_options()
        for option in self._build_options():
            options.add_option(option)


def _number(value: float) -> str:
    return f"{value:g}"


__all__ = ["CapacityInspectorModal", "CapacityInspectorSelection"]
