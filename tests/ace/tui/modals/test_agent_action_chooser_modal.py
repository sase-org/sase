"""Behavioral coverage for the agent action chooser modal."""

from __future__ import annotations

from xml.etree import ElementTree

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.modals.agent_action_chooser_modal import (
    AgentActionChoice,
    AgentActionChooserModal,
)


def _svg_text(page: AcePage) -> str:
    """Return decoded text content from the exported SVG screenshot."""
    root = ElementTree.fromstring(page.export_svg(title="chooser assertion"))
    nodes = (
        "".join(element.itertext())
        for element in root.iter()
        if element.tag.rsplit("}", 1)[-1] == "text"
    )
    return "\n".join(nodes).replace("\xa0", " ")


def _gate(
    label: str = "Review tale plan",
    result: str = "gate:abc123",
    detail: str | None = "sase_plan_enter_keymap.md",
    badge: str | None = "TALE",
    age: str | None = "12m",
) -> AgentActionChoice:
    return AgentActionChoice(
        result=result,
        section="gate",
        label=label,
        detail=detail,
        glyph="⋔",
        glyph_style="bold #0BCDEC",
        badge=badge,
        badge_style="bold #0BCDEC",
        age=age,
    )


def _patch(
    label: str = "Go to Patch",
    result: str = "patch:foo",
    detail: str | None = "foo enter keymap · PR #123",
    badge: str | None = "Mailed",
) -> AgentActionChoice:
    return AgentActionChoice(
        result=result,
        section="patch",
        label=label,
        detail=detail,
        glyph="⎇",
        glyph_style="#00D787",
        badge=badge,
        badge_style="#00D787",
        age=None,
    )


def test_chooser_rejects_empty_choices() -> None:
    with pytest.raises(ValueError, match="at least one choice"):
        AgentActionChooserModal((), title="Act on foo.bar")


def test_chooser_key_assignment_single_gate_and_patch() -> None:
    modal = AgentActionChooserModal((_gate(), _patch()), title="Act on foo.bar")

    assert modal.key_to_index == {"g": 0, "p": 1}
    assert modal.display_key(0) == "g"
    assert modal.display_key(1) == "p"
    assert modal.primary_label == "Review tale plan"
    assert modal.guidance_text == "⏎ again → Review tale plan · or press a key"


def test_chooser_key_assignment_multiple_gates_keeps_g_alias() -> None:
    modal = AgentActionChooserModal(
        (
            _gate("Review tale plan", result="gate:one"),
            _gate("Review sudo request", result="gate:two"),
            _gate("Answer question", result="gate:three"),
            _patch(),
        ),
        title="Act on foo.bar",
    )

    assert modal.key_to_index == {"1": 0, "2": 1, "3": 2, "g": 0, "p": 3}
    assert modal.display_key(0) == "1"
    assert modal.display_key(3) == "p"


def test_chooser_key_assignment_caps_digit_keys_at_nine() -> None:
    gates = tuple(_gate(f"Gate {n}", result=f"gate:{n}") for n in range(10))
    modal = AgentActionChooserModal(gates, title="Act on foo.bar")

    assert modal.key_to_index == {str(n + 1): n for n in range(9)} | {"g": 0}
    assert modal.display_key(8) == "9"
    assert modal.display_key(9) == ""


def test_chooser_key_assignment_gates_without_patch() -> None:
    modal = AgentActionChooserModal(
        (
            _gate("Review tale plan", result="gate:one"),
            _gate("Review sudo request", result="gate:two"),
        ),
        title="Act on foo.bar",
    )

    assert modal.key_to_index == {"1": 0, "2": 1, "g": 0}
    assert "p" not in modal.key_to_index


async def test_chooser_enter_selects_primary() -> None:
    results: list[str | None] = []
    async with AcePage() as page:
        modal = AgentActionChooserModal((_gate(), _patch()), title="Act on foo.bar")
        page.app.push_screen(modal, results.append)
        await page.expect_modal("AgentActionChooserModal")

        await page.press("enter")
        await page.expect_no_modal()
        assert results == ["gate:abc123"]


async def test_chooser_direct_keys_select_rows() -> None:
    results: list[str | None] = []
    async with AcePage() as page:
        modal = AgentActionChooserModal(
            (
                _gate("Review tale plan", result="gate:one"),
                _gate("Review sudo request", result="gate:two"),
                _patch(),
            ),
            title="Act on foo.bar",
        )
        page.app.push_screen(modal, results.append)
        await page.expect_modal("AgentActionChooserModal")

        await page.press("p")
        await page.expect_no_modal()
        assert results == ["patch:foo"]

    results.clear()
    async with AcePage() as page:
        modal = AgentActionChooserModal(
            (
                _gate("Review tale plan", result="gate:one"),
                _gate("Review sudo request", result="gate:two"),
                _patch(),
            ),
            title="Act on foo.bar",
        )
        page.app.push_screen(modal, results.append)
        await page.expect_modal("AgentActionChooserModal")

        await page.press("2")
        await page.expect_no_modal()
        assert results == ["gate:two"]

    results.clear()
    async with AcePage() as page:
        modal = AgentActionChooserModal(
            (
                _gate("Review tale plan", result="gate:one"),
                _gate("Review sudo request", result="gate:two"),
                _patch(),
            ),
            title="Act on foo.bar",
        )
        page.app.push_screen(modal, results.append)
        await page.expect_modal("AgentActionChooserModal")

        await page.press("g")
        await page.expect_no_modal()
        assert results == ["gate:one"]


async def test_chooser_navigation_wraps_and_enter_selects() -> None:
    results: list[str | None] = []
    async with AcePage() as page:
        modal = AgentActionChooserModal((_gate(), _patch()), title="Act on foo.bar")
        page.app.push_screen(modal, results.append)
        await page.expect_modal("AgentActionChooserModal")
        await page.wait_for(lambda _screen: bool(modal.query("#agent-action-row-1")))

        await page.press("k")
        assert modal.query_one("#agent-action-row-1").has_class("focused")

        await page.press("j")
        assert modal.query_one("#agent-action-row-0").has_class("focused")

        await page.press("down")
        assert modal.query_one("#agent-action-row-1").has_class("focused")

        await page.press("up")
        assert modal.query_one("#agent-action-row-0").has_class("focused")

        await page.press("enter")
        await page.expect_no_modal()
        assert results == ["gate:abc123"]


async def test_chooser_escape_and_q_cancel() -> None:
    results: list[str | None] = []
    async with AcePage() as page:
        modal = AgentActionChooserModal((_gate(), _patch()), title="Act on foo.bar")
        page.app.push_screen(modal, results.append)
        await page.expect_modal("AgentActionChooserModal")

        await page.press("escape")
        await page.expect_no_modal()
        assert results == [None]

    results.clear()
    async with AcePage() as page:
        modal = AgentActionChooserModal((_gate(), _patch()), title="Act on foo.bar")
        page.app.push_screen(modal, results.append)
        await page.expect_modal("AgentActionChooserModal")

        await page.press("q")
        await page.expect_no_modal()
        assert results == [None]


async def test_chooser_printable_keys_are_swallowed() -> None:
    results: list[str | None] = []
    async with AcePage() as page:
        modal = AgentActionChooserModal((_gate(), _patch()), title="Act on foo.bar")
        page.app.push_screen(modal, results.append)
        await page.expect_modal("AgentActionChooserModal")

        await page.press("z", "0", "x")
        await page.pause()

        assert page.state["modal"] == "AgentActionChooserModal"
        assert results == []

        await page.press("escape")
        await page.expect_no_modal()
        assert results == [None]


async def test_chooser_click_selects_row() -> None:
    results: list[str | None] = []
    async with AcePage() as page:
        page.app.push_screen(
            AgentActionChooserModal((_gate(), _patch()), title="Act on foo.bar"),
            results.append,
        )
        await page.expect_modal("AgentActionChooserModal")
        await page.wait_for(
            lambda _screen: bool(page.app.screen.query("#agent-action-row-1"))
        )

        await page.click("#agent-action-row-1")
        await page.expect_no_modal()

    assert results == ["patch:foo"]


async def test_chooser_dismisses_exactly_once() -> None:
    results: list[str | None] = []
    async with AcePage() as page:
        modal = AgentActionChooserModal((_gate(), _patch()), title="Act on foo.bar")
        page.app.push_screen(modal, results.append)
        await page.expect_modal("AgentActionChooserModal")

        await page.press("p")
        await page.expect_no_modal()
        assert results == ["patch:foo"]

        modal._dismiss_once("gate:abc123")
        await page.pause()
        assert results == ["patch:foo"]


async def test_chooser_guidance_names_primary_label() -> None:
    async with AcePage() as page:
        page.app.push_screen(
            AgentActionChooserModal((_gate(), _patch()), title="Act on foo.bar"),
            lambda _result: None,
        )
        await page.expect_modal("AgentActionChooserModal")
        await page.wait_for(
            lambda _screen: "Act on foo.bar" in _svg_text(page),
        )

        text = _svg_text(page)
        assert "Act on foo.bar" in text
        assert "⏎ again → Review tale plan · or press a key" in text
        assert "GATE" in text
        assert "PATCH" in text


_LONG_LABEL = "Review tale plan " + "QXZ" * 30
_LONG_DETAIL = "some/detail/path " + "QWZ" * 30


async def _expect_truncated(page: AcePage) -> None:
    await page.wait_for(
        lambda _screen: any(
            "Review tale plan" in node and "…" in node
            for node in _svg_text(page).splitlines()
        ),
    )
    text = _svg_text(page)
    assert "QXZ" * 30 not in text
    assert "QWZ" * 30 not in text


async def test_chooser_truncates_long_rows_at_60_columns() -> None:
    async with AcePage(size=(60, 30)) as page:
        page.app.push_screen(
            AgentActionChooserModal(
                (_gate(label=_LONG_LABEL, detail=_LONG_DETAIL), _patch()),
                title="Act on foo.bar",
            ),
            lambda _result: None,
        )
        await page.expect_modal("AgentActionChooserModal")
        await page.wait_for(
            lambda _screen: bool(page.app.screen.query("#agent-action-row-0"))
        )

        await _expect_truncated(page)


async def test_chooser_truncates_long_rows_at_120_columns() -> None:
    async with AcePage(size=(120, 30)) as page:
        page.app.push_screen(
            AgentActionChooserModal(
                (_gate(label=_LONG_LABEL, detail=_LONG_DETAIL), _patch()),
                title="Act on foo.bar",
            ),
            lambda _result: None,
        )
        await page.expect_modal("AgentActionChooserModal")
        await page.wait_for(
            lambda _screen: bool(page.app.screen.query("#agent-action-row-0"))
        )

        await _expect_truncated(page)
