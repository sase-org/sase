"""ACE TUI PNG visual snapshots for prompt syntax and annotation highlights."""

from __future__ import annotations

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui import AceApp
from sase.ace.tui.widgets.prompt_text_area import PromptTextArea
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patches,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_state,
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
from tests.ace.tui.visual._ace_prompt_png_snapshot_prompts import (
    ARTIFACT_REF_HIGHLIGHT,
    BULLET_HIGHLIGHT_SOLO,
    CODEBLOCK_HIGHLIGHT_SOLO,
    CODEBLOCK_HIGHLIGHT_STACK,
    GLOSSARY_HIGHLIGHT_PROMPT,
    GLOSSARY_WRAPPED_HIGHLIGHT_PROMPT,
    MISSPELLING_HIGHLIGHT_PROMPT,
    ORDERED_HIGHLIGHT_SOLO,
    REPO_MENTION_HIGHLIGHT_PROMPT,
    SEARCH_PROMPT,
    TODO_HIGHLIGHT_STACK,
    TODO_RESTORED_PROMPT,
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

PLACEHOLDER_RAW_ONLY_PROMPT = (
    "Fill <service> before launch\n"
    "Keep `<literal>` as documentation\n"
    "```text\n"
    "<code> stays literal too\n"
    "```"
)


@pytest.mark.parametrize(
    ("theme", "snapshot_name", "title"),
    [
        (
            "textual-dark",
            "prompt_todo_restored_dark_120x40",
            "ACE restored prompt TODO annotations — dark theme",
        ),
        (
            "textual-light",
            "prompt_todo_restored_light_120x40",
            "ACE restored prompt TODO annotations — light theme",
        ),
    ],
)
async def test_prompt_todo_restored_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    theme: str,
    snapshot_name: str,
    title: str,
) -> None:
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        page.app.theme = theme
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        await page.expect_state("tab", "patches")
        bar = await mount_prompt_bar(page, TODO_RESTORED_PROMPT)

        assert "TODO 4" in str(bar.border_title)
        assert bar.active_text_area().cursor_location[0] == 32
        ace_png_visual.assert_page_png(page, snapshot_name, title=title)


async def test_prompt_todo_stack_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        await page.expect_state("tab", "patches")
        bar = await mount_prompt_bar(page, TODO_HIGHLIGHT_STACK)

        assert "TODO 2" in str(bar.border_title)
        assert bar._stack.selected_index == 1
        assert (
            bar.query_one(".prompt-pane.inactive", PromptTextArea).todo_annotation_count
            == 1
        )
        ace_png_visual.assert_page_png(
            page,
            "prompt_todo_stack_120x40",
            title="ACE prompt TODO annotations — inactive pane count",
        )


@pytest.mark.parametrize(
    ("theme", "snapshot_name", "title"),
    [
        (
            "textual-dark",
            "prompt_bullet_highlight_solo_dark_120x40",
            "ACE prompt input — bullet-dash highlighting, dark theme",
        ),
        (
            "textual-light",
            "prompt_bullet_highlight_solo_light_120x40",
            "ACE prompt input — bullet-dash highlighting, light theme",
        ),
    ],
)
async def test_prompt_bullet_highlight_solo_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    theme: str,
    snapshot_name: str,
    title: str,
) -> None:
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        page.app.theme = theme
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        await page.expect_state("tab", "patches")
        await mount_prompt_bar(page, BULLET_HIGHLIGHT_SOLO)

        ace_png_visual.assert_page_png(page, snapshot_name, title=title)


@pytest.mark.parametrize(
    ("theme", "snapshot_name", "title"),
    [
        (
            "textual-dark",
            "prompt_ordered_highlight_solo_dark_120x40",
            "ACE prompt input — ordered-marker highlighting, dark theme",
        ),
        (
            "textual-light",
            "prompt_ordered_highlight_solo_light_120x40",
            "ACE prompt input — ordered-marker highlighting, light theme",
        ),
    ],
)
async def test_prompt_ordered_highlight_solo_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    theme: str,
    snapshot_name: str,
    title: str,
) -> None:
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        page.app.theme = theme
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        await page.expect_state("tab", "patches")
        await mount_prompt_bar(page, ORDERED_HIGHLIGHT_SOLO)

        ace_png_visual.assert_page_png(page, snapshot_name, title=title)


async def test_prompt_search_highlight_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        await page.expect_state("tab", "patches")
        bar = await mount_prompt_bar(page, SEARCH_PROMPT)

        await page.press("escape", "slash", "a", "l", "p", "h", "a")
        text_area = bar.active_text_area()
        await wait_for_state(
            page,
            lambda: (
                text_area._search_active
                and text_area._search_query == "alpha"
                and bar._search_command_visible
            ),
            description="active alpha prompt search and highlights",
        )
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "prompt_search_highlight_120x40",
            title="ACE prompt input - active search highlight",
        )


async def test_prompt_placeholder_raw_only_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        await page.expect_state("tab", "patches")
        await mount_prompt_bar(page, PLACEHOLDER_RAW_ONLY_PROMPT)

        ace_png_visual.assert_page_png(
            page,
            "placeholder_raw_only_highlight_120x40",
            title="ACE prompt input - raw placeholder highlighting",
        )


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


@pytest.mark.parametrize(
    ("theme", "snapshot_name", "title"),
    [
        (
            "textual-dark",
            "prompt_misspelling_highlight_dark_120x40",
            "ACE prompt input — sticky misspelling highlighting, dark theme",
        ),
        (
            "textual-light",
            "prompt_misspelling_highlight_light_120x40",
            "ACE prompt input — sticky misspelling highlighting, light theme",
        ),
    ],
)
async def test_prompt_misspelling_highlight_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    theme: str,
    snapshot_name: str,
    title: str,
) -> None:
    patch_startup_loaders(monkeypatch)
    # Seed the durable store directly, the same way a prior ``K`` session
    # would have left it, so the app's normal cold-start warm discovers it.
    from sase.history.prompt_misspellings import record_misspelling

    record_misspelling("recieve")
    record_misspelling("reciept")

    async with AcePage(query='"visual"', patches=patches()) as page:
        page.app.theme = theme
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        await page.expect_state("tab", "patches")
        await mount_prompt_bar(page, MISSPELLING_HIGHLIGHT_PROMPT)

        ace_png_visual.assert_page_png(page, snapshot_name, title=title)


@pytest.mark.parametrize(
    ("theme", "snapshot_name", "title"),
    [
        (
            "textual-dark",
            "prompt_codeblock_highlight_solo_dark_120x40",
            "ACE prompt input — code highlighting, dark theme",
        ),
        (
            "textual-light",
            "prompt_codeblock_highlight_solo_light_120x40",
            "ACE prompt input — code highlighting, light theme",
        ),
    ],
)
async def test_prompt_codeblock_highlight_solo_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    theme: str,
    snapshot_name: str,
    title: str,
) -> None:
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        page.app.theme = theme
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        await page.expect_state("tab", "patches")
        await mount_prompt_bar(page, CODEBLOCK_HIGHLIGHT_SOLO)

        ace_png_visual.assert_page_png(page, snapshot_name, title=title)


@pytest.mark.parametrize(
    ("theme", "snapshot_name", "title"),
    [
        (
            "textual-dark",
            "prompt_codeblock_highlight_stack_dark_120x40",
            "ACE prompt stack — code highlighting, dark theme",
        ),
        (
            "textual-light",
            "prompt_codeblock_highlight_stack_light_120x40",
            "ACE prompt stack — code highlighting, light theme",
        ),
    ],
)
async def test_prompt_codeblock_highlight_stack_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    theme: str,
    snapshot_name: str,
    title: str,
) -> None:
    patch_startup_loaders(monkeypatch)

    async with AcePage(
        query='"visual"',
        patches=patches(),
        startup_policy="real",
    ) as page:
        page.app.theme = theme
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        await page.expect_state("tab", "patches")
        await mount_prompt_bar(page, CODEBLOCK_HIGHLIGHT_STACK)

        ace_png_visual.assert_page_png(page, snapshot_name, title=title)
