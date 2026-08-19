"""Table-driven coverage for the ``@<kind>::`` ref-sync gesture trigger."""

from __future__ import annotations

import pytest

from sase.feature_flags import override_flags
from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar
from sase.ace.tui.widgets.prompt_text_area import PromptTextArea

from ._artifact_ref_completion_helpers import CATALOG, seed_catalog
from ._completion_helpers import CompletionTestApp


def _place_cursor(text_area: PromptTextArea, text: str, marker: str = "|") -> None:
    """Load *text* (with a ``|`` cursor marker) and position the cursor there."""
    offset = text.index(marker)
    clean = text.replace(marker, "", 1)
    text_area.load_text(clean)
    row = clean[:offset].count("\n")
    line_start = clean.rfind("\n", 0, offset) + 1
    text_area.cursor_location = (row, offset - line_start)


@pytest.mark.parametrize(
    ("text", "expected_kind"),
    (
        ("@plans:|", "plans"),
        ("@designs:|", "designs"),
        ("see @plans:|", "plans"),
        ("intro\n@plans:|", "plans"),
    ),
)
async def test_trigger_fires_for_empty_payload_at_known_kind(
    text: str,
    expected_kind: str,
) -> None:
    app = CompletionTestApp()
    async with app.run_test():
        text_area = app.query_one(PromptTextArea)
        seed_catalog(text_area, CATALOG)
        _place_cursor(text_area, text)

        assert text_area._artifact_ref_sync_trigger() == expected_kind


@pytest.mark.parametrize(
    "text",
    (
        "@plans:f|oo",
        "@plans:|foo",
        "@file:default:|",
        "`@plans:|`",
        "```\n@plans:|\n```",
        "@nosuch:|",
    ),
)
async def test_trigger_declines_for_non_empty_payload_or_unknown_context(
    text: str,
) -> None:
    app = CompletionTestApp()
    async with app.run_test():
        text_area = app.query_one(PromptTextArea)
        seed_catalog(text_area, CATALOG)
        _place_cursor(text_area, text)

        assert text_area._artifact_ref_sync_trigger() is None


async def test_trigger_declines_in_normal_mode() -> None:
    app = CompletionTestApp()
    async with app.run_test():
        text_area = app.query_one(PromptTextArea)
        seed_catalog(text_area, CATALOG)
        _place_cursor(text_area, "@plans:|")
        text_area._vim_mode = "normal"

        assert text_area._artifact_ref_sync_trigger() is None


async def test_trigger_declines_in_visual_mode() -> None:
    app = CompletionTestApp()
    async with app.run_test():
        text_area = app.query_one(PromptTextArea)
        seed_catalog(text_area, CATALOG)
        _place_cursor(text_area, "@plans:|")
        text_area._vim_mode = "visual"

        assert text_area._artifact_ref_sync_trigger() is None


async def test_trigger_declines_in_feedback_mode_bar() -> None:
    app = CompletionTestApp()
    async with app.run_test():
        text_area = app.query_one(PromptTextArea)
        bar = app.query_one(PromptInputBar)
        seed_catalog(text_area, CATALOG)
        _place_cursor(text_area, "@plans:|")
        bar._mode = "feedback"

        assert text_area._artifact_ref_sync_trigger() is None


async def test_trigger_declines_with_cold_known_kind_set() -> None:
    app = CompletionTestApp()
    async with app.run_test():
        text_area = app.query_one(PromptTextArea)
        _place_cursor(text_area, "@plans:|")

        assert text_area._artifact_ref_sync_trigger() is None


async def test_trigger_declines_when_flag_disabled() -> None:
    app = CompletionTestApp()
    async with app.run_test():
        text_area = app.query_one(PromptTextArea)
        seed_catalog(text_area, CATALOG)
        _place_cursor(text_area, "@plans:|")

        with override_flags(ref_sync_gesture=False):
            assert text_area._artifact_ref_sync_trigger() is None


async def test_trigger_fires_when_flag_enabled_explicitly() -> None:
    app = CompletionTestApp()
    async with app.run_test():
        text_area = app.query_one(PromptTextArea)
        seed_catalog(text_area, CATALOG)
        _place_cursor(text_area, "@plans:|")

        with override_flags(ref_sync_gesture=True):
            assert text_area._artifact_ref_sync_trigger() == "plans"


async def test_second_colon_is_consumed_and_never_enters_the_buffer() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        text_area = app.query_one(PromptTextArea)
        seed_catalog(text_area, CATALOG)
        text_area.load_text("@plans:")
        text_area.cursor_location = (0, len("@plans:"))
        started: list[str] = []
        text_area._start_artifact_ref_sync = started.append  # type: ignore[method-assign]
        before_text = text_area.text

        await pilot.press(":")

        assert started == ["plans"]
        assert text_area.text == before_text
        assert "::" not in text_area.text


async def test_disabled_flag_inserts_the_second_colon_literally_and_submits_nothing() -> (
    None
):
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        text_area = app.query_one(PromptTextArea)
        seed_catalog(text_area, CATALOG)
        text_area.load_text("@plans:")
        text_area.cursor_location = (0, len("@plans:"))
        started: list[str] = []
        text_area._start_artifact_ref_sync = started.append  # type: ignore[method-assign]

        with override_flags(ref_sync_gesture=False):
            await pilot.press(":")

        assert started == []
        assert text_area.text == "@plans::"
