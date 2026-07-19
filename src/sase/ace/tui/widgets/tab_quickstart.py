"""Shared quick-start empty state for ACE tabs."""

from __future__ import annotations

from typing import Any, Literal

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Static

from ..keymaps import (
    KeymapRegistry,
    key_display_name,
    leader_key_display,
    load_keymap_registry,
)

TabQuickStartTab = Literal["agents", "changespecs"]

_AGENTS_ACCENT = "#87D7FF"
_CHANGESPECS_ACCENT = "#00D7AF"
_CALLOUT_ACCENT = "#FFD700"

_TAB_META: dict[TabQuickStartTab, tuple[str, str, str, str, str]] = {
    "agents": (
        "agent",
        "Agents",
        _AGENTS_ACCENT,
        "Every agent you launch shows up here — watch prompts, diffs, "
        "tool calls, and artifact files live, then jump straight into their work.",
        "Launch an agent and it appears here.",
    ),
    "changespecs": (
        "changespec",
        "PRs",
        _CHANGESPECS_ACCENT,
        "Every PR your agents produce is tracked here as a ChangeSpec — "
        "commits, hooks, review comments, and status, from WIP through Submitted.",
        "Your agents' PRs appear here as they work.",
    ),
}

_KEYCAP_STYLE = "bold #1a1a1a on #00D7AF"


class TabQuickStart(VerticalScroll):
    """Small keymap-aware quick start for empty Agents and PRs result areas."""

    def __init__(self, *, tab: TabQuickStartTab, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._tab = tab
        self._registry: KeymapRegistry = load_keymap_registry({})
        self._no_match_total = 0
        self._content_cache_key: tuple[int, int] | None = None
        self._content_cache: dict[str, Text] | None = None

    @property
    def _id_prefix(self) -> str:
        return _TAB_META[self._tab][0]

    def compose(self) -> ComposeResult:
        """Compose quick-start sections."""
        callout = Static(
            Text(),
            id=f"{self._id_prefix}-quickstart-callout",
            classes="tab-quickstart-callout hidden",
        )
        yield callout

        yield Static(
            Text(),
            id=f"{self._id_prefix}-quickstart-hero",
            classes="tab-quickstart-hero",
        )

        card = Static(
            Text(),
            id=f"{self._id_prefix}-quickstart-card",
            classes=f"tab-quickstart-card -{self._tab}",
        )
        card.border_title = "Start here"
        yield card

        yield Static(
            Text(),
            id=f"{self._id_prefix}-quickstart-footer",
            classes="tab-quickstart-footer",
        )

    def on_mount(self) -> None:
        """Render the initial content after mount."""
        self.refresh_content()

    def set_keymap_registry(self, registry: KeymapRegistry) -> None:
        """Use the active keymap registry and refresh displayed hints."""
        if self._registry is registry:
            return
        self._registry = registry
        self._content_cache_key = None
        self.refresh_content()

    def set_no_match_context(self, total_changespecs: int) -> None:
        """Show PRs no-match context when a query filtered out existing PRs."""
        total = max(0, total_changespecs)
        if self._no_match_total == total:
            return
        self._no_match_total = total
        self._content_cache_key = None
        self.refresh_content()

    def refresh_content(self) -> None:
        """Refresh static sections from current state."""
        if not self.is_mounted:
            return
        for selector, content in self._cached_content().items():
            self.query_one(selector, Static).update(content)
        self._apply_callout_visibility()

    def _cached_content(self) -> dict[str, Text]:
        key = (id(self._registry), self._no_match_total)
        if self._content_cache_key == key and self._content_cache is not None:
            return self._content_cache
        self._content_cache_key = key
        self._content_cache = self.render_content(
            self._registry,
            tab=self._tab,
            no_match_total=self._no_match_total,
        )
        return self._content_cache

    def _apply_callout_visibility(self) -> None:
        callout = self.query_one(f"#{self._id_prefix}-quickstart-callout", Static)
        callout.set_class(not self._should_show_callout(), "hidden")

    def _should_show_callout(self) -> bool:
        return self._tab == "changespecs" and self._no_match_total > 0

    @classmethod
    def render_content(
        cls,
        registry: KeymapRegistry,
        *,
        tab: TabQuickStartTab,
        no_match_total: int = 0,
    ) -> dict[str, Text]:
        """Build all renderable sections for *registry* without mounting."""
        prefix = _TAB_META[tab][0]
        return {
            f"#{prefix}-quickstart-callout": cls._build_callout(
                registry,
                tab=tab,
                total_changespecs=no_match_total,
            ),
            f"#{prefix}-quickstart-hero": cls._build_hero(tab),
            f"#{prefix}-quickstart-card": cls._build_card(registry, tab=tab),
            f"#{prefix}-quickstart-footer": cls._build_footer(tab),
        }

    @staticmethod
    def _build_hero(tab: TabQuickStartTab) -> Text:
        _, title, accent, summary, _ = _TAB_META[tab]
        text = Text(justify="center")
        text.append("*  ", style="bold #FFD700")
        text.append(title, style="bold #FFFFFF")
        text.append("  *\n", style="bold #FFD700")
        text.append(summary, style=f"dim {accent}")
        return text

    @classmethod
    def _build_card(cls, registry: KeymapRegistry, *, tab: TabQuickStartTab) -> Text:
        app = registry.app
        rows: list[tuple[tuple[str, ...], str]] = [
            (
                (key_display_name(app.start_agent_home),),
                "Launch your first agent from the home-workspace prompt bar.",
            ),
            (
                (key_display_name(app.open_config_center),),
                "Open the SASE Admin Center: configure sase, install plugins, "
                "run updates.",
            ),
            (
                (key_display_name(app.next_tab),),
                "Cycle tabs: Agents · Artifacts · AXE.",
            ),
            (
                (leader_key_display(registry, "edit_query"),),
                "Search and filter this tab.",
            ),
            (
                (leader_key_display(registry, "show_help"),),
                "Every keymap for the current tab.",
            ),
            (
                (leader_key_display(registry, "show_help"), "]"),
                "The full tour of this tab: the in-depth guide.",
            ),
            (
                (key_display_name(app.open_command_palette),),
                "Command palette: fuzzy-run any command.",
            ),
        ]
        if tab == "changespecs":
            rows.insert(
                3,
                (
                    (
                        key_display_name(app.cycle_artifacts_subtab_reverse),
                        key_display_name(app.cycle_artifacts_subtab),
                    ),
                    "Browse Artifacts: PRs · Commits · Bugs · Plans.",
                ),
            )

        column_width = max(cls._keycap_width(labels) for labels, _ in rows)
        text = Text()
        for labels, description in rows:
            cls._append_key_row(text, labels, description, column_width=column_width)
        return text

    @staticmethod
    def _build_footer(tab: TabQuickStartTab) -> Text:
        text = Text(justify="center")
        text.append(_TAB_META[tab][4], style="dim italic")
        return text

    @classmethod
    def _build_callout(
        cls,
        registry: KeymapRegistry,
        *,
        tab: TabQuickStartTab,
        total_changespecs: int,
    ) -> Text:
        text = Text(justify="center")
        if tab != "changespecs" or total_changespecs <= 0:
            return text
        noun = "exists" if total_changespecs == 1 else "exist"
        text.append("No PRs match this query — ", style=f"bold {_CALLOUT_ACCENT}")
        text.append(str(total_changespecs), style=f"bold {_CALLOUT_ACCENT}")
        text.append(f" {noun}. ", style=f"bold {_CALLOUT_ACCENT}")
        cls._append_keycap(text, leader_key_display(registry, "edit_query"))
        text.append("edits the query.", style=f"bold {_CALLOUT_ACCENT}")
        return text

    @staticmethod
    def _keycap_width(labels: tuple[str, ...]) -> int:
        if not labels:
            return 0
        return sum(len(label) + 2 for label in labels) + len(labels) - 1

    @classmethod
    def _append_key_row(
        cls,
        text: Text,
        labels: tuple[str, ...],
        description: str,
        *,
        column_width: int,
    ) -> None:
        padding = max(0, column_width - cls._keycap_width(labels))
        text.append(" " * padding)
        for idx, label in enumerate(labels):
            if idx:
                text.append(" ")
            cls._append_keycap(text, label)
        text.append("  ")
        text.append(description)
        text.append("\n")

    @staticmethod
    def _append_keycap(text: Text, label: str) -> None:
        text.append(f" {label} ", style=_KEYCAP_STYLE)
