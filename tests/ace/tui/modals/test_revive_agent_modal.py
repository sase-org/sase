"""Tests for the legacy dismissed-agent revive modal."""

from __future__ import annotations

import asyncio
import inspect
from pathlib import Path
from threading import Event

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Input, OptionList

from sase.ace.testing import wait_for
import sase.ace.tui.modals.revive_agent_modal as revive_agent_modal
import sase.ace.tui.modals.revive_agent_rendering as revive_agent_rendering
from sase.ace.tui.models.agent import AgentType
from sase.ace.tui.models.agent_status import (
    STOPPED_COLOR,
    STOPPED_GLYPH,
    STOPPED_STATUS,
)
from sase.ace.tui.modals.revive_agent_modal import DismissedAgentSelectModal
from sase.ace.tui.modals.revive_agent_rendering import (
    build_metadata_preview,
    build_response_preview,
    format_agent_label,
    get_status_style,
)

from tests._agent_revive_helpers import make_agent


class _ModalHost(App[None]):
    ENABLE_COMMAND_PALETTE = False

    def __init__(self, modal: DismissedAgentSelectModal) -> None:
        super().__init__()
        self.modal = modal

    def compose(self) -> ComposeResult:
        yield from ()

    def on_mount(self) -> None:
        self.push_screen(self.modal)


def test_revive_modal_mount_handler_is_synchronous() -> None:
    assert not inspect.iscoroutinefunction(DismissedAgentSelectModal.on_mount)


@pytest.mark.asyncio
async def test_revive_modal_opens_while_initial_archive_load_is_blocked() -> None:
    started = Event()
    release = Event()
    loaded = make_agent(cl_name="alpha", raw_suffix="20260512120000")

    def page_loader() -> tuple[list[object], list[object], bool]:
        started.set()
        release.wait()
        return [loaded], [loaded], True

    modal = DismissedAgentSelectModal(
        [],
        loading_archive=True,
        page_loader=page_loader,  # type: ignore[arg-type]
    )

    async with _ModalHost(modal).run_test(size=(100, 30)) as pilot:
        try:
            assert await asyncio.wait_for(
                asyncio.to_thread(started.wait, 10.0), timeout=11.0
            )
            filter_input = modal.query_one("#dismissed-filter", Input)
            assert filter_input.has_focus
            await pilot.press("a")
            assert filter_input.value == "a"
            option_list = modal.query_one("#dismissed-agent-list", OptionList)
            assert (
                "Loading dismissed archive"
                in option_list.get_option_at_index(0).prompt.plain
            )
        finally:
            release.set()
            await wait_for(pilot, lambda: not modal._initial_loading)
            assert not modal._initial_loading


def test_modal_exposes_legacy_filter_placeholder_and_bindings() -> None:
    modal = DismissedAgentSelectModal(
        [make_agent(cl_name="alpha", raw_suffix="20260512120000")],
    )

    binding_actions = {
        binding.action if hasattr(binding, "action") else binding[1]
        for binding in modal.BINDINGS
    }

    assert "load_more" in binding_actions
    assert "toggle_mark" in binding_actions
    assert "toggle_all" in binding_actions
    assert "^k" not in modal._hints_text()


def test_filter_matches_agent_label_and_response_content(tmp_path: Path) -> None:
    response_path = tmp_path / "response.md"
    response_path.write_text("Needle appears in the transcript.", encoding="utf-8")
    agent = make_agent(
        cl_name="alpha",
        raw_suffix="20260512120000",
        agent_name="named",
        response_path=str(response_path),
    )
    modal = DismissedAgentSelectModal([agent])
    modal._chat_contents[0] = response_path.read_text(encoding="utf-8").lower()

    assert modal._get_filtered_agents("named") == [(0, agent)]
    assert modal._get_filtered_agents("needle") == [(0, agent)]
    assert modal._get_filtered_agents("missing") == []


def test_filter_discriminates_shared_patch_by_project_identity() -> None:
    widgets = make_agent(
        cl_name="shared-pr",
        raw_suffix="20260512120000",
        project_file="/tmp/projects/gh_acme__widgets/gh_acme__widgets.sase",
        project_display_name="widgets",
    )
    gadgets = make_agent(
        cl_name="shared-pr",
        raw_suffix="20260512120100",
        project_file="/tmp/projects/gh_acme__gadgets/gh_acme__gadgets.sase",
        project_display_name="gadgets",
    )
    modal = DismissedAgentSelectModal([widgets, gadgets])

    assert modal._get_filtered_agents("gh_acme__widgets") == [(0, widgets)]
    assert modal._get_filtered_agents("widgets") == [(0, widgets)]
    assert modal._get_filtered_agents("gh_acme__gadgets") == [(1, gadgets)]
    assert modal._get_filtered_agents("gadgets") == [(1, gadgets)]


def test_project_agent_label_metadata_response_and_filter_are_humanized(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response_path = tmp_path / "response.md"
    response_path.write_text(
        "Recorded prompt: #gh:gh_acme__widgets fix it.",
        encoding="utf-8",
    )
    agent = make_agent(
        agent_type=AgentType.RUNNING,
        cl_name="gh_acme__widgets",
        workflow=None,
        project_file="/tmp/projects/gh_acme__widgets/gh_acme__widgets.sase",
        project_display_name="widgets",
        response_path=str(response_path),
    )
    monkeypatch.setattr(
        revive_agent_rendering,
        "humanize_vcs_refs_in_text",
        lambda text: text.replace("gh_acme__widgets", "widgets"),
    )
    monkeypatch.setattr(
        revive_agent_modal,
        "humanize_vcs_refs_in_text",
        lambda text: text.replace("gh_acme__widgets", "widgets"),
    )

    label = format_agent_label(agent)
    metadata = build_metadata_preview(agent, [])
    response = build_response_preview(agent)
    modal = DismissedAgentSelectModal([agent])
    modal._chat_contents[0] = revive_agent_modal._response_filter_corpus(
        response_path.read_text(encoding="utf-8")
    )

    assert "widgets" in label.plain
    assert "gh_acme__widgets" not in label.plain
    assert "[agent] widgets" in metadata.plain
    assert "#gh:widgets fix it." in response.plain
    assert "#gh:gh_acme__widgets" not in response.plain
    assert modal._get_filtered_agents("widgets") == [(0, agent)]
    assert modal._get_filtered_agents("gh_acme__widgets") == [(0, agent)]


def test_marked_agents_return_original_order() -> None:
    first = make_agent(cl_name="alpha", raw_suffix="20260512120000")
    second = make_agent(cl_name="beta", raw_suffix="20260512120100")
    third = make_agent(cl_name="gamma", raw_suffix="20260512120200")
    modal = DismissedAgentSelectModal([first, second, third])
    modal._marked = {2, 0}

    assert modal._get_marked_agents() == [first, third]


def test_set_agents_recomputes_workflow_step_counts() -> None:
    parent = make_agent(cl_name="parent", raw_suffix="20260512120000")
    child = make_agent(
        cl_name="child",
        raw_suffix="20260512120100",
        parent_timestamp="20260512120000",
        step_index=1,
        step_type="agent",
    )
    modal = DismissedAgentSelectModal([])

    modal.agents = [parent]
    modal._all_dismissed = [parent, child]
    modal._step_counts = modal._compute_step_counts()

    assert modal._step_counts == {"20260512120000": 1}


def test_set_agents_preserves_marks_by_identity_after_reorder() -> None:
    first = make_agent(cl_name="alpha", raw_suffix="20260512120000")
    second = make_agent(cl_name="beta", raw_suffix="20260512120100")
    modal = DismissedAgentSelectModal([first, second])
    modal._marked = {1}

    modal.set_agents([second, first])

    assert modal._marked == {0}
    assert modal._get_marked_agents() == [second]


@pytest.mark.asyncio
async def test_ctrl_k_loads_more_without_clearing_filter_or_marks() -> None:
    first = make_agent(cl_name="alpha", raw_suffix="20260512120000")
    second = make_agent(cl_name="beta", raw_suffix="20260512120100")
    pages = [
        ([first], [first], False),
        ([first, second], [first, second], True),
    ]

    def page_loader() -> tuple[list[object], list[object], bool]:
        return pages.pop(0)  # type: ignore[return-value]

    modal = DismissedAgentSelectModal(
        [],
        loading_archive=True,
        page_loader=page_loader,  # type: ignore[arg-type]
        page_size=250,
    )
    app = _ModalHost(modal)

    async with app.run_test(size=(100, 30)) as pilot:
        # Both page loads run in a worker over `asyncio.to_thread`, so they
        # race the message pump and have to be waited on by their end state.
        await wait_for(pilot, lambda: modal.agents == [first])
        filter_input = modal.query_one("#dismissed-filter", Input)
        option_list = modal.query_one("#dismissed-agent-list", OptionList)
        filter_input.value = "a"
        modal._marked = {0}
        option_list.highlighted = 0

        await pilot.press("ctrl+k")
        await wait_for(pilot, lambda: modal.agents == [first, second])

        assert option_list.highlighted == 0

    assert filter_input.value == "a"
    assert modal.agents == [first, second]
    assert modal._marked == {0}
    assert pages == []
    assert "^k" not in modal._hints_text()


@pytest.mark.asyncio
async def test_initial_page_renders_loaded_rows_without_typing() -> None:
    loaded = make_agent(cl_name="alpha", raw_suffix="20260512120000")
    pages = [([loaded], [loaded], True)]

    def page_loader() -> tuple[list[object], list[object], bool]:
        return pages.pop(0)  # type: ignore[return-value]

    modal = DismissedAgentSelectModal(
        [],
        loading_archive=True,
        page_loader=page_loader,  # type: ignore[arg-type]
        page_size=250,
    )
    app = _ModalHost(modal)

    async with app.run_test(size=(100, 30)) as pilot:
        # Same off-pump page load as above: two bare pauses only happened to
        # outlast the worker's thread hop.
        await wait_for(pilot, lambda: modal.agents == [loaded])

        option_list = modal.query_one("#dismissed-agent-list", OptionList)

        assert modal.agents == [loaded]
        assert option_list.option_count == 1
        option = option_list.get_option_at_index(0)
        assert option.id == "0"
        assert not option.disabled
        assert "Loading dismissed archive" not in option.prompt.plain
        assert "archive loading" not in modal._hints_text()


def test_stopped_status_uses_canonical_style_and_glyph() -> None:
    agent = make_agent(status=STOPPED_STATUS)

    label = format_agent_label(agent)

    assert get_status_style(STOPPED_STATUS) == f"bold {STOPPED_COLOR}"
    assert f"{STOPPED_GLYPH} " in label.plain
    glyph_start = label.plain.index(STOPPED_GLYPH)
    glyph_end = glyph_start + len(STOPPED_GLYPH)
    assert any(
        span.start <= glyph_start
        and span.end >= glyph_end
        and str(span.style) == f"bold {STOPPED_COLOR}"
        for span in label.spans
    )
