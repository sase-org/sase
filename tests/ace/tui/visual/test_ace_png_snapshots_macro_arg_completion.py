"""ACE PNG snapshots for macro keyword-argument completion."""

from __future__ import annotations

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.widgets.file_completion import CompletionCandidate
from sase.ace.tui.widgets._file_completion_macro_args import (
    build_macro_arg_completion_candidates,
    build_macro_arg_model_completion_candidates,
)
from sase.ace.tui.widgets.macro_arg_assist import (
    MacroArgNameMetadata,
    MacroAssistEntry,
    MacroInputHint,
    detect_macro_arg_completion_at_cursor,
)
from sase.ace.tui.modals.enum_choice_picker_modal import EnumChoicePickerModal
from sase.macro.models import InputArg, InputChoice, InputType
from sase.macro.model_completion import ModelCompletionEntry
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patches,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_state,
    wait_for_svg_contains,
    wait_for_visual_idle,
)
from tests.ace.tui.visual._ace_prompt_png_snapshot_helpers import mount_prompt_bar
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


def _arg_name(
    name: str,
    type_: str,
    position: int,
    *,
    required: bool = True,
    default_display: str | None = None,
    description: str | None = None,
) -> CompletionCandidate:
    return CompletionCandidate(
        display=f"{name}=",
        insertion=f"{name}=",
        is_dir=False,
        name=name,
        metadata=MacroArgNameMetadata(
            reference_text="#review",
            input_hint=MacroInputHint(
                name=name,
                type=type_,
                required=required,
                default_display=default_display,
                position=position,
                description=description,
            ),
        ),
    )


_ARG_ROWS = [
    _arg_name("path", "path", 0, description="file to review"),
    _arg_name(
        "enabled",
        "bool",
        1,
        required=False,
        default_display="true",
        description="turn on",
    ),
    _arg_name("count", "int", 2, required=False, default_display="3"),
    _arg_name("label", "str", 3, description="a free-form label"),
]


@pytest.mark.parametrize(
    ("theme", "snapshot_name", "title"),
    [
        pytest.param(
            "textual-dark",
            "prompt_macro_arg_completion_dark_120x40",
            "ACE prompt input — macro keyword-argument completion, dark theme",
            id="dark",
        ),
        pytest.param(
            "textual-light",
            "prompt_macro_arg_completion_light_120x40",
            "ACE prompt input — macro keyword-argument completion, light theme",
            id="light",
        ),
    ],
)
async def test_macro_arg_name_completion_png_snapshot(
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
        bar = await mount_prompt_bar(page, "#review(")

        bar.show_file_completions(
            "",
            _ARG_ROWS,
            selected_index=1,
            completion_kind="macro_arg_name",
        )
        await wait_for_state(
            page,
            lambda: (
                bar._completion_visible and bar._completion_panel_kind == "completion"
            ),
            description="macro argument completion visibility",
        )
        await wait_for_svg_contains(page, "#review args")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(page, snapshot_name, title=title)


_ENUM_VALUE_CHOICES = (
    InputChoice(value="fast", label="Fast", description="quick pass"),
    InputChoice(value="thorough", label="Thorough", description="deep review"),
    InputChoice(value="balanced", label="Balanced", description="middle ground"),
)


def _enum_value_entry() -> MacroAssistEntry:
    return MacroAssistEntry(
        name="deploy",
        insertion="#deploy",
        reference_prefix="#",
        kind="macro",
        input_signature=None,
        inputs=(
            MacroInputHint(
                name="mode",
                type="enum",
                required=True,
                default_display="thorough",
                position=0,
                description="review depth",
                choices=_ENUM_VALUE_CHOICES,
            ),
        ),
        content_preview=None,
    )


@pytest.mark.parametrize(
    ("theme", "snapshot_name", "title"),
    [
        pytest.param(
            "textual-dark",
            "prompt_macro_arg_enum_value_dark_120x40",
            "ACE prompt input — macro enum value completion, dark theme",
            id="dark",
        ),
        pytest.param(
            "textual-light",
            "prompt_macro_arg_enum_value_light_120x40",
            "ACE prompt input — macro enum value completion, light theme",
            id="light",
        ),
    ],
)
async def test_macro_arg_enum_value_completion_png_snapshot(
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
        source = "#deploy(mode="
        bar = await mount_prompt_bar(page, source)

        # Drive the real path: TUI detection plus the shared Rust choice
        # builder, so the menu proves production row/label/default rendering.
        ctx = detect_macro_arg_completion_at_cursor(
            source, len(source), [_enum_value_entry()]
        )
        assert ctx is not None
        assert ctx.completion_kind == "macro_arg_value"
        candidates, _shared = build_macro_arg_completion_candidates(ctx)
        assert [candidate.name for candidate in candidates] == [
            "fast",
            "thorough",
            "balanced",
        ]

        bar.show_file_completions(
            "",
            candidates,
            selected_index=1,
            completion_kind="macro_arg_value",
        )
        await wait_for_state(
            page,
            lambda: (
                bar._completion_visible and bar._completion_panel_kind == "completion"
            ),
            description="macro enum value completion visibility",
        )
        await wait_for_svg_contains(page, "thorough")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(page, snapshot_name, title=title)


_PICKER_CHOICES = (
    InputChoice(value="fast", label="Fast", description="quick pass"),
    InputChoice(value="thorough", label="Thorough", description="deep review"),
    InputChoice(value="balanced", label="Balanced", description="middle ground"),
    InputChoice(value="concise", label="Concise", description="short output"),
    InputChoice(value="verbose", label="Verbose", description="full detail"),
    InputChoice(value="debug", label="Debug", description="diagnostic output"),
    InputChoice(value="audit", label="Audit", description="compliance trail"),
)


@pytest.mark.parametrize(
    ("theme", "snapshot_name", "title"),
    [
        pytest.param(
            "textual-dark",
            "typed_form_enum_choice_picker_dark_120x40",
            "ACE typed input form — searchable enum choice picker, dark theme",
            id="dark",
        ),
        pytest.param(
            "textual-light",
            "typed_form_enum_choice_picker_light_120x40",
            "ACE typed input form — searchable enum choice picker, light theme",
            id="light",
        ),
    ],
)
async def test_typed_form_enum_choice_picker_png_snapshot(
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
        await mount_prompt_bar(page, "Review the deploy gate inputs.")

        arg = InputArg(
            name="mode",
            type=InputType.ENUM,
            description="review depth",
            choices=_PICKER_CHOICES,
        )
        page.app.push_screen(EnumChoicePickerModal(arg, current="balanced"))
        await page.expect_modal("EnumChoicePickerModal")
        modal = page.app.screen
        assert isinstance(modal, EnumChoicePickerModal)
        # Narrow to the single "balanced" row to prove live filtering.
        await page.press("a", "l")
        await wait_for_state(
            page,
            lambda: modal._query == "al" and len(modal._rows) == 1,
            description="enum picker filter narrows to one row",
        )
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(page, snapshot_name, title=title)


def _model_arg_entry() -> MacroAssistEntry:
    return MacroAssistEntry(
        name="research_swarm",
        insertion="#research_swarm",
        reference_prefix="#",
        kind="macro",
        input_signature=None,
        inputs=(
            MacroInputHint(
                name="claude_model",
                type="word",
                required=True,
                default_display=None,
                position=0,
                named_type="model",
                value_role="model",
            ),
        ),
        content_preview=None,
    )


@pytest.mark.parametrize(
    ("theme", "snapshot_name", "title"),
    [
        pytest.param(
            "textual-dark",
            "prompt_macro_arg_model_value_dark_120x40",
            "ACE prompt input — macro model value completion, dark theme",
            id="dark",
        ),
        pytest.param(
            "textual-light",
            "prompt_macro_arg_model_value_light_120x40",
            "ACE prompt input — macro model value completion, light theme",
            id="light",
        ),
    ],
)
async def test_macro_arg_model_value_completion_png_snapshot(
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
        source = "#research_swarm(claude_model="
        bar = await mount_prompt_bar(page, source)
        ctx = detect_macro_arg_completion_at_cursor(
            source, len(source), [_model_arg_entry()]
        )
        assert ctx is not None
        assert ctx.completion_kind == "macro_arg_model"
        candidates, _shared = build_macro_arg_model_completion_candidates(
            ctx,
            (
                ModelCompletionEntry(
                    value="@large",
                    display="@large",
                    description="Large alias for complex work",
                    kind="implicit_alias",
                    alias_kind="role",
                    target_provider="claude",
                    target_model="opus",
                    target_effort="high",
                ),
                ModelCompletionEntry(
                    value="claude-fable-5",
                    display="claude-fable-5",
                    description="Claude (fable)",
                    provider="claude",
                    provider_display="Claude",
                    aliases=("fable",),
                ),
                ModelCompletionEntry(
                    value="gpt-5.6-sol",
                    display="gpt-5.6-sol",
                    description="Codex (gpt56sol)",
                    provider="codex",
                    provider_display="Codex",
                    aliases=("gpt56sol",),
                ),
            ),
        )
        assert candidates

        bar.show_file_completions(
            "",
            candidates,
            selected_index=0,
            completion_kind="macro_arg_model",
        )
        await wait_for_state(
            page,
            lambda: (
                bar._completion_visible and bar._completion_panel_kind == "completion"
            ),
            description="macro model value completion visibility",
        )
        await wait_for_svg_contains(page, "@large")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(page, snapshot_name, title=title)
