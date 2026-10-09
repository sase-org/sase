"""Dictionary definition card modal."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Container, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Static

from sase.ace.tui.actions.clipboard import schedule_copy_delivery

from .word_definition_card import (
    DefinitionCard,
    LeadDefinition,
    build_definition_card,
)
from .word_definition_render import (
    build_attribution,
    build_border_subtitle,
    build_border_title,
    build_details,
    build_headline,
    build_lead,
    definition_card_palette,
)


class WordDefinitionModal(ModalScreen[None]):
    """Display one word's dictionary card with a pinned hero and details."""

    BINDINGS = [
        ("escape", "close", "Close"),
        ("q", "close", "Close"),
        ("y", "copy_definition", "Copy definition"),
        ("ctrl+d", "scroll_down", "Scroll down"),
        ("ctrl+u", "scroll_up", "Scroll up"),
        ("j", "scroll_line_down", "Line down"),
        ("k", "scroll_line_up", "Line up"),
        ("g", "scroll_top", "Top"),
        ("G", "scroll_bottom", "Bottom"),
        ("shift+g", "scroll_bottom", "Bottom"),
    ]

    def __init__(
        self,
        card: DefinitionCard | str,
        sections: tuple[object, ...] | None = None,
    ) -> None:
        super().__init__()
        if isinstance(card, DefinitionCard):
            self._card = card
        else:
            self._card = build_definition_card(card, sections or ())  # type: ignore[arg-type]
        self._accent = "#5FD7AF"
        self._pill_fg = "#1a1a1a"

    def compose(self) -> ComposeResult:
        try:
            self._accent, self._pill_fg = definition_card_palette(
                self.app.current_theme
            )
        except Exception:
            pass
        with Container(id="word-definition-container"):
            with Vertical(id="word-definition-hero"):
                yield Static(
                    build_headline(
                        self._card, accent=self._accent, pill_fg=self._pill_fg
                    ),
                    id="word-definition-headline",
                )
                lead = build_lead(self._card)
                if lead is not None:
                    yield Static(lead, id="word-definition-lead")
                attribution = build_attribution(self._card)
                if attribution is not None:
                    yield Static(attribution, id="word-definition-attribution")
            with VerticalScroll(id="word-definition-scroll"):
                yield Static(
                    build_details(self._card, accent=self._accent),
                    id="word-definition-content",
                )

    def on_mount(self) -> None:
        try:
            self._accent, self._pill_fg = definition_card_palette(
                self.app.current_theme
            )
        except Exception:
            pass
        container = self.query_one("#word-definition-container", Container)
        container.border_title = build_border_title(accent=self._accent)
        container.border_subtitle = build_border_subtitle(accent=self._accent)
        container.styles.border = ("round", self._accent)
        try:
            lead = self.query_one("#word-definition-lead", Static)
            lead.styles.border_left = ("tall", self._accent)
        except Exception:
            pass

    def action_close(self) -> None:
        self.dismiss(None)

    def action_copy_definition(self) -> None:
        lead: LeadDefinition | None = self._card.lead
        if lead is None:
            self.notify("No definition summary to copy", severity="warning")
            return
        schedule_copy_delivery(
            self,
            lead.gloss,
            copied_label="definition",
            task_name="sase-word-definition-copy",
        )

    def action_scroll_down(self) -> None:
        scroll = self.query_one("#word-definition-scroll", VerticalScroll)
        height = max(1, scroll.scrollable_content_region.height // 2)
        scroll.scroll_relative(y=height, animate=False)

    def action_scroll_up(self) -> None:
        scroll = self.query_one("#word-definition-scroll", VerticalScroll)
        height = max(1, scroll.scrollable_content_region.height // 2)
        scroll.scroll_relative(y=-height, animate=False)

    def action_scroll_line_down(self) -> None:
        scroll = self.query_one("#word-definition-scroll", VerticalScroll)
        scroll.scroll_relative(y=1, animate=False)

    def action_scroll_line_up(self) -> None:
        scroll = self.query_one("#word-definition-scroll", VerticalScroll)
        scroll.scroll_relative(y=-1, animate=False)

    def action_scroll_top(self) -> None:
        scroll = self.query_one("#word-definition-scroll", VerticalScroll)
        scroll.scroll_home(animate=False)

    def action_scroll_bottom(self) -> None:
        scroll = self.query_one("#word-definition-scroll", VerticalScroll)
        scroll.scroll_end(animate=False)


__all__ = ["WordDefinitionModal"]
