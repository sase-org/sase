"""ACE TUI PNG visual snapshot coverage for the multi-agent prompt stack.

Phase 6 visual polish: pin how ``PromptInputBar`` renders a stacked, multi-agent
prompt in context — the accent-bordered active pane, the dimmer compacted
inactive panes, the quiet ``agent N`` separator rows, and the completion panel
scoped to the active pane. The bar is mounted directly over the ChangeSpecs tab
(``dock: bottom``) so the full ``styles.tcss`` styling applies exactly as it does
at runtime.
"""

from __future__ import annotations

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui import AceApp
from sase.ace.tui.modals.prompt_submit_choice_modal import PromptSubmitChoiceModal
from sase.ace.tui.widgets import StashedPromptsIndicator
from sase.ace.tui.widgets.file_completion import CompletionCandidate
from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar
from sase.ace.tui.widgets.prompt_text_area import PromptTextArea
from sase.ace.tui.widgets.xprompt_arg_assist import XPromptAssistEntry
from sase.xprompt import jinja_inspect
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    changespecs,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_state,
    wait_for_svg_contains,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


_TWO_PANE_PROMPT = (
    "Investigate the failing CI on the beads branch and\n"
    "summarize the smallest reproducible case for the team"
    "\n---\n"
    "Refactor the workspace loader for clarity and harden\n"
    "the missing-checkout failure path so it is easy to scan"
)

# The two upper panes carry more than ``_INACTIVE_PANE_MAX_ROWS`` lines so the
# inactive-pane cap visibly truncates them while the active bottom pane keeps
# its full body — the point of this snapshot.
_COMPACT_PROMPT = (
    "Audit the overflow tag rendering across the table\n"
    "and keep the compact suffix aligned in every lane\n"
    "so nothing shifts when a long project tag wraps\n"
    "and the preview column stays put under pressure\n"
    "with one more line to push past the compact cap\n"
    "and a final line that should be clipped away"
    "\n---\n"
    "Refactor the workspace loader for clarity\n"
    "and make the missing-checkout failure easy to scan\n"
    "during a long debugging session on a slow host\n"
    "with extra context lines for the reviewer\n"
    "and yet another line beyond the compact cap\n"
    "and a trailing line that should be clipped"
    "\n---\n"
    "Draft the release notes for the prompt stack feature\n"
    "and link the before/after screenshots"
)

_JINJA_VALID_PROMPT = (
    "Summarize {{ root | tojson }} for {% if root %}the release{% endif %}.\n"
    "{# keep this prompt scoped #}"
)

_JINJA_INVALID_PROMPT = "Hello {{ missing }\nPlease fix before sending."
_SEARCH_PROMPT = (
    "Draft alpha release notes for the prompt search polish\n"
    "Compare the alpha match highlight against the active cursor\n"
    "Ship the final alpha search behavior with clear wrap feedback"
)
_CURSOR_PROMPT = "Readable cursor colors make vim modes obvious"
_XPROMPT_HIGHLIGHT_SOLO = (
    "#gh:sase %auto #pr:my_change %m:opus fix the bug use /sase_plan\n"
    "```text\n#literal %wait:no\n---\n```"
)
_XPROMPT_HIGHLIGHT_STACK = (
    "#gh:sase %auto #pr:my_change inspect the failure\n"
    "---\n"
    "%{%m:opus | %m:sonnet} #git:home summarize the fix use /sase_plan"
)
_CODEBLOCK_HIGHLIGHT_SOLO = (
    "#gh:sase %auto inspect `foo`; keep `/sase_gate` literal\n"
    "```\n"
    "plain text without a language still forms one card\n"
    "```\n"
    "Then verify the typed transform:\n"
    "```python\n"
    "def normalize(value: str) -> str:\n"
    "    # #literal and %wait:no stay inert here\n"
    "    return value.strip().lower()\n"
    "```"
)
_CODEBLOCK_HIGHLIGHT_STACK = (
    "#gh:sase %auto review the `increment` Python transform\n"
    "```python\n"
    "def increment(value: int) -> int:\n"
    "    return value + 1\n"
    "```\n"
    "---\n"
    "%{%m:opus | %m:sonnet} #git:home verify the `src/*.py` path\n"
    "```bash\n"
    "for file in src/*.py; do\n"
    "  printf '%s\\n' \"$file\"\n"
    "done\n"
    "```"
)

_VISUAL_SKILL_ENTRIES = [
    XPromptAssistEntry(
        name="sase_plan",
        insertion="#sase_plan",
        reference_prefix="#",
        kind="xprompt",
        input_signature=None,
        inputs=(),
        content_preview=None,
        description="Create an implementation plan",
        is_skill=True,
    )
]


def _patch_visual_skill_catalog(monkeypatch: pytest.MonkeyPatch) -> None:
    def _entries(
        _app: AceApp,
        _project: str | None,
        *,
        schedule: bool = True,
    ) -> list[XPromptAssistEntry]:
        del schedule
        return _VISUAL_SKILL_ENTRIES

    monkeypatch.setattr(AceApp, "get_prompt_catalog_assist_entries", _entries)


async def _mount_prompt_bar(page: AcePage, initial_value: str) -> PromptInputBar:
    """Mount a prompt bar over the running app and wait for it to settle."""
    await page.app.mount(
        PromptInputBar(initial_value=initial_value, id="prompt-input-bar")
    )
    bar = page.app.query_one("#prompt-input-bar", PromptInputBar)
    await wait_for_state(
        page,
        lambda: bar.active_text_area().has_focus and len(bar._stack) > 0,
        description="mounted prompt stack and active-pane focus",
    )
    await wait_for_visual_idle(page)
    return bar


def _compute_jinja_now(text_area: PromptTextArea) -> None:
    text_area._jinja_diagnostics_generation += 1
    generation = text_area._jinja_diagnostics_generation
    text_area._fire_jinja_diagnostics_timer(
        generation,
        text_area.text,
        text_area._absolute_offset(text_area.cursor_location),
    )


async def test_prompt_stack_two_panes_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await page.expect_state("tab", "changespecs")
        await _mount_prompt_bar(page, _TWO_PANE_PROMPT)

        ace_png_visual.assert_page_png(
            page,
            "prompt_stack_two_panes_120x40",
            title="ACE prompt stack — active lower pane",
        )


async def test_prompt_stack_active_upper_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await page.expect_state("tab", "changespecs")
        bar = await _mount_prompt_bar(page, _TWO_PANE_PROMPT)

        # Focus the top pane so the accent border moves up and the bottom pane
        # dims — the mirror image of the default active-lower snapshot.
        bar.focus_item(0)
        await wait_for_state(
            page,
            lambda: bar._stack.selected_index == 0 and bar.active_text_area().has_focus,
            description="upper prompt pane focus",
        )
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "prompt_stack_active_upper_120x40",
            title="ACE prompt stack — active upper pane",
        )


async def test_prompt_submit_choice_modal_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await page.expect_state("tab", "changespecs")
        await _mount_prompt_bar(page, _TWO_PANE_PROMPT)

        page.app.push_screen(PromptSubmitChoiceModal(prompt_count=2))
        await page.expect_modal("PromptSubmitChoiceModal")
        await wait_for_svg_contains(page, "Launch all 2 prompts")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "prompt_submit_choice_modal_120x40",
            title="ACE prompt stack — submit chooser",
        )


async def test_prompt_stack_compact_inactive_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)

    async with AcePage(
        query='"visual"', changespecs=changespecs(), size=(80, 30)
    ) as page:
        await wait_for_startup(page)
        await page.expect_state("tab", "changespecs")
        await _mount_prompt_bar(page, _COMPACT_PROMPT)

        ace_png_visual.assert_page_png(
            page,
            "prompt_stack_compact_inactive_80x30",
            title="ACE prompt stack — compact inactive panes",
        )


async def test_prompt_stack_completion_panel_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await page.expect_state("tab", "changespecs")
        bar = await _mount_prompt_bar(page, _TWO_PANE_PROMPT)

        # The completion panel is scoped to the active pane; render a
        # deterministic xprompt completion to pin its in-stack styling.
        bar.show_file_completions(
            "fo",
            _XPROMPT_COMPLETION_ROWS,
            selected_index=1,
            completion_kind="xprompt",
        )
        await wait_for_state(
            page,
            lambda: (
                bar._completion_visible and bar._completion_panel_kind == "completion"
            ),
            description="xprompt completion panel visibility",
        )
        await wait_for_svg_contains(page, "followup")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "prompt_stack_completion_panel_120x40",
            title="ACE prompt stack — completion panel in active pane",
        )


async def test_prompt_stack_g_prefix_hints_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await page.expect_state("tab", "changespecs")
        indicator = page.app.query_one(
            "#stashed-prompts-indicator", StashedPromptsIndicator
        )
        indicator.set_count(2)
        bar = await _mount_prompt_bar(page, _TWO_PANE_PROMPT)

        await page.press("escape", "g")
        text_area = bar.active_text_area()
        await wait_for_state(
            page,
            lambda: (
                text_area._vim_mode == "normal"
                and text_area._pending_keys == "g"
                and bar._g_prefix_hints_visible
            ),
            description="NORMAL-mode g-prefix hint panel",
        )
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "prompt_stack_g_prefix_hints_120x40",
            title="ACE prompt stack — g prefix hints",
        )


async def test_prompt_search_highlight_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await page.expect_state("tab", "changespecs")
        bar = await _mount_prompt_bar(page, _SEARCH_PROMPT)

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


async def test_prompt_xprompt_highlight_solo_light_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    _patch_visual_skill_catalog(monkeypatch)

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        page.app.theme = "textual-light"
        await wait_for_startup(page)
        await page.expect_state("tab", "changespecs")
        await _mount_prompt_bar(page, _XPROMPT_HIGHLIGHT_SOLO)

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
    _patch_visual_skill_catalog(monkeypatch)

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await page.expect_state("tab", "changespecs")
        await _mount_prompt_bar(page, _XPROMPT_HIGHLIGHT_STACK)

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

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        page.app.theme = theme
        await wait_for_startup(page)
        await page.expect_state("tab", "changespecs")
        await _mount_prompt_bar(page, _CODEBLOCK_HIGHLIGHT_SOLO)

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

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        page.app.theme = theme
        await wait_for_startup(page)
        await page.expect_state("tab", "changespecs")
        await _mount_prompt_bar(page, _CODEBLOCK_HIGHLIGHT_STACK)

        ace_png_visual.assert_page_png(page, snapshot_name, title=title)


async def test_prompt_vim_cursor_insert_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await page.expect_state("tab", "changespecs")
        bar = await _mount_prompt_bar(page, _CURSOR_PROMPT)
        text_area = bar.active_text_area()
        text_area.cursor_location = (0, 9)
        await wait_for_state(
            page,
            lambda: (
                text_area._vim_mode == "insert"
                and text_area.cursor_location == (0, 9)
                and text_area.has_focus
            ),
            description="INSERT-mode prompt cursor at fixture location",
        )
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "prompt_vim_cursor_insert_120x40",
            title="ACE prompt input - INSERT cursor",
        )


async def test_prompt_vim_cursor_normal_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await page.expect_state("tab", "changespecs")
        bar = await _mount_prompt_bar(page, _CURSOR_PROMPT)
        text_area = bar.active_text_area()
        text_area.cursor_location = (0, 9)
        text_area._enter_normal_mode()
        await wait_for_state(
            page,
            lambda: (
                text_area._vim_mode == "normal"
                and text_area.cursor_location == (0, 9)
                and text_area.has_focus
            ),
            description="NORMAL-mode prompt cursor at fixture location",
        )
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "prompt_vim_cursor_normal_120x40",
            title="ACE prompt input - NORMAL cursor",
        )


async def test_prompt_vim_cursor_visual_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await page.expect_state("tab", "changespecs")
        bar = await _mount_prompt_bar(page, _CURSOR_PROMPT)
        text_area = bar.active_text_area()
        text_area.cursor_location = (0, 9)
        text_area._enter_visual_mode("charwise")
        await wait_for_state(
            page,
            lambda: (
                text_area._vim_mode == "visual"
                and text_area._visual_cursor == (0, 9)
                and text_area.has_focus
            ),
            description="VISUAL-mode prompt cursor at fixture location",
        )
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "prompt_vim_cursor_visual_120x40",
            title="ACE prompt input - VISUAL cursor",
        )


async def test_prompt_jinja_valid_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    monkeypatch.setattr(jinja_inspect, "known_toplevel_context", lambda: {"root"})

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await page.expect_state("tab", "changespecs")
        bar = await _mount_prompt_bar(page, _JINJA_VALID_PROMPT)
        text_area = bar.active_text_area()
        _compute_jinja_now(text_area)
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "prompt_jinja_valid_120x40",
            title="ACE prompt input — Jinja valid state",
        )


async def test_prompt_jinja_invalid_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    monkeypatch.setattr(jinja_inspect, "known_toplevel_context", lambda: {"root"})

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await page.expect_state("tab", "changespecs")
        bar = await _mount_prompt_bar(page, _JINJA_INVALID_PROMPT)
        text_area = bar.active_text_area()
        _compute_jinja_now(text_area)
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "prompt_jinja_invalid_120x40",
            title="ACE prompt input — Jinja invalid state",
        )


def _xprompt_candidate(
    name: str,
    *,
    kind: str,
    description: str,
) -> CompletionCandidate:
    return CompletionCandidate(
        display=f"#{name}",
        insertion=name,
        is_dir=False,
        name=name,
        metadata=XPromptAssistEntry(
            name=name,
            insertion=name,
            reference_prefix="#",
            kind=kind,
            input_signature=None,
            inputs=(),
            content_preview=None,
            description=description,
        ),
    )


_XPROMPT_COMPLETION_ROWS = [
    _xprompt_candidate("fork", kind="part", description="Strip SASE lingo and fork"),
    _xprompt_candidate(
        "format", kind="workflow", description="Run the formatter across the diff"
    ),
    _xprompt_candidate(
        "followup", kind="part", description="Draft a follow-up review pass"
    ),
]
