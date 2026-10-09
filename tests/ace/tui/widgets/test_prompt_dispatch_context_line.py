"""Idle prompts hide the dispatch Target/Source context line."""

from __future__ import annotations

import pytest
from textual.widgets import Static

from sase.ace.tui.widgets._prompt_input_bar_dispatch import (
    PromptInputBarDispatchMixin,
)
from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar
from sase.ace.tui.widgets.prompt_text_area import PromptTextArea
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


async def test_history_load_refreshes_dispatch_context_line_and_focus(
    no_catalog_worker: None,
) -> None:
    """A Prompts-overlay LOAD that changes %dispatch refreshes target state.

    Regression for the viewer_matrix ade28c173a recheck: overlay History/Stash
    restores replace pane text through ``load_prompt_into_pane`` (fresh mounts,
    no ``TextArea.Changed``), so without an explicit refresh the Target/Source
    line keeps showing the pre-load directive while the prompt bar already
    carries the new target. The rebuild must also leave the prompt pane
    focused for typing, never the filtered agent list behind the picker.
    """
    app = DispatchPickerFocusApp("#gh:sase")
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        _seed_remote_targets(bar)
        bar._refresh_dispatch_context_line()
        await pilot.pause()

        panel = app.query_one("#prompt-dispatch-context", Static)
        assert panel.has_class("hidden")

        assert (
            bar.load_prompt_into_pane(
                bar.active_text_area(), "", "%dispatch:apollo\n#gh:sase"
            )
            is True
        )
        await pilot.pause()
        await pilot.pause()

        panel = app.query_one("#prompt-dispatch-context", Static)
        assert not panel.has_class("hidden")
        assert bar._dispatch_context_visible is True
        rendered = renderable_to_text(panel.render())
        assert rendered is not None
        assert "apollo" in rendered
        assert "Source" in rendered
        assert app.query_one(PromptTextArea).has_focus


async def test_history_load_hides_dispatch_context_line_without_directive(
    no_catalog_worker: None,
) -> None:
    """Loading a plain entry clears a previously shown dispatch target."""
    app = DispatchPickerFocusApp("%dispatch:apollo\n#gh:sase")
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        _seed_remote_targets(bar)
        bar._refresh_dispatch_context_line()
        await pilot.pause()

        panel = app.query_one("#prompt-dispatch-context", Static)
        assert not panel.has_class("hidden")

        assert bar.load_prompt_into_pane(bar.active_text_area(), "", "#gh:sase") is True
        await pilot.pause()
        await pilot.pause()

        panel = app.query_one("#prompt-dispatch-context", Static)
        assert panel.has_class("hidden")
        assert bar._dispatch_context_visible is False
        assert app.query_one(PromptTextArea).has_focus


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


async def test_invalid_auto_spelling_shows_error_without_dispatch(
    no_catalog_worker: None,
) -> None:
    app = DispatchPickerFocusApp("%auto(plan=ask)\n#gh:sase")
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
        assert "Auto error" in rendered
        assert "parenthesized arguments are not supported yet" in rendered


async def test_invalid_auto_spelling_shows_launch_message_with_dispatch(
    no_catalog_worker: None,
) -> None:
    prompt = "%dispatch:apollo\n%auto:foo\n#gh:sase"

    app = DispatchPickerFocusApp(prompt)
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        _seed_remote_targets(bar)
        bar._refresh_dispatch_context_line()
        await pilot.pause()

        panel = app.query_one("#prompt-dispatch-context", Static)
        assert not panel.has_class("hidden")
        assert panel.has_class("error")
        rendered = renderable_to_text(panel.render())
        assert rendered is not None
        assert "Target" in rendered
        assert "apollo" in rendered
        assert "Auto error" in rendered
        # The panel wraps the long line; the unit parity test asserts the
        # full message text matches the launch path exactly.
        assert "Invalid %auto spelling '%auto:foo'" in rendered
        assert "unknown auto mode 'foo'" in rendered


async def test_dispatch_with_invalid_auto_shows_message_once(
    no_catalog_worker: None,
) -> None:
    from sase.macro._directive_scan import scan_auto_directive

    prompt = "%dispatch:apollo\n%auto:foo\n#gh:sase"
    app = DispatchPickerFocusApp(prompt)
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        _seed_remote_targets(bar)
        scan = scan_auto_directive(prompt)
        assert scan is not None and scan.error is not None
        bar._dispatch_preflight_override = (scan.error, "error", prompt)
        text, severity, _ = bar._dispatch_context_text(prompt)
        rendered = renderable_to_text(text)
        assert rendered is not None
        assert severity == "error"
        assert rendered.count("Invalid %auto spelling") == 1


@pytest.mark.parametrize("prompt", ["%auto:tale\n#gh:sase", "%auto:off\n#gh:sase"])
async def test_valid_and_manual_auto_spellings_show_nothing(
    no_catalog_worker: None,
    prompt: str,
) -> None:
    app = DispatchPickerFocusApp(prompt)
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        _seed_remote_targets(bar)
        bar._refresh_dispatch_context_line()
        await pilot.pause()

        panel = app.query_one("#prompt-dispatch-context", Static)
        assert panel.has_class("hidden")
        assert bar._dispatch_context_visible is False


async def test_invalid_auto_spelling_blocks_submit(
    no_catalog_worker: None,
) -> None:
    from types import SimpleNamespace

    prompt = "%auto(plan=ask)\n#gh:sase"
    app = DispatchPickerFocusApp(prompt)
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        _seed_remote_targets(bar)

        prepared = SimpleNamespace(value=prompt, panes=())
        assert bar._maybe_preflight_dispatch_submission(prepared) is True

        override = bar._dispatch_preflight_override
        assert override is not None
        assert override[1] == "error"
        assert "parenthesized arguments are not supported yet" in override[0]
        assert app.query_one(PromptTextArea).has_focus

        valid = SimpleNamespace(value="%auto:tale\n#gh:sase", panes=())
        assert bar._maybe_preflight_dispatch_submission(valid) is False
