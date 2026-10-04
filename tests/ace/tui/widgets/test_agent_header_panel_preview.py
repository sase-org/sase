"""Collapsed RAW PROMPT preview card behavior for the header panel."""

from __future__ import annotations

import dataclasses
from typing import Any

import pytest
from rich.text import Text

from sase.ace.tui.widgets.agent_detail import AgentDetail
from sase.ace.tui.widgets.agent_header_panel import AgentHeaderPanel
from sase.ace.tui.widgets.prompt_panel import AgentPromptPanel
from sase.ace.tui.widgets.renderable_text import renderable_to_text
from sase.ace.tui.widgets.agent_header_preview import preview_row_budget
from sase.ace.tui.agent_header_settings import AgentHeaderSettings
from tests.ace.tui.widgets._agent_display_helpers import make_agent
from tests.ace.tui.widgets._agent_header_panel_shared import (
    LONG_XPROMPT,
    DetailApp,
    artifact_agent,
    header_panel,
    header_text,
    show_agent,
    show_agent_full,
    solo_agent,
)

_SHORT_XPROMPT = "Fix the typo on the launch line."


def _preview_rows(panel: AgentHeaderPanel) -> int:
    return int(panel._last_preview_rows)  # noqa: SLF001


def _raw_rows(panel: AgentHeaderPanel) -> list[str]:
    """Return the painted rows with their padding (``header_text`` rstrips)."""
    content = panel.query_one("#agent-header-content")
    painted = getattr(content, "content", None)
    assert isinstance(painted, Text)
    return painted.plain.split("\n")


def _assert_card(panel: AgentHeaderPanel) -> list[str]:
    """Assert the collapsed header ends in a RAW PROMPT card; return its body rows."""
    rows = _raw_rows(panel)
    body_rows = _preview_rows(panel)
    assert body_rows >= 1
    assert len(rows) == 2 + 1 + body_rows
    assert rows[2].rstrip() == "▎ RAW PROMPT"
    body = rows[3:]
    for row in body:
        assert row.startswith("▎ ")
    return body


def _tagged(agent: Any, tag: str) -> Any:
    return dataclasses.replace(agent, cl_name=f"cl-{tag}", raw_suffix=tag)


async def test_collapsed_preview_shows_quote_bar_and_body_omits_xprompt(
    tmp_path: Any,
) -> None:
    app = DetailApp()
    async with app.run_test(size=(80, 24)) as pilot:
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        await show_agent_full(
            detail, artifact_agent(tmp_path, "a", LONG_XPROMPT), pilot
        )
        panel = header_panel(detail)
        assert not panel.is_expanded
        _assert_card(panel)
        assert "rendering the AGENT RAW PROMPT" in header_text(panel)
        prompt = detail.query_one("#agent-prompt-panel", AgentPromptPanel)
        body = renderable_to_text(prompt.content) or ""
        assert "AGENT RAW PROMPT" not in body
        assert "AGENT PROMPT" in body


async def test_preview_row_count_matches_budget_and_short_prompt_fits(
    tmp_path: Any,
) -> None:
    app = DetailApp()
    async with app.run_test(size=(80, 24)) as pilot:
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        await show_agent_full(
            detail, artifact_agent(tmp_path, "a", LONG_XPROMPT), pilot
        )
        panel = header_panel(detail)
        expected = preview_row_budget(
            int(panel._column_rows),
            0.35,
            max_rows=3,  # noqa: SLF001
        )
        assert 1 <= expected <= 3
        assert _preview_rows(panel) == expected
        assert "lines · " in str(panel.border_subtitle)

        await show_agent_full(
            detail, artifact_agent(tmp_path, "b", _SHORT_XPROMPT), pilot
        )
        panel = header_panel(detail)
        assert _preview_rows(panel) == 1
        assert _assert_card(panel)[-1].startswith("▎ ")
        assert "lines" not in str(panel.border_subtitle)
        assert "more" in str(panel.border_subtitle)


async def test_overflow_subtitle_names_hidden_lines(tmp_path: Any) -> None:
    app = DetailApp()
    async with app.run_test(size=(80, 24)) as pilot:
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        await show_agent_full(
            detail, artifact_agent(tmp_path, "a", LONG_XPROMPT), pilot
        )
        panel = header_panel(detail)
        subtitle = str(panel.border_subtitle)
        assert "lines · " in subtitle
        assert "more" in subtitle
        assert header_text(panel).splitlines()[-1].rstrip().endswith("…")


async def test_expand_shows_full_xprompt_and_toggles_back(tmp_path: Any) -> None:
    app = DetailApp()
    async with app.run_test(size=(80, 24)) as pilot:
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        await show_agent_full(
            detail, artifact_agent(tmp_path, "a", LONG_XPROMPT), pilot
        )
        panel = header_panel(detail)

        assert detail.toggle_header_expanded() is True
        await pilot.pause()
        expanded = header_text(panel)
        assert "AGENT RAW PROMPT" in expanded
        assert "some fenced code block line" in expanded
        assert "less" in str(panel.border_subtitle)

        assert detail.toggle_header_expanded() is False
        await pilot.pause()
        _assert_card(panel)
        collapsed = header_text(panel).splitlines()
        assert not any(line.strip() == "AGENT RAW PROMPT" for line in collapsed)


def test_no_phantom_row_rule_in_stylesheet() -> None:
    from pathlib import Path

    tcss = Path("src/sase/ace/tui/styles.tcss").read_text(encoding="utf-8")
    for selector in ("#agent-header-panel", "#agent-jump-panel"):
        start = tcss.index(selector + " {")
        block = tcss[start : tcss.index("}", start)]
        assert "scrollbar-size-horizontal: 0;" in block


async def test_collapsed_content_rows_are_exact(tmp_path: Any) -> None:
    app = DetailApp()
    async with app.run_test(size=(80, 24)) as pilot:
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        await show_agent_full(
            detail, artifact_agent(tmp_path, "a", LONG_XPROMPT), pilot
        )
        panel = header_panel(detail)
        _assert_card(panel)

        await show_agent_full(
            detail, artifact_agent(tmp_path, "b", _SHORT_XPROMPT), pilot
        )
        _assert_card(panel)
        assert _preview_rows(panel) == 1
        assert panel.rendered_row_count == 2 + 1 + 1


async def test_pending_hold_keeps_rows_then_settles(tmp_path: Any) -> None:
    app = DetailApp()
    async with app.run_test(size=(80, 24)) as pilot:
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        await show_agent_full(
            detail, artifact_agent(tmp_path, "a", LONG_XPROMPT), pilot
        )
        panel = header_panel(detail)
        held = _preview_rows(panel)
        assert held >= 1

        other = _tagged(solo_agent(), "b")
        await show_agent(detail, other, pilot)
        assert _preview_rows(panel) == held
        held_rows = _assert_card(panel)
        assert held_rows[0].startswith("▎ ⋯")
        assert all("⋯" not in row for row in held_rows[1:])
        assert panel.rendered_row_count == 2 + 1 + held

        await show_agent_full(detail, other, pilot)
        assert _preview_rows(panel) == 0
        assert len(header_text(panel).splitlines()) == 2


async def test_visited_agent_cheap_path_shows_preview(tmp_path: Any) -> None:
    app = DetailApp()
    async with app.run_test(size=(80, 24)) as pilot:
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        agent = artifact_agent(tmp_path, "a", LONG_XPROMPT)
        await show_agent_full(detail, agent, pilot)
        panel = header_panel(detail)
        full_rows = _preview_rows(panel)
        assert full_rows >= 1

        await show_agent(
            detail, _tagged(make_agent(agent_name="other"), "other"), pilot
        )
        await show_agent(detail, agent, pilot)
        assert _preview_rows(panel) == full_rows
        _assert_card(panel)


async def test_share_zero_hides_preview_but_expanded_keeps_xprompt(
    tmp_path: Any,
) -> None:
    app = DetailApp()
    async with app.run_test(size=(80, 24)) as pilot:
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        app._agent_header_settings = AgentHeaderSettings(collapsed_max_share=0.0)  # noqa: SLF001
        await show_agent_full(
            detail, artifact_agent(tmp_path, "a", LONG_XPROMPT), pilot
        )
        panel = header_panel(detail)
        assert _preview_rows(panel) == 0
        assert panel.rendered_row_count == 2
        rows = header_text(panel).splitlines()
        assert len(rows) == 2
        assert not any("RAW PROMPT" in row for row in rows)

        assert detail.toggle_header_expanded() is True
        await pilot.pause()
        assert "AGENT RAW PROMPT" in header_text(panel)


async def test_column_resize_changes_budget(tmp_path: Any) -> None:
    import types

    app = DetailApp()
    async with app.run_test(size=(80, 24)) as pilot:
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        await show_agent_full(
            detail, artifact_agent(tmp_path, "a", LONG_XPROMPT), pilot
        )
        panel = header_panel(detail)
        detail.on_resize(types.SimpleNamespace(size=types.SimpleNamespace(height=100)))
        await pilot.pause()
        assert _preview_rows(panel) == 3
        assert header_text(panel).splitlines()[-1].rstrip().endswith("…")
        assert "lines · " in str(panel.border_subtitle)

        detail.on_resize(types.SimpleNamespace(size=types.SimpleNamespace(height=12)))
        await pilot.pause()
        assert 1 <= _preview_rows(panel) < 3


async def test_exact_fit_shows_no_ellipsis_or_count(tmp_path: Any) -> None:
    from sase.ace.tui.widgets.agent_header_preview import fit_xprompt_preview

    app = DetailApp()
    async with app.run_test(size=(80, 24)) as pilot:
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        await show_agent_full(
            detail, artifact_agent(tmp_path, "a", LONG_XPROMPT), pilot
        )
        panel = header_panel(detail)
        width = panel._content_width()  # noqa: SLF001
        prompt: str | None = None
        for count in range(5, 200):
            candidate = " ".join(f"word{i:03d}" for i in range(count))
            fit = fit_xprompt_preview(Text(candidate), width=width, max_rows=100)
            if fit.rows == 3 and not fit.truncated:
                prompt = candidate
                break
        assert prompt is not None
        await show_agent_full(detail, artifact_agent(tmp_path, "b", prompt), pilot)
        panel = header_panel(detail)
        assert _preview_rows(panel) == 3
        assert not header_text(panel).splitlines()[-1].rstrip().endswith("…")
        assert "lines" not in str(panel.border_subtitle)


async def test_row_cap_setting_changes_collapsed_rows(tmp_path: Any) -> None:
    import types

    app = DetailApp()
    async with app.run_test(size=(80, 24)) as pilot:
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        app._agent_header_settings = AgentHeaderSettings(  # noqa: SLF001
            collapsed_preview_max_rows=5
        )
        await show_agent_full(
            detail, artifact_agent(tmp_path, "a", LONG_XPROMPT), pilot
        )
        panel = header_panel(detail)
        detail.on_resize(types.SimpleNamespace(size=types.SimpleNamespace(height=100)))
        await pilot.pause()
        assert _preview_rows(panel) == 5

        app._agent_header_settings = AgentHeaderSettings(  # noqa: SLF001
            collapsed_preview_max_rows=1
        )
        panel.show_identity(panel._identity)  # noqa: SLF001
        await pilot.pause()
        assert _preview_rows(panel) == 1


async def test_hidden_line_subtitle_uses_singular_for_one_line(tmp_path: Any) -> None:
    app = DetailApp()
    async with app.run_test(size=(80, 24)) as pilot:
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        await show_agent_full(
            detail, artifact_agent(tmp_path, "a", LONG_XPROMPT), pilot
        )
        panel = header_panel(detail)
        assert "+1 line · " in panel._subtitle_for(False, hidden_lines=1)  # noqa: SLF001
        assert "+2 lines · " in panel._subtitle_for(False, hidden_lines=2)  # noqa: SLF001
        assert "+12 lines · " in panel._subtitle_for(False, hidden_lines=12)  # noqa: SLF001


async def test_card_rows_are_padded_and_repaint_on_width_change(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from rich.cells import cell_len

    app = DetailApp()
    async with app.run_test(size=(120, 40)) as pilot:
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        await show_agent_full(
            detail, artifact_agent(tmp_path, "a", LONG_XPROMPT), pilot
        )
        panel = header_panel(detail)
        for width in (90, 60, 75):
            monkeypatch.setattr(panel, "_content_width", lambda width=width: width)
            panel.on_resize()
            assert {cell_len(row) for row in _assert_card(panel)} == {width}


async def test_bottom_pinned_body_stays_pinned_across_row_count_change(
    tmp_path: Any,
) -> None:
    app = DetailApp()
    async with app.run_test(size=(80, 24)) as pilot:
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        await show_agent_full(
            detail, artifact_agent(tmp_path, "a", _SHORT_XPROMPT), pilot
        )
        panel = header_panel(detail)
        before = panel.rendered_row_count
        main_view = detail.deck_area.panel(0).main_view
        main_view.pin_to_bottom()
        assert bool(main_view.is_pinned_to_bottom) is True
        await show_agent_full(
            detail, artifact_agent(tmp_path, "b", LONG_XPROMPT), pilot
        )
        assert panel.rendered_row_count != before
        assert bool(main_view.is_pinned_to_bottom) is True
