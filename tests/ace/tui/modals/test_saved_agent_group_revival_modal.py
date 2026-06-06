"""Tests for the saved dismissed-agent group revival modal."""

from __future__ import annotations

from datetime import UTC, datetime

from textual.app import App
from textual.widgets import OptionList, Static

from sase.ace.tui.modals.saved_agent_group_revival_modal import (
    SavedAgentGroupRevivalModal,
    SavedAgentGroupRevivalResult,
)
from sase.ace.tui.modals.saved_agent_group_revival_rendering import (
    _saved_group_time_label,
    build_saved_group_preview,
    format_saved_group_row,
)
from sase.core.agent_group_archive_wire import (
    SavedAgentGroupPageWire,
    SavedAgentGroupRefWire,
    SavedAgentGroupSummaryWire,
    SavedAgentGroupWire,
)


class _TestApp(App[SavedAgentGroupRevivalResult | None]):
    pass


def test_initial_page_includes_load_more_before_custom_search() -> None:
    page = SavedAgentGroupPageWire(
        groups=tuple(_summary(idx) for idx in range(20)),
        next_cursor=20,
    )
    modal = SavedAgentGroupRevivalModal(page)

    option_ids = [option.id for option in modal._create_options()]

    assert option_ids[:5] == [
        "heading:recent",
        "empty:recent",
        "heading:saved",
        "group:group-00",
        "group:group-01",
    ]
    assert option_ids[-2:] == ["load-more", "custom-search"]
    assert len(option_ids) == 25


def test_empty_state_still_keeps_custom_search_final() -> None:
    modal = SavedAgentGroupRevivalModal(
        SavedAgentGroupPageWire(groups=(), next_cursor=None)
    )

    option_ids = [option.id for option in modal._create_options()]

    assert option_ids == [
        "heading:recent",
        "empty:recent",
        "heading:saved",
        "empty:saved",
        "custom-search",
    ]
    assert "0 recent | 0 saved loaded" in modal._hints_text()


async def test_load_more_appends_next_page_and_keeps_custom_final() -> None:
    def load_page(cursor: int | None) -> SavedAgentGroupPageWire:
        assert cursor == 20
        return SavedAgentGroupPageWire(groups=(_summary(20),), next_cursor=None)

    modal = SavedAgentGroupRevivalModal(
        SavedAgentGroupPageWire(
            groups=tuple(_summary(idx) for idx in range(20)),
            next_cursor=20,
        ),
        page_loader=load_page,
    )

    async with _TestApp().run_test() as pilot:
        pilot.app.push_screen(modal)
        await pilot.pause()

        modal.action_load_more()
        await pilot.pause()

        option_list = modal.query_one("#saved-agent-group-list", OptionList)
        option_ids = [option.id for option in option_list.options]
        assert len(modal.groups) == 21
        assert option_ids[-2:] == ["group:group-20", "custom-search"]
        assert modal.next_cursor is None


async def test_preview_loads_full_group_details_for_highlighted_group() -> None:
    group = _group("group-00")
    modal = SavedAgentGroupRevivalModal(
        SavedAgentGroupPageWire(groups=(_summary(0),), next_cursor=None),
        group_loader=lambda group_id: group if group_id == "group-00" else None,
    )

    async with _TestApp().run_test() as pilot:
        pilot.app.push_screen(modal)
        await pilot.pause()

        preview = modal.query_one("#saved-agent-group-preview", Static)
        plain = _static_plain(preview)
        assert "Included agents" in plain
        assert "worker-one" in plain


async def test_enter_on_custom_search_returns_custom_result() -> None:
    result: SavedAgentGroupRevivalResult | None = None
    modal = SavedAgentGroupRevivalModal(
        SavedAgentGroupPageWire(groups=(), next_cursor=None)
    )

    def on_dismiss(value: SavedAgentGroupRevivalResult | None) -> None:
        nonlocal result
        result = value

    async with _TestApp().run_test() as pilot:
        pilot.app.push_screen(modal, callback=on_dismiss)
        await pilot.pause()
        option_list = modal.query_one("#saved-agent-group-list", OptionList)
        option_list.highlighted = 4
        await pilot.press("enter")
        await pilot.pause()

    assert result == SavedAgentGroupRevivalResult(action="custom_search")


async def test_enter_on_recent_group_returns_recent_location() -> None:
    result: SavedAgentGroupRevivalResult | None = None
    modal = SavedAgentGroupRevivalModal(
        SavedAgentGroupPageWire(groups=(), next_cursor=None),
        recent_page=SavedAgentGroupPageWire(
            groups=(_recent_summary(),), next_cursor=None
        ),
    )

    def on_dismiss(value: SavedAgentGroupRevivalResult | None) -> None:
        nonlocal result
        result = value

    async with _TestApp().run_test() as pilot:
        pilot.app.push_screen(modal, callback=on_dismiss)
        await pilot.pause()
        option_list = modal.query_one("#saved-agent-group-list", OptionList)
        option_list.highlighted = 1
        await pilot.press("enter")
        await pilot.pause()

    assert result == SavedAgentGroupRevivalResult(
        action="revive_group",
        group_id="recent-00",
        location="recent",
    )


def test_preview_rendering_includes_stable_time_and_status_text() -> None:
    text = build_saved_group_preview(
        _summary(0),
        _group("group-00"),
    ).plain

    assert "3 agents from backend" in text
    assert "done:2" in text
    assert "failed:1" in text
    assert "worker-one" in text
    assert "codex/gpt-5" in text


def test_named_preview_uses_name_with_generated_summary_context() -> None:
    text = build_saved_group_preview(
        _summary(0, name="Backend batch"),
        _group("group-00"),
    ).plain

    assert "Backend batch" in text
    assert "3 agents from backend" in text


def test_row_rendering_includes_compact_saved_time() -> None:
    text = format_saved_group_row(
        _summary(0),
        0,
        now=datetime(2026, 5, 27, 13, 30, tzinfo=UTC),
    ).plain

    assert "1h | 05-27 12:00" in text
    assert "3 agents" in text


def test_named_row_uses_name_with_generated_summary_context() -> None:
    text = format_saved_group_row(
        _summary(0, name="Backend batch"),
        0,
        now=datetime(2026, 5, 27, 13, 30, tzinfo=UTC),
    ).plain

    assert "Backend batch" in text
    assert "3 agents from backend" in text


def test_saved_group_time_label_is_deterministic_with_supplied_now() -> None:
    label = _saved_group_time_label(
        "2026-05-27T12:00:00Z",
        now=datetime(2026, 5, 27, 13, 30, tzinfo=UTC),
    )

    assert label == "1h ago | 2026-05-27 12:00"


def _summary(idx: int, *, name: str | None = None) -> SavedAgentGroupSummaryWire:
    return SavedAgentGroupSummaryWire(
        group_id=f"group-{idx:02}",
        created_at=f"2026-05-27T12:{idx % 60:02}:00Z",
        source="marked_agents",
        title="3 agents from backend",
        name=name,
        agent_count=3,
        top_level_agent_count=2,
        status_counts={"DONE": 2, "FAILED": 1},
        project_names=("sase",),
        cl_names=("backend",),
    )


def _recent_summary() -> SavedAgentGroupSummaryWire:
    return SavedAgentGroupSummaryWire(
        group_id="recent-00",
        created_at="2026-05-27T12:10:00Z",
        source="recent_dismissal",
        title="1 agent in backend",
        agent_count=1,
        top_level_agent_count=1,
        status_counts={"DONE": 1},
        project_names=("sase",),
        cl_names=("backend",),
    )


def _group(group_id: str) -> SavedAgentGroupWire:
    return SavedAgentGroupWire(
        group_id=group_id,
        created_at="2026-05-27T12:00:00Z",
        source="marked_agents",
        title="3 agents from backend",
        agent_count=3,
        top_level_agent_count=2,
        status_counts={"DONE": 2, "FAILED": 1},
        project_names=("sase",),
        cl_names=("backend",),
        agent_refs=(
            SavedAgentGroupRefWire(
                agent_type="run",
                cl_name="backend",
                raw_suffix="20260527120000",
                display_name="worker-one",
                agent_name="backend.1",
                status="DONE",
                model="gpt-5",
                llm_provider="codex",
            ),
        ),
    )


def _static_plain(static: Static) -> str:
    renderable = static.content
    plain = getattr(renderable, "plain", None)
    if isinstance(plain, str):
        return plain
    return str(renderable)
