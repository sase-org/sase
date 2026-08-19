"""Title, header, and review-shell layout coverage for the shared gate modal."""

from __future__ import annotations

from rich.markup import escape
from rich.text import Text
from textual.containers import VerticalScroll
from textual.widgets import Static

from sase.ace.tui.modals.custom_gate_modal import CustomGateModal
from sase.notification_gates.presentation import GateChip

from ._custom_gate_modal_helpers import GateTestApp, data, option


async def test_preview_composes_two_pane_shell_with_document_border_title() -> None:
    modal = CustomGateModal(
        data(
            options=(option("proceed"),),
            branches=(("proceed",),),
            preview_name="change.md",
            preview_text="# Change\n",
        )
    )

    async with GateTestApp().run_test(size=(120, 40)) as pilot:
        pilot.app.push_screen(modal)
        await pilot.pause()

        assert modal.query_one(".gate-review-body")
        assert modal.query_one(".gate-review-actions")
        scroll = modal.query_one("#custom-gate-review-scroll", VerticalScroll)
        assert scroll.has_class("gate-review-document")
        assert scroll.border_title == "change.md"
        assert not modal.query_one("#custom-gate-container").has_class(
            "gate-review-shell--compact"
        )
        assert modal.has_class("-gate-review-wide")


async def test_preview_uses_narrow_breakpoint_below_threshold() -> None:
    modal = CustomGateModal(
        data(
            options=(option("proceed"),),
            branches=(("proceed",),),
            preview_name="change.md",
            preview_text="# Change\n",
        )
    )

    async with GateTestApp().run_test(size=(90, 40)) as pilot:
        pilot.app.push_screen(modal)
        await pilot.pause()

        assert modal.has_class("-gate-review-narrow")
        assert not modal.has_class("-gate-review-wide")


async def test_previewless_gate_composes_compact_actions_only() -> None:
    modal = CustomGateModal(
        data(options=(option("proceed"),), branches=(("proceed",),))
    )

    async with GateTestApp().run_test(size=(120, 40)) as pilot:
        pilot.app.push_screen(modal)
        await pilot.pause()

        shell = modal.query_one("#custom-gate-container")
        assert shell.has_class("gate-review-shell--compact")
        assert not modal.query(".gate-review-body")
        assert not modal.query(".gate-review-document")
        actions = modal.query_one("#custom-gate-review-scroll", VerticalScroll)
        assert actions.has_class("gate-review-actions--compact")


def test_title_omits_chip_when_absent() -> None:
    modal = CustomGateModal(
        data(options=(option("proceed"),), branches=(("proceed",),))
    )

    assert modal._title() == (
        "[bold cyan]🛡️ Custom Gate[/bold cyan]  "
        "[dim]Custom Gate[/dim]  "
        "[bold]review-agent[/bold]  "
        "[dim]custom-ace[/dim]"
    )


def test_title_renders_chip_between_headline_and_kind() -> None:
    modal = CustomGateModal(
        data(
            options=(option("proceed"),),
            branches=(("proceed",),),
            title="Task Triage",
            gate_title="Review follow-up",
            chip=GateChip("≈", "flake", "#AF87FF"),
        )
    )

    assert modal._title() == (
        "[bold cyan]🛡️ Review follow-up[/bold cyan]  "
        "[bold #AF87FF]≈ flake[/]  "
        "[dim]Task Triage[/dim]  "
        "[bold]review-agent[/bold]  "
        "[dim]custom-ace[/dim]"
    )


def test_title_degrades_malformed_chip_color() -> None:
    modal = CustomGateModal(
        data(
            options=(option("proceed"),),
            branches=(("proceed",),),
            chip=GateChip("≈", "flake", "not-a-color"),
        )
    )
    title = modal._title()

    assert "[bold]≈ flake[/]" in title
    assert "not-a-color" not in title


def test_title_escapes_markup_in_chip_glyph_and_label() -> None:
    modal = CustomGateModal(
        data(
            options=(option("proceed"),),
            branches=(("proceed",),),
            chip=GateChip("[", "x[/]y"),
        )
    )
    title = modal._title()

    assert f"[bold]{escape('[')} {escape('x[/]y')}[/]" in title
    assert "[ x[/]y" in Text.from_markup(title).plain


async def test_header_uses_adapter_title_and_omits_absent_filer() -> None:
    modal = CustomGateModal(
        data(
            options=(option("proceed"),),
            branches=(("proceed",),),
            title="Task Triage",
        )
    )

    async with GateTestApp().run_test(size=(120, 40)) as pilot:
        pilot.app.push_screen(modal)
        await pilot.pause()

        rendered = modal.query_one("#custom-gate-title", Static).render().plain
        assert "Task Triage" in rendered
        assert "Custom Gate" not in rendered
        assert not modal.query("#custom-gate-origin")


async def test_declared_origin_agent_renders_filed_by_above_context() -> None:
    modal = CustomGateModal(
        data(
            options=(option("proceed"),),
            branches=(("proceed",),),
            origin_agent="claude_coder",
        )
    )

    async with GateTestApp().run_test(size=(120, 40)) as pilot:
        pilot.app.push_screen(modal)
        await pilot.pause()

        origin = modal.query_one("#custom-gate-origin", Static)
        assert origin.render().plain == "Filed by @claude_coder"
        assert origin.has_class("gate-review-origin")

        siblings = list(modal.query_one("#custom-gate-review-scroll").children)
        context_index = next(
            index
            for index, widget in enumerate(siblings)
            if isinstance(widget, Static) and widget.render().plain == "Context"
        )
        assert siblings.index(origin) < context_index
