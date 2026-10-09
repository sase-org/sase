"""Tests for the dictionary definition card modal."""

from __future__ import annotations

from rich.console import Console
from textual.app import App, ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Static

from sase.ace.tui.modals.word_definition_card import (
    DefinitionCard,
    build_definition_card,
)
from sase.ace.tui.modals.word_definition_modal import WordDefinitionModal
from sase.core.word_lookup import DefinitionSection


class _TestApp(App[None]):
    ENABLE_COMMAND_PALETTE = False

    def compose(self) -> ComposeResult:
        yield from ()


def _card() -> DefinitionCard:
    return build_definition_card(
        "refuting",
        (
            DefinitionSection(
                source="The Collaborative International Dictionary",
                database="gcide",
                body=(
                    '  refute \\re*fute"\\ (r[-e]*f[=u]t"), v. t. [F. r[\'e]futer.]\n'
                    "     To disprove and overthrow by argument; as, to refute lies.\n"
                ),
            ),
        ),
    )


def _render_text(renderable: object) -> str:
    console = Console(width=88, record=True, color_system=None)
    with console.capture() as capture:
        console.print(renderable)
    return capture.get()


async def test_hero_widgets_carry_headword_and_lead() -> None:
    async with _TestApp().run_test() as pilot:
        pilot.app.push_screen(WordDefinitionModal(_card()))
        await pilot.pause()

        headline = pilot.app.screen.query_one("#word-definition-headline", Static)
        lead = pilot.app.screen.query_one("#word-definition-lead", Static)
        attribution = pilot.app.screen.query_one("#word-definition-attribution", Static)
        pilot.app.screen.query_one("#word-definition-scroll", VerticalScroll)
        pilot.app.screen.query_one("#word-definition-content", Static)

        assert "refute" in _render_text(headline.content)
        assert "To disprove and overthrow" in _render_text(lead.content)
        assert "Webster" in _render_text(attribution.content)


async def test_no_lead_card_omits_lead_widgets() -> None:
    card = DefinitionCard(word="zzzzz", headword="zzzzz", lead=None, entries=())
    async with _TestApp().run_test() as pilot:
        pilot.app.push_screen(WordDefinitionModal(card))
        await pilot.pause()

        assert len(pilot.app.screen.query("#word-definition-lead")) == 0
        assert len(pilot.app.screen.query("#word-definition-attribution")) == 0
        assert pilot.app.screen.query_one("#word-definition-content", Static)


async def test_y_copies_lead_gloss() -> None:
    import sase.ace.tui.modals.word_definition_modal as modal_module

    seen: dict[str, object] = {}
    card = _card()
    assert card.lead is not None

    def fake_schedule(owner: object, value: object, **kwargs: object) -> None:
        seen["value"] = value
        seen.update(kwargs)

    async with _TestApp().run_test() as pilot:
        pilot.app.push_screen(WordDefinitionModal(card))
        await pilot.pause()
        modal_module.schedule_copy_delivery = fake_schedule  # type: ignore[assignment]
        try:
            await pilot.press("y")
            await pilot.pause()
        finally:
            import sase.ace.tui.actions.clipboard as clipboard

            modal_module.schedule_copy_delivery = clipboard.schedule_copy_delivery  # type: ignore[assignment]

    assert seen["value"] == card.lead.gloss
    assert seen["copied_label"] == "definition"


async def test_y_without_lead_warns() -> None:
    notifications: list[tuple[str, str | None]] = []
    card = DefinitionCard(word="zzzzz", headword="zzzzz", lead=None, entries=())
    async with _TestApp().run_test() as pilot:
        pilot.app.push_screen(WordDefinitionModal(card))
        await pilot.pause()
        modal = pilot.app.screen_stack[-1]
        modal.notify = lambda message, severity=None: notifications.append(  # type: ignore[method-assign]
            (message, severity)
        )
        modal.action_copy_definition()

    assert notifications == [("No definition summary to copy", "warning")]


async def test_j_and_g_scroll_details_with_hero_pinned() -> None:
    body = "  Run \\Run\\, v. i.\n" + "".join(
        f"     {index}. To run sense number {index} here today.\n"
        for index in range(1, 60)
    )
    card = build_definition_card(
        "run", (DefinitionSection(source="GCIDE", database="gcide", body=body),)
    )
    async with _TestApp().run_test(size=(88, 30)) as pilot:
        pilot.app.push_screen(WordDefinitionModal(card))
        await pilot.pause()

        scroll = pilot.app.screen.query_one("#word-definition-scroll", VerticalScroll)
        hero = pilot.app.screen.query_one("#word-definition-hero")
        assert hero.is_mounted

        await pilot.press("j")
        await pilot.pause()
        after_j = scroll.scroll_offset.y
        assert after_j >= 0

        await pilot.press("G")
        await pilot.pause()
        assert scroll.scroll_offset.y >= after_j
        assert hero.is_mounted
