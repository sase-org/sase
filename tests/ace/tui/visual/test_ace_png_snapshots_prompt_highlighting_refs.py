"""sase's TUI PNG visual snapshots for prompt reference highlights."""

from __future__ import annotations

from collections import Counter

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui import AceApp
from sase.ace.tui.widgets.prompt_text_area import PromptTextArea
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patches,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_visual_idle,
)
from tests.ace.tui.visual._ace_prompt_png_snapshot_artifact_ref_fixtures import (
    patch_visual_artifact_ref_kinds,
    seed_visual_artifact_ref_kinds,
)
from tests.ace.tui.visual._ace_prompt_png_snapshot_glossary_fixtures import (
    patch_visual_glossary_catalog,
)
from tests.ace.tui.visual._ace_prompt_png_snapshot_helpers import mount_prompt_bar
from tests.ace.tui.visual._ace_prompt_png_snapshot_project_tag_fixtures import (
    patch_visual_project_tag_catalog,
)
from tests.ace.tui.visual._ace_prompt_png_snapshot_prompts import (
    ARTIFACT_REF_HIGHLIGHT,
    GLOSSARY_HIGHLIGHT_PROMPT,
    GLOSSARY_WRAPPED_HIGHLIGHT_PROMPT,
    PROJECT_TAG_HIGHLIGHT_SOLO,
    REPO_MENTION_HIGHLIGHT_PROMPT,
    XPROMPT_ARGUMENT_HIGHLIGHT,
    XPROMPT_HIGHLIGHT_SOLO,
    XPROMPT_HIGHLIGHT_STACK,
)
from tests.ace.tui.visual._ace_prompt_png_snapshot_repo_mention_fixtures import (
    patch_visual_repo_mention_catalog,
)
from tests.ace.tui.visual._ace_prompt_png_snapshot_xprompt_fixtures import (
    patch_visual_skill_catalog,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


async def test_prompt_xprompt_highlight_solo_light_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    patch_visual_skill_catalog(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        page.app.theme = "textual-light"
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        await page.expect_state("tab", "patches")
        await mount_prompt_bar(page, XPROMPT_HIGHLIGHT_SOLO)

        ace_png_visual.assert_page_png(
            page,
            "prompt_xprompt_highlight_solo_light_120x40",
            title="ACE prompt input — xprompt highlighting, light theme",
        )


async def test_prompt_xprompt_highlight_stack_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    patch_visual_skill_catalog(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        await page.expect_state("tab", "patches")
        await mount_prompt_bar(page, XPROMPT_HIGHLIGHT_STACK)

        ace_png_visual.assert_page_png(
            page,
            "prompt_xprompt_highlight_stack_120x40",
            title="ACE prompt stack — xprompt highlighting",
        )


@pytest.mark.parametrize(
    ("theme", "snapshot_name", "title"),
    [
        (
            "textual-dark",
            "prompt_project_tag_highlight_dark_120x40",
            "ACE prompt input — project tag highlighting, dark theme",
        ),
        (
            "textual-light",
            "prompt_project_tag_highlight_light_120x40",
            "ACE prompt input — project tag highlighting, light theme",
        ),
    ],
)
async def test_prompt_project_tag_highlight_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    theme: str,
    snapshot_name: str,
    title: str,
) -> None:
    patch_startup_loaders(monkeypatch)
    patch_visual_skill_catalog(monkeypatch)
    patch_visual_project_tag_catalog(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        page.app.theme = theme
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        await page.expect_state("tab", "patches")
        bar = await mount_prompt_bar(page, PROJECT_TAG_HIGHLIGHT_SOLO)
        text_area = bar.active_text_area()
        await wait_for_visual_idle(page)

        names = [
            name for row in text_area._highlights.values() for *_range, name in row
        ]
        counts = Counter(names)
        accent_sigils = [
            name
            for name in names
            if name.startswith("project_tag.sigil.")
            and name != "project_tag.sigil.neutral"
        ]
        accent_names = [
            name
            for name in names
            if name.startswith("project_tag.name.")
            and name != "project_tag.name.neutral"
        ]
        assert len(accent_sigils) == 1, names  # +sase keeps its accent
        assert len(accent_names) == 1, names
        assert counts["project_tag.sigil.neutral"] == 2, names  # +home, +oldproj
        assert counts["project_tag.name.neutral"] == 2, names
        assert counts["project_tag.unknown"] == 1, names  # +no-such-project
        ace_png_visual.assert_page_png(page, snapshot_name, title=title)


@pytest.mark.parametrize(
    ("theme", "snapshot_name", "title"),
    [
        (
            "textual-dark",
            "prompt_xprompt_argument_highlight_dark_120x40",
            "ACE prompt input - xprompt argument highlighting, dark theme",
        ),
        (
            "textual-light",
            "prompt_xprompt_argument_highlight_light_120x40",
            "ACE prompt input - xprompt argument highlighting, light theme",
        ),
    ],
)
async def test_prompt_xprompt_argument_highlight_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    theme: str,
    snapshot_name: str,
    title: str,
) -> None:
    patch_startup_loaders(monkeypatch)
    patch_visual_skill_catalog(monkeypatch)
    patch_visual_artifact_ref_kinds(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        page.app.theme = theme
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        await page.expect_state("tab", "patches")
        bar = await mount_prompt_bar(page, XPROMPT_ARGUMENT_HIGHLIGHT)
        text_area = bar.active_text_area()
        seed_visual_artifact_ref_kinds(text_area)
        await wait_for_visual_idle(page)

        names = [
            name for row in text_area._highlights.values() for *_range, name in row
        ]
        for name in (
            "xprompt.arg_delimiter",
            "xprompt.arg_key",
            "xprompt.arg_key.invalid",
            "xprompt.arg_assign",
            "xprompt.arg_value",
            "xprompt.arg_value_string",
            "xprompt.arg_value_number",
            "xprompt.arg_value_bool",
            "xprompt.directive.arg_delimiter",
            "xprompt.directive.arg_key",
            "xprompt.directive.arg_key.invalid",
            "xprompt.directive.arg_assign",
            "xprompt.directive.arg_value",
            "artifact_ref.payload",
            "jinja.delimiter",
            "jinja.variable",
        ):
            assert name in names
        ace_png_visual.assert_page_png(page, snapshot_name, title=title)


async def test_prompt_artifact_ref_highlight_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    patch_visual_artifact_ref_kinds(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        await page.expect_state("tab", "patches")
        bar = await mount_prompt_bar(page, ARTIFACT_REF_HIGHLIGHT)
        seed_visual_artifact_ref_kinds(bar.active_text_area())
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "prompt_artifact_ref_highlight_120x40",
            title="ACE prompt input — artifact-reference highlighting",
        )


@pytest.mark.parametrize(
    ("theme", "snapshot_name", "title"),
    [
        (
            "textual-dark",
            "prompt_glossary_highlight_dark_120x40",
            "ACE prompt input — glossary highlighting, dark theme",
        ),
        (
            "textual-light",
            "prompt_glossary_highlight_light_120x40",
            "ACE prompt input — glossary highlighting, light theme",
        ),
    ],
)
async def test_prompt_glossary_highlight_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    theme: str,
    snapshot_name: str,
    title: str,
) -> None:
    patch_startup_loaders(monkeypatch)
    patch_visual_glossary_catalog(monkeypatch)
    # This pair of goldens pins glossary styling with artifact-like text kept
    # in the cold, neutral state. The wrapped glossary snapshot below covers
    # the known-artifact-ref overlay on the same prompt surface.
    monkeypatch.setattr(
        PromptTextArea,
        "_warm_current_artifact_ref_completion_catalog",
        lambda _self: None,
    )

    async with AcePage(query='"visual"', patches=patches()) as page:
        page.app.theme = theme
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        await page.expect_state("tab", "patches")
        bar = await mount_prompt_bar(page, GLOSSARY_HIGHLIGHT_PROMPT)
        text_area = bar.active_text_area()
        text_area._refresh_prompt_glossary_context(schedule=False)
        text_area._build_highlight_map()
        await wait_for_visual_idle(page)

        assert any(
            name == "glossary.term"
            for row in text_area._highlights.values()
            for *_range, name in row
        )
        ace_png_visual.assert_page_png(page, snapshot_name, title=title)


async def test_prompt_glossary_wrapped_highlight_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    monkeypatch.setattr(
        AceApp,
        "warm_prompt_catalog_project",
        lambda _app, _project: None,
    )
    patch_visual_glossary_catalog(monkeypatch)
    patch_visual_artifact_ref_kinds(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        page.app.theme = "textual-dark"
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        await page.expect_state("tab", "patches")
        bar = await mount_prompt_bar(page, GLOSSARY_WRAPPED_HIGHLIGHT_PROMPT)
        text_area = bar.active_text_area()
        text_area._refresh_prompt_glossary_context(schedule=False)
        text_area._build_highlight_map()
        await wait_for_visual_idle(page)

        highlights = [
            (row, start, end, name)
            for row, spans in text_area._highlights.items()
            for start, end, name in spans
            if name == "glossary.term"
        ]
        assert (0, 8, 13, "glossary.term") in highlights
        assert (1, 2, 6, "glossary.term") in highlights
        ace_png_visual.assert_page_png(
            page,
            "prompt_glossary_wrapped_highlight_dark_120x40",
            title="ACE prompt input — wrapped glossary highlighting, dark theme",
        )


async def test_prompt_repo_mention_highlight_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    patch_visual_glossary_catalog(monkeypatch)
    patch_visual_repo_mention_catalog(monkeypatch)
    monkeypatch.setattr(
        PromptTextArea,
        "_warm_current_artifact_ref_completion_catalog",
        lambda _self: None,
    )

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        await page.expect_state("tab", "patches")
        bar = await mount_prompt_bar(page, REPO_MENTION_HIGHLIGHT_PROMPT)
        text_area = bar.active_text_area()
        text_area._refresh_prompt_glossary_context(schedule=False)
        text_area._refresh_prompt_repo_mention_context(schedule=False)
        text_area._build_highlight_map()
        await wait_for_visual_idle(page)

        names = [
            name for row in text_area._highlights.values() for *_range, name in row
        ]
        assert "glossary.term" in names
        assert "repo.mention" in names
        glossary = text_area._theme.syntax_styles["glossary.term"]
        repo = text_area._theme.syntax_styles["repo.mention"]
        assert glossary.color != repo.color
        ace_png_visual.assert_page_png(
            page,
            "prompt_repo_mention_highlight_120x40",
            title="ACE prompt input — repo mention vs glossary highlighting",
        )
