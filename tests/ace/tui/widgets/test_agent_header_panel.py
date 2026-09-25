"""Mounted header-panel behavior for the Agents tab sticky identity header."""

from __future__ import annotations

import dataclasses
from datetime import datetime
from typing import Any

import pytest
from rich.text import Text
from textual.app import App, ComposeResult
from sase.ace.tui._app_action_availability import check_app_action
from sase.ace.tui.widgets.agent_detail import AgentDetail
from sase.ace.tui.widgets.agent_header_panel import AgentHeaderPanel
from sase.ace.tui.widgets.prompt_panel import AgentPromptPanel
from sase.ace.tui.widgets.prompt_panel._agent_display_header import build_header_text
from sase.ace.tui.widgets.prompt_panel._agent_display_header_renderable import (
    AgentHeaderRenderable,
)
from sase.ace.tui.widgets.prompt_panel._identity_header import find_identity_header
from sase.ace.tui.widgets.renderable_text import renderable_to_text
from sase.ace.tui.widgets.agent_header_preview import preview_row_budget
from sase.ace.tui.agent_header_settings import AgentHeaderSettings
from tests.ace.tui.widgets._agent_display_clan_helpers import make_clan_agent
from tests.ace.tui.widgets._agent_display_helpers import (
    make_agent,
    make_artifact_agent,
)
from tests.ace.tui.widgets._agent_display_tribe_helpers import make_tribe_snapshot

from sase.ace.tui.models._agent_tree import project_clan_tree


def _solo() -> Any:
    return make_agent(agent_name="solo")


class _DetailApp(App[None]):
    def compose(self) -> ComposeResult:
        yield AgentDetail(id="agent-detail-panel")


async def _show_agent(detail: AgentDetail, agent: Any, pilot: Any) -> None:
    detail.update_display_immediate(agent)
    await pilot.pause()


async def _show_agent_full(detail: AgentDetail, agent: Any, pilot: Any) -> None:
    detail.update_display(agent)
    await pilot.pause()


def _preview_rows(panel: AgentHeaderPanel) -> int:
    return int(panel._last_preview_rows)  # noqa: SLF001


_LONG_XPROMPT = (
    "Can you help me start rendering the AGENT XPROMPT section in the sticky "
    "header above the agent data deck panel? Make sure that we provide a good "
    "preview of the contents in this section.\n"
    "\n"
    "- first list item explains the quote bar\n"
    "- second list item explains the row budget\n"
    "```\n"
    "some fenced code block line\n"
    "```\n"
    "A final hard-wrapped prose paragraph keeps going so the preview budget "
    "overflows and the border subtitle names the hidden line count."
)

_SHORT_XPROMPT = "Fix the typo on the launch line."


def _artifact_agent(tmp_path: Any, name: str, raw_xprompt: str) -> Any:
    import dataclasses

    subdir = tmp_path / name
    subdir.mkdir(exist_ok=True)
    agent = make_artifact_agent(subdir, status="DONE", raw_xprompt=raw_xprompt)
    return dataclasses.replace(agent, cl_name=f"cl-{name}", raw_suffix=name)


def _tagged(agent: Any, tag: str) -> Any:
    import dataclasses

    return dataclasses.replace(agent, cl_name=f"cl-{tag}", raw_suffix=tag)


def _header_panel(detail: AgentDetail) -> AgentHeaderPanel:
    return detail.query_one("#agent-header-panel", AgentHeaderPanel)


def _header_text(panel: AgentHeaderPanel) -> str:
    content = panel.query_one("#agent-header-content")
    return renderable_to_text(getattr(content, "content", None)) or ""


def _raw_rows(panel: AgentHeaderPanel) -> list[str]:
    """Return the painted rows with their padding (``_header_text`` rstrips)."""
    content = panel.query_one("#agent-header-content")
    painted = getattr(content, "content", None)
    assert isinstance(painted, Text)
    return painted.plain.split("\n")


def _assert_card(panel: AgentHeaderPanel) -> list[str]:
    """Assert the collapsed header ends in an XPROMPT card; return its body rows."""
    rows = _raw_rows(panel)
    body_rows = _preview_rows(panel)
    assert body_rows >= 1
    assert len(rows) == 2 + 1 + body_rows
    assert rows[2].rstrip() == "▎ XPROMPT"
    body = rows[3:]
    for row in body:
        assert row.startswith("▎ ")
    return body


async def test_header_collapsed_by_default_with_title_and_hint() -> None:
    app = _DetailApp()
    async with app.run_test(size=(80, 24)) as pilot:
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        await _show_agent(detail, _solo(), pilot)
        panel = _header_panel(detail)
        assert not panel.has_class("hidden")
        assert panel.has_identity
        assert not panel.is_expanded
        assert detail.header_toggle_available() is True
        assert panel.border_title is not None
        assert "AGENT SHELL" in str(panel.border_title)
        assert "more" in str(panel.border_subtitle)
        assert "d" in str(panel.border_subtitle)
        rows = _header_text(panel).splitlines()
        assert len(rows) == 2


async def test_toggle_expands_to_full_fields_and_back() -> None:
    app = _DetailApp()
    async with app.run_test(size=(80, 24)) as pilot:
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        await _show_agent(detail, _solo(), pilot)
        panel = _header_panel(detail)

        assert detail.toggle_header_expanded() is True
        assert panel.is_expanded
        assert "less" in str(panel.border_subtitle)
        assert "Name:" in _header_text(panel)

        assert detail.toggle_header_expanded() is False
        assert not panel.is_expanded
        assert "more" in str(panel.border_subtitle)
        assert len(_header_text(panel).splitlines()) == 2


async def test_body_excludes_identity_lines() -> None:
    app = _DetailApp()
    async with app.run_test(size=(80, 24)) as pilot:
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        await _show_agent(detail, _solo(), pilot)
        prompt = detail.query_one("#agent-prompt-panel", AgentPromptPanel)
        body = renderable_to_text(prompt.content) or ""
        assert "AGENT SHELL" not in body
        combined = renderable_to_text(prompt.inline_document_renderable()) or ""
        assert "AGENT SHELL" in combined
        assert "Name:" in combined


async def test_expanded_state_persists_across_selection_and_tribe() -> None:
    app = _DetailApp()
    async with app.run_test(size=(80, 24)) as pilot:
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        await _show_agent(detail, _solo(), pilot)
        assert detail.toggle_header_expanded() is True

        await _show_agent(detail, make_agent(agent_name="other"), pilot)
        panel = _header_panel(detail)
        assert panel.is_expanded
        assert "Name:" in _header_text(panel)

        detail.show_tribe_summary(make_tribe_snapshot())
        await pilot.pause()
        assert panel.is_expanded
        assert "TRIBE" in str(panel.border_title)


async def test_clan_selection_shows_header() -> None:
    member = make_clan_agent(
        "clan-test", status="RUNNING", start=datetime(2024, 1, 1), stop=None
    )
    container = project_clan_tree([member])[0]
    assert container.is_clan_container
    app = _DetailApp()
    async with app.run_test(size=(80, 24)) as pilot:
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        await _show_agent(detail, _solo(), pilot)
        assert detail.header_toggle_available() is True

        await _show_agent(detail, container, pilot)
        panel = _header_panel(detail)
        assert not panel.has_class("hidden")
        assert panel.has_identity
        assert detail.header_toggle_available() is True
        assert "CLAN" in str(panel.border_title)
        assert not panel.is_expanded
        assert len(_header_text(panel).splitlines()) == 2

        assert detail.toggle_header_expanded() is True
        await pilot.pause()
        assert "Name:" in _header_text(panel)
        assert "Status:" in _header_text(panel)

        assert detail.toggle_header_expanded() is False
        await pilot.pause()
        assert len(_header_text(panel).splitlines()) == 2

        await _show_agent(detail, _solo(), pilot)
        assert not panel.is_expanded
        assert detail.toggle_header_expanded() is True
        await _show_agent(detail, container, pilot)
        assert panel.is_expanded
        assert "Name:" in _header_text(panel)


async def test_secondary_only_keeps_header_visible_and_toggleable() -> None:
    from sase.ace.tui.widgets.decks.model import DeckId, DeckLayout

    app = _DetailApp()
    async with app.run_test(size=(80, 24)) as pilot:
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        await _show_agent(detail, _solo(), pilot)
        panel = _header_panel(detail)

        detail.toggle_deck_split(DeckLayout.LEFT_RIGHT)
        await pilot.pause()
        detail.show_deck(0, DeckId.MAIN)
        detail.show_deck(1, DeckId.FILES)
        await pilot.pause()
        assert not panel.has_class("hidden")
        assert detail.header_toggle_available() is True
        assert detail.toggle_header_expanded() is True
        await pilot.pause()
        assert "Name:" in _header_text(panel)
        assert detail.toggle_header_expanded() is False
        await pilot.pause()
        assert not panel.has_class("hidden")
        assert detail.header_toggle_available() is True


async def test_search_overlay_keeps_header_visible() -> None:
    from sase.ace.tui.widgets.decks.model import DeckId

    app = _DetailApp()
    async with app.run_test(size=(80, 24)) as pilot:
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        await _show_agent(detail, _solo(), pilot)
        detail.show_deck(0, DeckId.TOOLS)
        await pilot.pause()
        panel = _header_panel(detail)
        assert not panel.has_class("hidden")
        assert detail.header_toggle_available() is True
        detail.show_deck(0, DeckId.MAIN)
        await pilot.pause()
        assert not panel.has_class("hidden")


async def test_hint_document_forces_expansion() -> None:
    agent = _solo()
    document, _ = build_header_text(agent, cheap=True, detach_identity=True)
    assert isinstance(document, AgentHeaderRenderable)
    identity = find_identity_header(document)
    assert identity is not None
    hinted = dataclasses.replace(identity, has_hints=True)
    app = _DetailApp()
    async with app.run_test(size=(80, 24)) as pilot:
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        await _show_agent(detail, agent, pilot)
        panel = _header_panel(detail)
        assert not panel.is_expanded
        panel.show_identity(hinted)
        assert "Name:" in _header_text(panel)


async def test_bottom_pinned_body_stays_pinned_across_toggle() -> None:
    from sase.ace.tui.widgets.decks.model import DeckId, DeckLayout

    app = _DetailApp()
    async with app.run_test(size=(80, 24)) as pilot:
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        await _show_agent(detail, _solo(), pilot)
        detail.toggle_deck_split(DeckLayout.LEFT_RIGHT)
        await pilot.pause()
        detail.show_deck(0, DeckId.MAIN)
        detail.show_deck(1, DeckId.FILES)
        await pilot.pause()
        main_view = detail.deck_area.panel(0).main_view
        main_view.pin_to_bottom()
        assert bool(main_view.is_pinned_to_bottom) is True
        detail.toggle_header_expanded()
        await pilot.pause()
        assert bool(main_view.is_pinned_to_bottom) is True


async def test_empty_state_hides_header() -> None:
    app = _DetailApp()
    async with app.run_test(size=(80, 24)) as pilot:
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        await _show_agent(detail, _solo(), pilot)
        assert detail.header_toggle_available() is True
        detail.show_empty()
        await pilot.pause()
        panel = _header_panel(detail)
        assert panel.has_class("hidden")
        assert detail.header_toggle_available() is False


def _fallback(_action: str, _parameters: tuple[object, ...]) -> bool:
    return True


class _FakeAgentsApp:
    current_tab = "agents"
    _screen_stack = ("screen",)

    def __init__(self, *, prompt_active: bool, detail: Any) -> None:
        self._prompt_active = prompt_active
        self._detail = detail

    def _prompt_input_active(self) -> bool:
        return self._prompt_active

    def query_one(self, _selector: str, _type: Any = None) -> Any:
        return self._detail


class _FakeDetail:
    def __init__(self, *, available: bool) -> None:
        self._available = available

    def header_toggle_available(self) -> bool:
        return self._available


def test_toggle_unavailable_while_prompt_input_owns_keys() -> None:
    available = _FakeAgentsApp(prompt_active=False, detail=_FakeDetail(available=True))
    assert check_app_action(available, "toggle_agent_header", (), _fallback) is True
    busy = _FakeAgentsApp(prompt_active=True, detail=_FakeDetail(available=True))
    assert check_app_action(busy, "toggle_agent_header", (), _fallback) is False
    hidden = _FakeAgentsApp(prompt_active=False, detail=_FakeDetail(available=False))
    assert check_app_action(hidden, "toggle_agent_header", (), _fallback) is False


async def test_collapsed_preview_shows_quote_bar_and_body_omits_xprompt(
    tmp_path: Any,
) -> None:
    app = _DetailApp()
    async with app.run_test(size=(80, 24)) as pilot:
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        await _show_agent_full(
            detail, _artifact_agent(tmp_path, "a", _LONG_XPROMPT), pilot
        )
        panel = _header_panel(detail)
        assert not panel.is_expanded
        _assert_card(panel)
        assert "rendering the AGENT XPROMPT" in _header_text(panel)
        prompt = detail.query_one("#agent-prompt-panel", AgentPromptPanel)
        body = renderable_to_text(prompt.content) or ""
        assert "AGENT XPROMPT" not in body
        assert "AGENT PROMPT" in body


async def test_preview_row_count_matches_budget_and_short_prompt_fits(
    tmp_path: Any,
) -> None:
    app = _DetailApp()
    async with app.run_test(size=(80, 24)) as pilot:
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        await _show_agent_full(
            detail, _artifact_agent(tmp_path, "a", _LONG_XPROMPT), pilot
        )
        panel = _header_panel(detail)
        expected = preview_row_budget(int(panel._column_rows), 0.35)  # noqa: SLF001
        assert expected >= 1
        assert _preview_rows(panel) == expected
        assert "lines · " in str(panel.border_subtitle)

        await _show_agent_full(
            detail, _artifact_agent(tmp_path, "b", _SHORT_XPROMPT), pilot
        )
        panel = _header_panel(detail)
        assert _preview_rows(panel) == 1
        assert _assert_card(panel)[-1].startswith("▎ ")
        assert "lines" not in str(panel.border_subtitle)
        assert "more" in str(panel.border_subtitle)


async def test_overflow_subtitle_names_hidden_lines(tmp_path: Any) -> None:
    app = _DetailApp()
    async with app.run_test(size=(80, 24)) as pilot:
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        await _show_agent_full(
            detail, _artifact_agent(tmp_path, "a", _LONG_XPROMPT), pilot
        )
        panel = _header_panel(detail)
        subtitle = str(panel.border_subtitle)
        assert "lines · " in subtitle
        assert "more" in subtitle
        assert _header_text(panel).splitlines()[-1].rstrip().endswith("…")


async def test_expand_shows_full_xprompt_and_toggles_back(tmp_path: Any) -> None:
    app = _DetailApp()
    async with app.run_test(size=(80, 24)) as pilot:
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        await _show_agent_full(
            detail, _artifact_agent(tmp_path, "a", _LONG_XPROMPT), pilot
        )
        panel = _header_panel(detail)

        assert detail.toggle_header_expanded() is True
        await pilot.pause()
        expanded = _header_text(panel)
        assert "AGENT XPROMPT" in expanded
        assert "some fenced code block line" in expanded
        assert "less" in str(panel.border_subtitle)

        assert detail.toggle_header_expanded() is False
        await pilot.pause()
        _assert_card(panel)
        collapsed = _header_text(panel).splitlines()
        assert not any(line.strip() == "AGENT XPROMPT" for line in collapsed)


def test_no_phantom_row_rule_in_stylesheet() -> None:
    from pathlib import Path

    tcss = Path("src/sase/ace/tui/styles.tcss").read_text(encoding="utf-8")
    for selector in ("#agent-header-panel", "#agent-jump-panel"):
        start = tcss.index(selector + " {")
        block = tcss[start : tcss.index("}", start)]
        assert "scrollbar-size-horizontal: 0;" in block


async def test_collapsed_content_rows_are_exact(tmp_path: Any) -> None:
    app = _DetailApp()
    async with app.run_test(size=(80, 24)) as pilot:
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        await _show_agent_full(
            detail, _artifact_agent(tmp_path, "a", _LONG_XPROMPT), pilot
        )
        panel = _header_panel(detail)
        _assert_card(panel)

        await _show_agent_full(
            detail, _artifact_agent(tmp_path, "b", _SHORT_XPROMPT), pilot
        )
        _assert_card(panel)
        assert _preview_rows(panel) == 1
        assert panel.rendered_row_count == 2 + 1 + 1


async def test_pending_hold_keeps_rows_then_settles(tmp_path: Any) -> None:
    app = _DetailApp()
    async with app.run_test(size=(80, 24)) as pilot:
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        await _show_agent_full(
            detail, _artifact_agent(tmp_path, "a", _LONG_XPROMPT), pilot
        )
        panel = _header_panel(detail)
        held = _preview_rows(panel)
        assert held >= 1

        other = _tagged(_solo(), "b")
        await _show_agent(detail, other, pilot)
        assert _preview_rows(panel) == held
        held_rows = _assert_card(panel)
        assert held_rows[0].startswith("▎ ⋯")
        assert all("⋯" not in row for row in held_rows[1:])
        assert panel.rendered_row_count == 2 + 1 + held

        await _show_agent_full(detail, other, pilot)
        assert _preview_rows(panel) == 0
        assert len(_header_text(panel).splitlines()) == 2


async def test_visited_agent_cheap_path_shows_preview(tmp_path: Any) -> None:
    app = _DetailApp()
    async with app.run_test(size=(80, 24)) as pilot:
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        agent = _artifact_agent(tmp_path, "a", _LONG_XPROMPT)
        await _show_agent_full(detail, agent, pilot)
        panel = _header_panel(detail)
        full_rows = _preview_rows(panel)
        assert full_rows >= 1

        await _show_agent(
            detail, _tagged(make_agent(agent_name="other"), "other"), pilot
        )
        await _show_agent(detail, agent, pilot)
        assert _preview_rows(panel) == full_rows
        _assert_card(panel)


async def test_share_zero_hides_preview_but_expanded_keeps_xprompt(
    tmp_path: Any,
) -> None:
    app = _DetailApp()
    async with app.run_test(size=(80, 24)) as pilot:
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        app._agent_header_settings = AgentHeaderSettings(collapsed_max_share=0.0)  # noqa: SLF001
        await _show_agent_full(
            detail, _artifact_agent(tmp_path, "a", _LONG_XPROMPT), pilot
        )
        panel = _header_panel(detail)
        assert _preview_rows(panel) == 0
        assert panel.rendered_row_count == 2
        rows = _header_text(panel).splitlines()
        assert len(rows) == 2
        assert not any("XPROMPT" in row for row in rows)

        assert detail.toggle_header_expanded() is True
        await pilot.pause()
        assert "AGENT XPROMPT" in _header_text(panel)


async def test_column_resize_changes_budget(tmp_path: Any) -> None:
    import types

    app = _DetailApp()
    async with app.run_test(size=(80, 24)) as pilot:
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        await _show_agent_full(
            detail, _artifact_agent(tmp_path, "a", _LONG_XPROMPT), pilot
        )
        panel = _header_panel(detail)
        before = _preview_rows(panel)
        detail.on_resize(types.SimpleNamespace(size=types.SimpleNamespace(height=100)))
        await pilot.pause()
        assert _preview_rows(panel) > before
        assert "lines" not in str(panel.border_subtitle)


async def test_card_rows_are_padded_and_repaint_on_width_change(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from rich.cells import cell_len

    app = _DetailApp()
    async with app.run_test(size=(120, 40)) as pilot:
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        await _show_agent_full(
            detail, _artifact_agent(tmp_path, "a", _LONG_XPROMPT), pilot
        )
        panel = _header_panel(detail)
        for width in (90, 60, 75):
            monkeypatch.setattr(panel, "_content_width", lambda width=width: width)
            panel.on_resize()
            assert {cell_len(row) for row in _assert_card(panel)} == {width}


async def test_bottom_pinned_body_stays_pinned_across_row_count_change(
    tmp_path: Any,
) -> None:
    app = _DetailApp()
    async with app.run_test(size=(80, 24)) as pilot:
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        await _show_agent_full(
            detail, _artifact_agent(tmp_path, "a", _SHORT_XPROMPT), pilot
        )
        panel = _header_panel(detail)
        before = panel.rendered_row_count
        main_view = detail.deck_area.panel(0).main_view
        main_view.pin_to_bottom()
        assert bool(main_view.is_pinned_to_bottom) is True
        await _show_agent_full(
            detail, _artifact_agent(tmp_path, "b", _LONG_XPROMPT), pilot
        )
        assert panel.rendered_row_count != before
        assert bool(main_view.is_pinned_to_bottom) is True
