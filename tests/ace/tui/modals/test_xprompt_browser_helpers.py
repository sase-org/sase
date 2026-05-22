from pathlib import Path
from unittest.mock import patch

from rich.text import Text

from sase.ace.tui.modals.xprompt_browser_modal import XPromptBrowserModal
from sase.ace.tui.modals.xprompt_browser_helpers import (
    append_input_args,
    classify_source,
)
from sase.xprompt.models import InputArg, InputType
from sase.xprompt.workflow_models import Workflow, WorkflowStep


def test_classify_source_default_xprompts_builtin(tmp_path: Path) -> None:
    pkg_dir = tmp_path / "xprompts"
    default_dir = tmp_path / "default_xprompts"
    default_dir.mkdir()
    source = default_dir / "research_swarm.md"
    source.write_text("x")

    with (
        patch(
            "sase.ace.tui.modals.xprompt_browser_helpers.get_sase_package_xprompts_dir",
            return_value=pkg_dir,
        ),
        patch(
            "sase.ace.tui.modals.xprompt_browser_helpers."
            "get_sase_package_default_xprompts_dir",
            return_value=default_dir,
        ),
    ):
        category, display_path, is_editable = classify_source(str(source))

    assert category == "Built-in"
    assert display_path.endswith("default_xprompts/research_swarm.md")
    assert is_editable is True


def test_append_input_args_keeps_required_and_optional_modal_styles() -> None:
    text = Text("prompt")
    append_input_args(
        text,
        [
            InputArg(name="required", type=InputType.WORD),
            InputArg(name="optional", type=InputType.INT, default=4),
        ],
    )

    assert text.plain == "prompt\n     required\n     optional=4"
    assert [(span.start, span.end, span.style) for span in text.spans] == [
        (12, 20, "#D7AF87"),
        (26, 34, "dim #D7AF87"),
        (34, 36, "dim #888888"),
    ]


def test_browser_filters_and_previews_descriptions() -> None:
    prompts = {
        "review": Workflow(
            name="review",
            description="Review a selected diff.",
            inputs=[
                InputArg(
                    name="diff",
                    type=InputType.PATH,
                    description="Diff file to inspect.",
                )
            ],
            steps=[WorkflowStep(name="prompt", prompt_part="body")],
        ),
        "ship": Workflow(
            name="ship",
            steps=[WorkflowStep(name="run", agent="ship")],
        ),
    }

    with (
        patch(
            "sase.ace.tui.modals.xprompt_browser_modal.get_all_prompts",
            return_value=prompts,
        ),
        patch("sase.xprompt.loader.get_all_project_local_prompts", return_value={}),
    ):
        modal = XPromptBrowserModal()

    modal._rebuild_groups("file to inspect")
    assert [item.name for item in modal._get_flat_items()] == ["review"]
    preview = modal._create_simple_preview(prompts["review"])
    assert "Review a selected diff." in preview
    assert "Diff file to inspect." in preview
