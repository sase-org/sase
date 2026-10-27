"""Keyboard-first view of the authoritative machine capacity report."""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widget import Widget
from textual.widgets import OptionList, Static
from textual.widgets.option_list import Option

from sase.ace.tui.actions.clipboard import schedule_copy_delivery
from sase.core.runner_slots import capacity_view, format_capacity_duration

from ._capacity_inspector_render import (
    format_capacity_number,
    render_capacity_row,
    render_detail,
    render_facts,
    render_footer,
    render_gauge,
    render_headline,
    render_section_header,
    render_verdict,
)
from .base import CopyModeForwardingMixin, OptionListNavigationMixin

_OPTION_LIST_ID = "capacity-inspector-options"


@dataclass(frozen=True, slots=True)
class CapacityInspectorSelection:
    """Agent selected for a jump from the capacity inspector."""

    name: str
    artifact_dir: str


@dataclass(frozen=True, slots=True)
class _GroupMember:
    name: str
    artifact_dir: str


@dataclass(frozen=True, slots=True)
class _OptionAction:
    kind: Literal["jump", "toggle_group"]
    detail_kind: str
    row: Any | None = None
    group: Any | None = None
    group_code: str | None = None


class _CapacityOptionList(OptionList):
    """OptionList with a quiet programmatic selection path for report refreshes."""

    def __init__(self, *children: Option, **kwargs: Any) -> None:
        self._setting_highlight_silently = False
        super().__init__(*children, **kwargs)

    def set_highlight_silently(self, index: int | None) -> None:
        self._setting_highlight_silently = True
        try:
            self.highlighted = index
            self.scroll_to_highlight()
        finally:
            self._setting_highlight_silently = False

    def watch_highlighted(self, highlighted: int | None) -> None:
        if self._setting_highlight_silently:
            return
        super().watch_highlighted(highlighted)


class _CapacityGauge(Widget):
    """Responsive one-line gauge, rendered from authoritative core geometry."""

    def __init__(self, *, id: str) -> None:
        super().__init__(id=id)
        self._view: Any | None = None
        self._highlighted_owner: int | None = None
        self._dark = True
        self._accent = "#87D7FF"

    def update_view(
        self,
        view: Any | None,
        *,
        highlighted_owner: int | None,
        dark: bool,
        accent: str,
    ) -> None:
        self._view = view
        self._highlighted_owner = highlighted_owner
        self._dark = dark
        self._accent = accent
        self.refresh()

    def render(self) -> Text:
        """Draw as many cells as the current widget width allows."""
        return render_gauge(
            self._view,
            width=self.size.width,
            highlighted_owner=self._highlighted_owner,
            dark=self._dark,
            accent=self._accent,
        )


class CapacityInspectorModal(
    CopyModeForwardingMixin,
    OptionListNavigationMixin,
    ModalScreen[CapacityInspectorSelection | None],
):
    """Render the shared tiered capacity view with selectable agent rows."""

    _option_list_id = _OPTION_LIST_ID
    BINDINGS = [
        *OptionListNavigationMixin.NAVIGATION_BINDINGS,
        ("enter", "select_highlighted", "Jump or expand"),
        ("l", "expand_group", "Expand group"),
        ("right", "expand_group", "Expand group"),
        ("h", "fold_group", "Fold group"),
        ("left", "fold_group", "Fold group"),
        ("y", "copy_snapshot", "Copy snapshot"),
    ]

    def __init__(
        self,
        report: Any | None,
        *,
        running_nodes: int | None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        super().__init__()
        self._report = report
        self._running_nodes = running_nodes
        self._clock = time.time if clock is None else clock
        self._expanded_groups: set[str] = set()
        self._view: Any | None = None
        self._option_actions: dict[str, _OptionAction] = {}
        self._option_positions: dict[str, tuple[str, int]] = {}
        self._section_option_ids: dict[str, list[str]] = {}
        self._selected_option_id: str | None = None
        self._freshness_timer: Any | None = None
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
            yield Static(self._headline_text(), id="capacity-inspector-headline")
            yield _CapacityGauge(id="capacity-inspector-gauge")
            yield Static(self._verdict_text(), id="capacity-inspector-verdict")
            yield Static(self._facts_text(), id="capacity-inspector-facts")
            yield _CapacityOptionList(
                *self._build_options(),
                id=_OPTION_LIST_ID,
            )
            yield Static(
                render_detail(
                    view=None, target_kind=None, row=None, group=None, now=self._clock()
                ),
                id="capacity-inspector-detail",
            )
            yield Static(render_footer(), id="capacity-inspector-footer")

    def on_mount(self) -> None:
        self.query_one(f"#{_OPTION_LIST_ID}", _CapacityOptionList).focus()
        self._freshness_timer = self.set_interval(1.0, self._tick_freshness)
        try:
            self.watch(self.app, "theme", self._theme_changed, init=False)
        except Exception:
            pass
        self._refresh_widgets()

    def on_unmount(self) -> None:
        if self._freshness_timer is not None:
            self._freshness_timer.stop()
            self._freshness_timer = None

    def on_resize(self) -> None:
        if self.is_mounted:
            self._refresh_widgets()

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

    def action_expand_group(self) -> None:
        action = self._highlighted_action()
        if action is None or action.group_code is None:
            return
        if (
            action.kind == "toggle_group"
            and action.group_code not in self._expanded_groups
        ):
            self._expanded_groups.add(action.group_code)
            self._project_view()
            self._refresh_widgets(preferred_id=f"group:{action.group_code}")

    def action_fold_group(self) -> None:
        action = self._highlighted_action()
        if action is None or action.group_code is None:
            return
        group_id = f"group:{action.group_code}"
        if action.group_code in self._expanded_groups:
            self._expanded_groups.remove(action.group_code)
            self._project_view()
            self._refresh_widgets(preferred_id=group_id)

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

    def on_option_list_option_highlighted(
        self,
        event: OptionList.OptionHighlighted,
    ) -> None:
        self._selected_option_id = event.option.id
        self._update_detail_and_gauge()

    def _project_view(self) -> None:
        self._view = (
            None
            if self._report is None
            else capacity_view(
                self._report,
                running_nodes=self._running_nodes,
                expanded_idle_groups=self._expanded_groups,
                now=self._clock(),
            )
        )

    def _current_dark_theme(self) -> bool:
        try:
            return bool(self.app.current_theme.dark)
        except Exception:
            return True

    def _theme_accent(self) -> str:
        try:
            color = self.app.current_theme.primary
            return str(color)
        except Exception:
            return "#87D7FF"

    def _theme_changed(self) -> None:
        if self.is_mounted:
            self._refresh_widgets()

    def _title_text(self) -> Text:
        text = Text("CAPACITY", style="bold #87D7FF")
        if self._report is not None:
            machine = getattr(self._report, "machine", None)
            if isinstance(machine, str) and machine:
                text.append(f" · {machine}", style="bold")
        return text

    def _headline_text(self) -> Text:
        return render_headline(
            self._view,
            now=self._clock(),
            dark=self._current_dark_theme(),
        )

    def _verdict_text(self) -> Text:
        return render_verdict(self._view)

    def _facts_text(self) -> Text:
        return render_facts(self._view, now=self._clock())

    def _option_width(self) -> int:
        if self.is_mounted:
            try:
                width = self.query_one(f"#{_OPTION_LIST_ID}", OptionList).size.width
                if width > 0:
                    return max(20, width - 2)
            except Exception:
                pass
        try:
            screen_width = self.size.width
        except Exception:
            screen_width = 0
        return max(48, int(screen_width * 0.96) - 8 if screen_width else 100)

    def _build_options(self) -> list[Option]:
        self._option_actions = {}
        self._option_positions = {}
        self._section_option_ids = {}
        view = self._view
        if view is None:
            return [
                Option("Waiting for the first authoritative report…", disabled=True)
            ]

        options: list[Option] = []
        width = self._option_width()
        if view.accounting_unavailable:
            self._add_header(options, "Accounting", "unavailable", width)
            self._add_disabled(options, "This sase-core build reports totals only.")
            return options

        attention_count = sum(group.count for group in view.attention_groups)
        if attention_count or view.diagnostics:
            self._add_header(
                options,
                "Needs attention",
                f"{attention_count + len(view.diagnostics)} issues",
                width,
            )
            for group in view.attention_groups:
                for name, artifact_dir in zip(
                    group.members,
                    group.member_artifact_dirs,
                    strict=False,
                ):
                    member = _GroupMember(name, artifact_dir)
                    self._add_agent(
                        options,
                        section="attention",
                        option_id=f"agent:{artifact_dir}",
                        row=member,
                        detail_kind="member",
                        group=group,
                        mark="▱?",
                        name=name,
                        kind="attention",
                        note=group.reason_label,
                        width=width,
                        mark_style="yellow",
                        name_style="yellow",
                    )
            for diagnostic in view.diagnostics:
                self._add_disabled(options, f"! {diagnostic}", style="yellow")

        charged = tuple(view.charged)
        self._add_header(
            options,
            "Using capacity",
            f"{format_capacity_number(view.total_charged)} units · {len(charged)} agents",
            width,
        )
        if not charged:
            self._add_disabled(
                options,
                f"Nothing holds capacity — all {format_capacity_number(view.limit)} units are free",
            )
        for row in charged:
            note_parts = []
            if row.weight_source == "explicit":
                note_parts.append("explicit weight")
            if row.authored_budget is not None:
                note_parts.append(f"budget {row.authored_budget}")
            if row.rider_names:
                note_parts.append(f"+{len(row.rider_names)} rider")
            self._add_agent(
                options,
                section="using",
                option_id=f"agent:{row.artifact_dir}",
                row=row,
                detail_kind="holder",
                mark=f"▰{format_capacity_number(row.charged_weight)}",
                name=row.name,
                kind=row.kind,
                note=" · ".join(note_parts),
                age=format_capacity_duration(row.running_seconds),
                width=width,
            )

        self._add_header(options, "Queued", f"{len(view.queued)} waiting", width)
        if not view.queued:
            self._add_disabled(options, "Nobody is queued")
        tone_styles = {
            "ready": "green",
            "capacity": "yellow",
            "held": "magenta",
            "never_fits": "red",
            "deferred": "dim",
            "other": "yellow",
        }
        for row in view.queued:
            self._add_agent(
                options,
                section="queued",
                option_id=f"agent:{row.artifact_dir}",
                row=row,
                detail_kind="queued",
                mark=f"#{row.queue_position}",
                name=row.name,
                kind="waiter",
                note=row.blocker,
                age=format_capacity_duration(row.waiting_seconds),
                width=width,
                mark_style=tone_styles.get(row.tone, "yellow"),
            )

        zero_rows = tuple(view.zero_weight)
        riders = tuple(view.riders)
        if zero_rows or riders:
            self._add_header(
                options,
                "Running at zero weight",
                f"{len(zero_rows) + len(riders)} agents",
                width,
            )
            for row in zero_rows:
                self._add_agent(
                    options,
                    section="zero",
                    option_id=f"agent:{row.artifact_dir}",
                    row=row,
                    detail_kind="zero",
                    mark="▰0",
                    name=row.name,
                    kind=row.kind,
                    note="explicit zero weight",
                    age=format_capacity_duration(row.running_seconds),
                    width=width,
                    mark_style="dim",
                )
            for row in riders:
                self._add_agent(
                    options,
                    section="zero",
                    option_id=f"agent:{row.artifact_dir}",
                    row=row,
                    detail_kind="rider",
                    mark="⇢",
                    name=row.name,
                    kind="rider",
                    note=f"shares {row.holder_name}'s claim",
                    age=format_capacity_duration(row.running_seconds),
                    width=width,
                )

        waiting_groups = tuple(view.waiting_groups)
        inactive_groups = tuple(view.inactive_groups)
        if waiting_groups or inactive_groups:
            live_count = sum(group.count for group in waiting_groups)
            inactive_count = sum(group.count for group in inactive_groups)
            self._add_header(
                options,
                "Not running",
                f"holds nothing · {live_count} live · {inactive_count} inactive",
                width,
            )
            for group in (*waiting_groups, *inactive_groups):
                self._add_group(options, group, width=width)
        return options

    def _add_header(
        self,
        options: list[Option],
        label: str,
        summary: str,
        width: int,
    ) -> None:
        options.append(
            Option(
                render_section_header(label, summary, width=width),
                disabled=True,
            )
        )

    def _add_disabled(
        self,
        options: list[Option],
        label: str,
        *,
        style: str = "dim",
    ) -> None:
        options.append(Option(Text(f"  {label}", style=style), disabled=True))

    def _add_agent(
        self,
        options: list[Option],
        *,
        section: str,
        option_id: str,
        row: Any,
        detail_kind: str,
        mark: str,
        name: str,
        kind: str,
        note: str,
        width: int,
        age: str = "",
        mark_style: str = "bold",
        name_style: str = "bold",
        group: Any | None = None,
        group_code: str | None = None,
    ) -> None:
        prompt = render_capacity_row(
            mark=mark,
            name=name,
            kind=kind,
            note=note,
            age=age,
            width=width,
            mark_style=mark_style,
            name_style=name_style,
        )
        options.append(Option(prompt, id=option_id))
        section_ids = self._section_option_ids.setdefault(section, [])
        self._option_positions[option_id] = (section, len(section_ids))
        section_ids.append(option_id)
        self._option_actions[option_id] = _OptionAction(
            kind="jump",
            detail_kind=detail_kind,
            row=row,
            group=group,
            group_code=group_code,
        )

    def _add_group(self, options: list[Option], group: Any, *, width: int) -> None:
        expanded = group.reason_code in self._expanded_groups
        preview = ", ".join(group.members)
        option_id = f"group:{group.reason_code}"
        prompt = render_capacity_row(
            mark="▾" if expanded else "▸",
            name=f"{group.count} {group.reason_label}",
            kind="",
            note=preview,
            width=width,
            mark_style="dim" if group.tier == "inactive" else "bold",
            name_style="dim" if group.tier == "inactive" else "bold",
        )
        options.append(Option(prompt, id=option_id))
        section_ids = self._section_option_ids.setdefault("not_running", [])
        self._option_positions[option_id] = ("not_running", len(section_ids))
        section_ids.append(option_id)
        self._option_actions[option_id] = _OptionAction(
            kind="toggle_group",
            detail_kind="group",
            group=group,
            group_code=group.reason_code,
        )
        if not expanded:
            return
        for name, artifact_dir in zip(
            group.members,
            group.member_artifact_dirs,
            strict=False,
        ):
            member = _GroupMember(name, artifact_dir)
            self._add_agent(
                options,
                section="not_running",
                option_id=f"member:{group.reason_code}:{artifact_dir}",
                row=member,
                detail_kind="member",
                mark="↳",
                name=name,
                kind="",
                note="",
                width=width,
                mark_style="dim" if group.tier == "inactive" else "",
                name_style="dim" if group.tier == "inactive" else "bold",
                group=group,
                group_code=group.reason_code,
            )

    def _highlighted_action(self) -> _OptionAction | None:
        options = self.query_one(f"#{_OPTION_LIST_ID}", OptionList)
        index = options.highlighted
        if index is None or index < 0 or index >= len(options.options):
            return None
        option_id = options.options[index].id
        return None if option_id is None else self._option_actions.get(option_id)

    def _activate_option(self, option_id: str) -> None:
        action = self._option_actions.get(option_id)
        if action is None:
            return
        if action.kind == "toggle_group" and action.group_code is not None:
            if action.group_code in self._expanded_groups:
                self._expanded_groups.remove(action.group_code)
            else:
                self._expanded_groups.add(action.group_code)
            self._project_view()
            self._refresh_widgets(preferred_id=f"group:{action.group_code}")
            self.query_one(f"#{_OPTION_LIST_ID}", OptionList).focus()
            return
        row = action.row
        if (
            row is not None
            and getattr(row, "name", None)
            and getattr(row, "artifact_dir", None)
        ):
            self.dismiss(
                CapacityInspectorSelection(
                    name=row.name,
                    artifact_dir=row.artifact_dir,
                )
            )

    def _refresh_widgets(self, *, preferred_id: str | None = None) -> None:
        if not self.is_mounted:
            return
        old_id = self._selected_option_id
        options_widget = self.query_one(f"#{_OPTION_LIST_ID}", _CapacityOptionList)
        old_section_position = self._option_positions.get(old_id or "")
        rendered = self._build_options()

        self.query_one("#capacity-inspector-title", Static).update(self._title_text())
        self.query_one("#capacity-inspector-headline", Static).update(
            self._headline_text()
        )
        self.query_one("#capacity-inspector-verdict", Static).update(
            self._verdict_text()
        )
        self.query_one("#capacity-inspector-facts", Static).update(self._facts_text())
        options_widget.clear_options()
        for option in rendered:
            options_widget.add_option(option)

        option_ids = [option.id for option in rendered]
        selectable_ids = [
            option_id for option_id in option_ids if option_id is not None
        ]
        target_id = preferred_id or (old_id if old_id in selectable_ids else None)
        if target_id is None and old_section_position is not None:
            section, position = old_section_position
            same_section = self._section_option_ids.get(section, [])
            if same_section:
                target_id = same_section[min(position, len(same_section) - 1)]
        if target_id is None and selectable_ids:
            target_id = selectable_ids[0]
        target_index = next(
            (i for i, option in enumerate(rendered) if option.id == target_id),
            None,
        )
        options_widget.set_highlight_silently(target_index)
        self._selected_option_id = target_id
        self._update_detail_and_gauge()

    def _update_detail_and_gauge(self) -> None:
        action = self._option_actions.get(self._selected_option_id or "")
        detail = render_detail(
            view=self._view,
            target_kind=None if action is None else action.detail_kind,
            row=None if action is None else action.row,
            group=None if action is None else action.group,
            now=self._clock(),
        )
        try:
            self.query_one("#capacity-inspector-detail", Static).update(detail)
            self.query_one("#capacity-inspector-gauge", _CapacityGauge).update_view(
                self._view,
                highlighted_owner=self._highlighted_owner(action),
                dark=self._current_dark_theme(),
                accent=self._theme_accent(),
            )
        except Exception:
            return

    def _highlighted_owner(self, action: _OptionAction | None) -> int | None:
        if action is None or action.detail_kind not in {"holder", "zero"}:
            return None
        artifact_dir = getattr(action.row, "artifact_dir", None)
        if not artifact_dir or self._view is None:
            return None
        for index, row in enumerate(self._view.charged):
            if row.artifact_dir == artifact_dir:
                return index
        return None

    def _tick_freshness(self) -> None:
        if self._view is None:
            return
        self.query_one("#capacity-inspector-headline", Static).update(
            self._headline_text()
        )


__all__ = ["CapacityInspectorModal", "CapacityInspectorSelection"]
