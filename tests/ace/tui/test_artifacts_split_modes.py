"""Artifacts split-mode helpers and application integration."""

from __future__ import annotations

from rich.text import Text

from sase.ace.testing import AcePage
from sase.ace.tui._app_layout import MAX_LIST_WIDTH, MIN_LIST_WIDTH
from sase.ace.tui.artifact_tabs import ARTIFACTS_ACCENTS
from sase.ace.tui.artifacts_split import (
    ARTIFACTS_SPLIT_BADGE_CELLS,
    ARTIFACTS_SPLIT_BADGE_FILLED,
    ARTIFACTS_SPLIT_CLASSES,
    ARTIFACTS_SPLIT_MODE_ORDER,
    artifacts_split_left_cap,
    build_artifacts_split_badge,
    cycle_artifacts_split_mode,
    normalize_artifacts_split_mode,
)
from sase.ace.tui.widgets.artifacts.split_badge import ArtifactsSplitBadge
from sase.ace.tui.widgets.artifacts.view import ArtifactsView
from sase.ace.tui.widgets.patch_list import PatchList


def test_cycle_artifacts_split_mode_wraps_in_both_directions() -> None:
    for index, mode in enumerate(ARTIFACTS_SPLIT_MODE_ORDER):
        assert (
            cycle_artifacts_split_mode(mode, 1)
            == ARTIFACTS_SPLIT_MODE_ORDER[(index + 1) % len(ARTIFACTS_SPLIT_MODE_ORDER)]
        )
        assert (
            cycle_artifacts_split_mode(mode, -1)
            == ARTIFACTS_SPLIT_MODE_ORDER[(index - 1) % len(ARTIFACTS_SPLIT_MODE_ORDER)]
        )


def test_normalize_artifacts_split_mode_falls_back_to_even() -> None:
    for value in (None, "unknown", 1, True, object()):
        assert normalize_artifacts_split_mode(value) == "even"


def test_artifacts_split_left_cap_uses_fraction_and_floors() -> None:
    assert (
        artifacts_split_left_cap(
            "even", 0, minimum=MIN_LIST_WIDTH, maximum=MAX_LIST_WIDTH
        )
        == MAX_LIST_WIDTH
    )
    assert [
        artifacts_split_left_cap(
            mode,
            120,
            minimum=MIN_LIST_WIDTH,
            maximum=MAX_LIST_WIDTH,
        )
        for mode in ARTIFACTS_SPLIT_MODE_ORDER
    ] == [43, 60, 80]
    assert (
        artifacts_split_left_cap(
            "narrow",
            80,
            minimum=MIN_LIST_WIDTH,
            maximum=MAX_LIST_WIDTH,
        )
        == MIN_LIST_WIDTH
    )


def test_build_artifacts_split_badge_styles_filled_prefix() -> None:
    accent = "#12ABEF"
    for mode in ARTIFACTS_SPLIT_MODE_ORDER:
        badge = build_artifacts_split_badge(mode, accent)
        filled = ARTIFACTS_SPLIT_BADGE_FILLED[mode]
        assert badge.plain == "{" + "█" * ARTIFACTS_SPLIT_BADGE_CELLS + "}"
        accent_spans = [span for span in badge.spans if str(span.style) == accent]
        assert len(accent_spans) == 1
        assert accent_spans[0].start == 1
        assert accent_spans[0].end == 1 + filled


def _active_split_classes(view: ArtifactsView) -> set[str]:
    return {
        class_name
        for class_name in ARTIFACTS_SPLIT_CLASSES.values()
        if view.has_class(class_name)
    }


def _badge_text(badge: ArtifactsSplitBadge) -> Text:
    content = badge.content
    assert isinstance(content, Text)
    return content


async def test_split_keys_share_mode_classes_and_badge_accent() -> None:
    async with AcePage(initial_tab="patches") as page:
        view = page.query_one_widget("#artifacts-view", ArtifactsView)
        badge = page.query_one_widget("#artifacts-split-badge", ArtifactsSplitBadge)

        assert page.app.artifacts_split_mode == "even"
        assert _active_split_classes(view) == {"-split-even"}

        await page.press("}")
        assert page.app.artifacts_split_mode == "wide"
        assert _active_split_classes(view) == {"-split-wide"}

        await page.press("}")
        assert page.app.artifacts_split_mode == "narrow"
        assert _active_split_classes(view) == {"-split-narrow"}

        await page.press("{")
        assert page.app.artifacts_split_mode == "wide"
        assert _active_split_classes(view) == {"-split-wide"}

        await page.press(page.artifacts_digit("beads"))
        await page.expect_state("artifacts_subtab", "beads")
        assert _active_split_classes(view) == {"-split-wide"}
        accent = ARTIFACTS_ACCENTS["beads"]
        text = _badge_text(badge)
        assert any(str(span.style) == accent for span in text.spans)


async def test_split_actions_are_scoped_to_every_artifacts_subtab() -> None:
    async with AcePage(initial_tab="patches") as page:
        actions = (
            "cycle_artifacts_split",
            "cycle_artifacts_split_reverse",
        )
        view = page.query_one_widget("#artifacts-view", ArtifactsView)

        for descriptor in view.descriptors:
            page.app.current_artifacts_subtab = descriptor.id
            await page.pause()
            assert all(page.app.check_action(action, ()) is True for action in actions)

        page.app.current_tab = "agents"
        await page.pause()
        assert all(page.app.check_action(action, ()) is False for action in actions)
        page.app.current_tab = "axe"
        await page.pause()
        assert all(page.app.check_action(action, ()) is False for action in actions)


async def test_patch_list_content_width_obeys_split_cap() -> None:
    async with AcePage(initial_tab="patches", size=(120, 40)) as page:
        list_container = page.query_one_widget("#list-container")
        page.app.on_patch_list_width_changed(PatchList.WidthChanged(80))

        assert list_container.styles.width is not None
        assert list_container.styles.width.value == 60

        page.app.artifacts_split_mode = "wide"
        await page.pause()
        assert list_container.styles.width.value == 80

        page.app.artifacts_split_mode = "narrow"
        await page.pause()
        assert list_container.styles.width.value == MIN_LIST_WIDTH


async def test_clicking_split_badge_cycles_forward() -> None:
    async with AcePage(initial_tab="patches") as page:
        assert page.app.artifacts_split_mode == "even"
        await page.click("#artifacts-split-badge", offset=(1, 0))
        await page.pause()
        assert page.app.artifacts_split_mode == "wide"
