"""Shared quick-start empty state for ACE tabs."""

from __future__ import annotations

from textwrap import wrap
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

TabQuickStartTab = Literal["agents", "artifacts"]
LegacyTabQuickStartTab = Literal[
    "patches",
    "changespecs",  # legacy compatibility alias
]

_AGENTS_ACCENT = "#87D7FF"
_PATCHES_ACCENT = "#00D7AF"
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
    "artifacts": (
        "patch",
        "PRs",
        _PATCHES_ACCENT,
        "Every PR your agents produce is tracked here as a Patch — "
        "commits, hooks, review comments, and status, from WIP through Submitted.",
        "Your agents' PRs appear here as they work.",
    ),
}

_KEYCAP_STYLE = "bold #1a1a1a on #00D7AF"

# Keep in sync with `.tab-quickstart-card` in styles.tcss: max-width 90 minus
# the round border (2) and `padding: 0 1` (2).
_CARD_MAX_WIDTH = 90
_CARD_CONTENT_WIDTH = _CARD_MAX_WIDTH - 4
_KEY_DESCRIPTION_GAP = 2
_MIN_DESCRIPTION_WIDTH = 24


class TabQuickStart(VerticalScroll):
    """Small keymap-aware quick start for empty Agents and PRs result areas."""

    def __init__(
        self,
        *,
        tab: TabQuickStartTab,
        selector_prefix: str | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._tab = _normalize_tab(tab)
        self._selector_prefix = selector_prefix
        self._registry: KeymapRegistry = load_keymap_registry({})
        self._no_match_total = 0
        self._content_cache_key: tuple[int, int] | None = None
        self._content_cache: dict[str, Text] | None = None

    @property
    def _id_prefix(self) -> str:
        if self._selector_prefix is not None:
            return self._selector_prefix
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

    def set_no_match_context(self, total_patches: int) -> None:
        """Show PRs no-match context when a query filtered out existing PRs."""
        total = max(0, total_patches)
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
            selector_prefix=self._selector_prefix,
        )
        return self._content_cache

    def _apply_callout_visibility(self) -> None:
        callout = self.query_one(f"#{self._id_prefix}-quickstart-callout", Static)
        callout.set_class(not self._should_show_callout(), "hidden")

    def _should_show_callout(self) -> bool:
        return self._tab == "artifacts" and self._no_match_total > 0

    @classmethod
    def render_content(
        cls,
        registry: KeymapRegistry,
        *,
        tab: TabQuickStartTab | LegacyTabQuickStartTab,
        no_match_total: int = 0,
        selector_prefix: str | None = None,
    ) -> dict[str, Text]:
        """Build all renderable sections for *registry* without mounting."""
        selector_prefix = (
            selector_prefix or "changespec"  # legacy compatibility alias
            if tab == "changespecs"
            else selector_prefix or "patch"
            if tab == "patches"
            else selector_prefix
        )
        tab = _normalize_tab(tab)
        prefix = selector_prefix or _TAB_META[tab][0]
        return {
            f"#{prefix}-quickstart-callout": cls._build_callout(
                registry,
                tab=tab,
                total_patches=no_match_total,
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
        query_key = (
            leader_key_display(registry, "edit_query")
            if tab == "agents"
            else key_display_name(app.edit_query)
        )
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
                (query_key,),
                "Search and filter this tab.",
            ),
            (
                (key_display_name(app.show_help),),
                "Every keymap for the current tab.",
            ),
            (
                (key_display_name(app.show_help), "]"),
                "The full tour of this tab: the in-depth guide.",
            ),
            (
                (key_display_name(app.open_command_palette),),
                "Command palette: fuzzy-run any command.",
            ),
        ]
        if tab == "artifacts":
            rows.insert(
                3,
                (
                    ("1", "2", "3", "4"),
                    "Jump: Stitches · Patches · Beads · Files.",
                ),
            )
            rows.insert(
                4,
                (
                    (
                        key_display_name(app.cycle_artifacts_subtab_reverse),
                        key_display_name(app.cycle_artifacts_subtab),
                    ),
                    "Cycle Artifacts: Stitches · Patches · Beads · Files.",
                ),
            )
            rows.insert(
                5,
                (
                    (
                        key_display_name(app.cycle_files_subtab_reverse),
                        key_display_name(app.cycle_files_subtab),
                    ),
                    "Inside Files: Plans · Chats · Other.",
                ),
            )

        column_width = max(cls._keycap_width(labels) for labels, _ in rows)
        text = Text()
        for idx, (labels, description) in enumerate(rows):
            if idx:
                text.append("\n")
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
        total_patches: int,
    ) -> Text:
        text = Text(justify="center")
        if tab != "artifacts" or total_patches <= 0:
            return text
        noun = "exists" if total_patches == 1 else "exist"
        text.append("No PRs match this query — ", style=f"bold {_CALLOUT_ACCENT}")
        text.append(str(total_patches), style=f"bold {_CALLOUT_ACCENT}")
        text.append(f" {noun}. ", style=f"bold {_CALLOUT_ACCENT}")
        cls._append_keycap(text, key_display_name(registry.app.edit_query))
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
        description_width = max(
            _MIN_DESCRIPTION_WIDTH,
            _CARD_CONTENT_WIDTH - (column_width + _KEY_DESCRIPTION_GAP),
        )
        description_lines = wrap(description, width=description_width) or [""]
        text.append(" " * padding)
        for idx, label in enumerate(labels):
            if idx:
                text.append(" ")
            cls._append_keycap(text, label)
        text.append(" " * _KEY_DESCRIPTION_GAP)
        text.append(description_lines[0])
        continuation_prefix = " " * (column_width + _KEY_DESCRIPTION_GAP)
        for line in description_lines[1:]:
            text.append("\n")
            text.append(continuation_prefix)
            text.append(line)

    @staticmethod
    def _append_keycap(text: Text, label: str) -> None:
        text.append(f" {label} ", style=_KEYCAP_STYLE)


def _normalize_tab(tab: TabQuickStartTab | LegacyTabQuickStartTab) -> TabQuickStartTab:
    if tab in {
        "patches",
        "changespecs",  # legacy compatibility alias
    }:
        return "artifacts"
    if tab == "agents":
        return "agents"
    return "artifacts"
