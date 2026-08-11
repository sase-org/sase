from pathlib import Path
from unittest.mock import patch

from rich.text import Text

from sase.ace.tui.modals.xprompt_browser_pane import XPromptBrowserPane
from sase.ace.tui.modals.xprompt_browser_helpers import (
    append_input_args,
    classify_source,
    is_yaml_backed_source,
)
from sase.ace.tui.modals.xprompt_browser_options import create_item_label
from sase.ace.tui.modals.xprompt_browser_preview import (
    create_meta_text,
    create_simple_preview,
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
    assert is_editable is False


def test_classify_source_project_memory_note(tmp_path: Path, monkeypatch) -> None:
    project_root = tmp_path / "workspace"
    memory_source = project_root / "sase" / "memory" / "glossary.md"
    memory_source.parent.mkdir(parents=True)
    memory_source.write_text("---\ntype: short\n---\nbody\n")
    monkeypatch.chdir(project_root)

    category, display_path, is_editable = classify_source(str(memory_source))

    assert category == "Project sase/memory/"
    assert display_path == "sase/memory/glossary.md"
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


def test_is_yaml_backed_source_treats_md_paths_as_loadable() -> None:
    # Standalone ``.md`` prompt-part files (the only inline-loadable rows).
    assert is_yaml_backed_source("/home/u/.xprompts/note.md") is False
    assert is_yaml_backed_source("plugin:demo/helper.md") is False
    # ``None`` is a programmatic built-in with no file: treated as non-YAML.
    assert is_yaml_backed_source(None) is False


def test_is_yaml_backed_source_flags_yaml_paths() -> None:
    assert is_yaml_backed_source("/home/u/xprompts/flow.yml") is True
    assert is_yaml_backed_source("/home/u/xprompts/flow.yaml") is True
    # Case-insensitive on the extension.
    assert is_yaml_backed_source("/home/u/xprompts/FLOW.YAML") is True
    # A plugin can ship a ``.yml`` workflow too.
    assert is_yaml_backed_source("plugin:demo/flow.yml") is True


def test_is_yaml_backed_source_flags_config_source_identifiers() -> None:
    assert is_yaml_backed_source("config") is True
    assert is_yaml_backed_source("local_config") is True
    assert is_yaml_backed_source("default_config") is True


def test_is_yaml_backed_source_flags_config_and_plugin_prefixes() -> None:
    assert is_yaml_backed_source("config_overlay:sase_extra.yml") is True
    assert is_yaml_backed_source("project_local_config:sase") is True
    assert is_yaml_backed_source("plugin_config:sase_github") is True


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
            "sase.ace.tui.modals.xprompt_browser_pane.get_all_prompts",
            return_value=prompts,
        ),
        patch("sase.xprompt.loader.get_all_project_local_prompts", return_value={}),
    ):
        pane = XPromptBrowserPane()

    pane._rebuild_groups("file to inspect")
    assert [item.name for item in pane._get_flat_items()] == ["review"]
    preview = pane._create_simple_preview(prompts["review"])
    assert "Review a selected diff." in preview
    assert "Diff file to inspect." in preview


def test_browser_labels_and_previews_memory_entries() -> None:
    from sase.ace.tui.modals.xprompt_browser_helpers import BrowserItem

    workflow = Workflow(
        name="memory/glossary",
        description="Glossary terms.",
        memory_type="short",
        steps=[WorkflowStep(name="prompt", prompt_part="Memory body")],
    )
    item = BrowserItem(
        name="memory/glossary",
        workflow=workflow,
        source_category="Project sase/memory/",
        source_path="/tmp/sase/memory/glossary.md",
        display_path="sase/memory/glossary.md",
        is_editable=True,
        item_type="xprompt",
        kind="memory",
        insertion="#memory/glossary",
    )

    assert create_item_label(item).plain == "  #memory/glossary  memory · short"
    preview = create_simple_preview(workflow)
    assert "# Memory: memory/glossary" in preview
    assert "memory type: short" in preview
    assert "Type: memory · short (simple)" in create_meta_text(item).plain
