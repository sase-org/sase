"""Idle prompts hide the dispatch Target/Source context line."""

from __future__ import annotations

import pytest
from textual.widgets import Static

from sase.ace.tui.widgets._prompt_input_bar_dispatch import (
    PromptInputBarDispatchMixin,
)
from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar
from sase.ace.tui.widgets.renderable_text import renderable_to_text
from tests.ace.tui.widgets.test_dispatch_target_picker_focus import (
    DispatchPickerFocusApp,
    _seed_remote_targets,
)


@pytest.fixture
def no_catalog_worker(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        PromptInputBarDispatchMixin,
        "_warm_dispatch_target_catalog",
        lambda self: None,
    )


async def test_idle_prompt_hides_context_line_with_seeded_targets(
    no_catalog_worker: None,
) -> None:
    app = DispatchPickerFocusApp("#gh:sase")
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        _seed_remote_targets(bar)
        bar._refresh_dispatch_context_line()
        await pilot.pause()

        panel = app.query_one("#prompt-dispatch-context", Static)
        assert panel.has_class("hidden")
        assert bar._dispatch_context_visible is False


async def test_idle_prompt_hides_catalog_unavailable_override(
    no_catalog_worker: None,
) -> None:
    app = DispatchPickerFocusApp("#gh:sase")
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        _seed_remote_targets(bar)
        bar._dispatch_preflight_override = (
            "target catalog unavailable: boom",
            "warning",
            "",
        )
        bar._refresh_dispatch_context_line()
        await pilot.pause()

        panel = app.query_one("#prompt-dispatch-context", Static)
        assert panel.has_class("hidden")
        assert bar._dispatch_context_visible is False


async def test_dispatch_selector_shows_context_line(
    no_catalog_worker: None,
) -> None:
    app = DispatchPickerFocusApp("%dispatch:apollo\n#gh:sase")
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        _seed_remote_targets(bar)
        bar._refresh_dispatch_context_line()
        await pilot.pause()

        panel = app.query_one("#prompt-dispatch-context", Static)
        assert not panel.has_class("hidden")
        assert bar._dispatch_context_visible is True
        rendered = renderable_to_text(panel.render())
        assert rendered is not None
        assert "Target" in rendered
        assert "apollo" in rendered
        assert "Source" in rendered


async def test_duplicate_dispatch_selector_shows_error(
    no_catalog_worker: None,
) -> None:
    app = DispatchPickerFocusApp("%dispatch:apollo\n%dispatch:apollo\n#gh:sase")
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        _seed_remote_targets(bar)
        bar._refresh_dispatch_context_line()
        await pilot.pause()

        panel = app.query_one("#prompt-dispatch-context", Static)
        assert not panel.has_class("hidden")
        assert panel.has_class("error")
        assert bar._dispatch_context_visible is True
        rendered = renderable_to_text(panel.render())
        assert rendered is not None
        assert "Target error" in rendered


async def test_dispatch_context_text_reports_hidden_without_directive(
    no_catalog_worker: None,
) -> None:
    app = DispatchPickerFocusApp("#gh:sase")
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        _seed_remote_targets(bar)

        _, _, visible = bar._dispatch_context_text("#gh:sase")
        assert visible is False
