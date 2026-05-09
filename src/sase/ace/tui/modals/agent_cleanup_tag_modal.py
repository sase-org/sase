"""Tag-scoped agent cleanup chooser for the ace TUI."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import Label, OptionList, Static
from textual.widgets.option_list import Option

from sase.core.agent_cleanup_facade import agents_to_cleanup_targets, plan_agent_cleanup
from sase.core.agent_cleanup_wire import (
    AGENT_CLEANUP_WIRE_SCHEMA_VERSION,
    CLEANUP_MODE_KILL_AND_DISMISS,
    CLEANUP_SCOPE_CUSTOM_SELECTION,
    CLEANUP_SCOPE_TAG,
    AgentCleanupIdentityWire,
    AgentCleanupPlanWire,
    AgentCleanupRequestWire,
)

from .agent_cleanup_types import AgentCleanupTagResult
from .base import OptionListNavigationMixin

if TYPE_CHECKING:
    from ..models import Agent


@dataclass(frozen=True)
class _TagRow:
    tag: str
    plan: AgentCleanupPlanWire


class AgentCleanupTagModal(
    OptionListNavigationMixin, ModalScreen[AgentCleanupTagResult | None]
):
    """Choose one or more tags and preview cleanup plans."""

    _option_list_id = "agent-cleanup-tag-list"
    BINDINGS = [
        *OptionListNavigationMixin.NAVIGATION_BINDINGS,
        ("space", "toggle_mark", "Mark"),
        ("m", "toggle_mark", "Mark"),
        ("enter", "choose_highlighted", "Choose"),
    ]

    def __init__(self, *, tags: tuple[str, ...], targets: list[Agent]) -> None:
        super().__init__()
        self._targets = list(targets)
        self._rows = [self._build_row(tag) for tag in sorted(set(tags), key=str.lower)]
        self._marked_tags: set[str] = set()

    def compose(self) -> ComposeResult:
        with Container(id="agent-cleanup-tag-container"):
            yield Label("Cleanup by Tag", id="agent-cleanup-title")
            yield OptionList(
                *[
                    Option(
                        self._tag_row_label(row),
                        id=f"tag:{row.tag}",
                        disabled=not self._row_enabled(row),
                    )
                    for row in self._rows
                ],
                id="agent-cleanup-tag-list",
            )
            yield Static(
                self._hint_text(),
                id="agent-cleanup-hints",
            )

    def action_choose_highlighted(self) -> None:
        if self._marked_tags:
            self.dismiss(AgentCleanupTagResult(tags=self._marked_tags_in_row_order()))
            return

        option_list = self.query_one("#agent-cleanup-tag-list", OptionList)
        highlighted = option_list.highlighted
        if highlighted is None or highlighted < 0:
            return
        option = option_list.get_option_at_index(highlighted)
        if option.disabled or option.id is None:
            return
        tag = str(option.id).removeprefix("tag:")
        self.dismiss(AgentCleanupTagResult(tags=(tag,)))

    def action_toggle_mark(self) -> None:
        option_list = self.query_one("#agent-cleanup-tag-list", OptionList)
        highlighted = option_list.highlighted
        if highlighted is None or highlighted < 0 or highlighted >= len(self._rows):
            return
        row = self._rows[highlighted]
        if not self._row_enabled(row):
            self._set_hint("Tag has no cleanup targets")
            return
        if row.tag in self._marked_tags:
            self._marked_tags.remove(row.tag)
        else:
            self._marked_tags.add(row.tag)
        self._refresh_row(highlighted)
        if self._rows:
            option_list.highlighted = (highlighted + 1) % len(self._rows)
        self._update_hint()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if event.option.disabled or event.option.id is None:
            return
        if self._marked_tags:
            self.dismiss(AgentCleanupTagResult(tags=self._marked_tags_in_row_order()))
            return
        tag = str(event.option.id).removeprefix("tag:")
        self.dismiss(AgentCleanupTagResult(tags=(tag,)))

    def _build_row(self, tag: str) -> _TagRow:
        request = AgentCleanupRequestWire(
            schema_version=AGENT_CLEANUP_WIRE_SCHEMA_VERSION,
            scope=CLEANUP_SCOPE_TAG,
            mode=CLEANUP_MODE_KILL_AND_DISMISS,
            tag=tag,
            include_pidless_as_dismissable=True,
        )
        plan = plan_agent_cleanup(agents_to_cleanup_targets(self._targets), request)
        return _TagRow(tag=tag, plan=plan)

    @staticmethod
    def _row_enabled(row: _TagRow) -> bool:
        return bool(row.plan.kill_items or row.plan.dismiss_items)

    def _tag_row_label(self, row: _TagRow) -> Text:
        text = Text()
        enabled = self._row_enabled(row)
        marked = row.tag in self._marked_tags
        marker_style = "bold green" if marked else "dim"
        tag_style = "bold cyan" if enabled else "dim"
        detail_style = "dim" if enabled else "dim italic"
        text.append("[x] " if marked else "[ ] ", style=marker_style)
        text.append(f"@{row.tag}", style=tag_style)
        counts = row.plan.counts
        text.append(
            f"\n   {counts.kill} kill  {counts.dismiss} dismiss  "
            f"{counts.cascaded_workflow_children} child cascade",
            style=detail_style,
        )
        return text

    def _marked_tags_in_row_order(self) -> tuple[str, ...]:
        return tuple(row.tag for row in self._rows if row.tag in self._marked_tags)

    def _marked_plan(self) -> AgentCleanupPlanWire | None:
        identities = self._marked_identities()
        if not identities:
            return None
        request = AgentCleanupRequestWire(
            schema_version=AGENT_CLEANUP_WIRE_SCHEMA_VERSION,
            scope=CLEANUP_SCOPE_CUSTOM_SELECTION,
            mode=CLEANUP_MODE_KILL_AND_DISMISS,
            identities=identities,
            include_pidless_as_dismissable=True,
        )
        return plan_agent_cleanup(agents_to_cleanup_targets(self._targets), request)

    def _marked_identities(self) -> tuple[AgentCleanupIdentityWire, ...]:
        seen: set[AgentCleanupIdentityWire] = set()
        identities: list[AgentCleanupIdentityWire] = []
        for row in self._rows:
            if row.tag not in self._marked_tags:
                continue
            for identity in row.plan.selected_identities:
                if identity in seen:
                    continue
                seen.add(identity)
                identities.append(identity)
        return tuple(identities)

    def _hint_text(self) -> str:
        base = "j/k move  space/m mark  enter preview  q close"
        mark_count = len(self._marked_tags)
        if not mark_count:
            return base
        plan = self._marked_plan()
        if plan is None:
            return f"{base}  marked: {mark_count}"
        counts = plan.counts
        return (
            f"{base}  marked: {mark_count}  {counts.kill} kill  "
            f"{counts.dismiss} dismiss  {counts.cascaded_workflow_children} child cascade"
        )

    def _refresh_row(self, index: int) -> None:
        option_list = self.query_one("#agent-cleanup-tag-list", OptionList)
        option_list.replace_option_prompt_at_index(
            index,
            self._tag_row_label(self._rows[index]),
        )
        option_list.highlighted = index

    def _set_hint(self, text: str) -> None:
        try:
            self.query_one("#agent-cleanup-hints", Static).update(text)
        except Exception:
            pass

    def _update_hint(self) -> None:
        self._set_hint(self._hint_text())


__all__ = ["AgentCleanupTagModal"]
