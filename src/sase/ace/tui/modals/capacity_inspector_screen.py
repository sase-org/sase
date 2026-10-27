"""Capacity inspector modal screen implementation."""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widget import Widget
from textual.widgets import OptionList, Static
from textual.widgets.option_list import Option

from sase.ace.tui.actions.clipboard import schedule_copy_delivery
from sase.core.runner_slots import capacity_view

from ._capacity_inspector_render import (
    render_detail,
    render_facts,
    render_footer,
    render_gauge,
    render_headline,
    render_verdict,
)
from ._capacity_inspector_shared import OptionAction
from .base import CopyModeForwardingMixin, OptionListNavigationMixin
from .capacity_inspector_options import build_capacity_options

_OPTION_LIST_ID = "capacity-inspector-options"


@dataclass(frozen=True, slots=True)
class CapacityInspectorSelection:
    """Agent selected for a jump from the capacity inspector."""

    name: str
    artifact_dir: str


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
        self._option_actions: dict[str, OptionAction] = {}
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
                render_detail(view=None, target_kind=None, row=None, group=None),
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
            )
        )

    def _project_snapshot(self) -> Any | None:
        try:
            return getattr(self.app, "project_display_snapshot", None)
        except Exception:
            return None

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
            width=self._header_width("#capacity-inspector-headline"),
        )

    def _verdict_text(self) -> Text:
        return render_verdict(self._view)

    def _facts_text(self) -> Text:
        return render_facts(
            self._view, width=self._header_width("#capacity-inspector-facts")
        )

    def _header_width(self, widget_id: str) -> int | None:
        if not self.is_mounted:
            return None
        try:
            width = self.query_one(widget_id, Static).size.width
        except Exception:
            return None
        return width if width > 0 else None

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
        options, actions, positions, section_ids = build_capacity_options(
            self._view,
            expanded_groups=self._expanded_groups,
            width=self._option_width(),
        )
        self._option_actions = actions
        self._option_positions = positions
        self._section_option_ids = section_ids
        return options

    def _highlighted_action(self) -> OptionAction | None:
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
            snapshot=self._project_snapshot(),
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

    def _highlighted_owner(self, action: OptionAction | None) -> int | None:
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
