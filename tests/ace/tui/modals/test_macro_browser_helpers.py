from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from rich.text import Text

from sase.ace.tui.modals.macro_browser_pane import MacroBrowserPane
from sase.ace.tui.modals import macro_browser_helpers
from sase.ace.tui.modals.macro_browser_helpers import (
    append_input_args,
    classify_source,
    is_yaml_backed_source,
)
from sase.ace.tui.modals.macro_browser_options import (
    browser_hint_text,
    create_item_label,
)
from sase.ace.tui.modals.macro_browser_preview import (
    create_meta_text,
    create_simple_preview,
)
from sase.macro.models import InputArg, InputType
from sase.macro.workflow_models import Workflow, WorkflowStep


def test_classify_source_default_macros_builtin(tmp_path: Path) -> None:
    pkg_dir = tmp_path / "macros"
    default_dir = tmp_path / "default_macros"
    default_dir.mkdir()
    source = default_dir / "research_swarm.md"
    source.write_text("x")

    with (
        patch(
            "sase.ace.tui.modals.macro_browser_helpers.get_sase_package_macros_dir",
            return_value=pkg_dir,
        ),
        patch(
            "sase.ace.tui.modals.macro_browser_helpers."
            "get_sase_package_default_macros_dir",
            return_value=default_dir,
        ),
    ):
        category, display_path, is_editable = classify_source(str(source))

    assert category == "Built-in"
    assert display_path.endswith("default_macros/research_swarm.md")
    assert is_editable is False


def test_classify_source_project_memory_note(tmp_path: Path, monkeypatch) -> None:
    project_root = tmp_path / "workspace"
    memory_source = project_root / "sase" / "memory" / "glossary.md"
    memory_source.parent.mkdir(parents=True)
    memory_source.write_text("---\ntype: core\n---\nbody\n")
    monkeypatch.chdir(project_root)

    category, display_path, is_editable = classify_source(str(memory_source))

    assert category == "Project sase/memory/"
    assert display_path == "sase/memory/glossary.md"
    assert is_editable is True


def test_classify_source_labels_legacy_project_macro_path(
    tmp_path: Path, monkeypatch
) -> None:
    project_root = tmp_path / "workspace"
    new_dir = project_root / "sase" / "macros"
    legacy_dir = project_root / "sase" / "xprompts"
    layout = SimpleNamespace(
        macros=SimpleNamespace(candidates=(new_dir,), write_path=new_dir),
        xprompts=SimpleNamespace(write_path=legacy_dir),
        memory=SimpleNamespace(candidates=()),
    )
    monkeypatch.setattr(
        macro_browser_helpers, "discover_project_root", lambda: project_root
    )
    monkeypatch.setattr(
        macro_browser_helpers, "resolve_project_layout", lambda *_a, **_k: layout
    )
    monkeypatch.setattr(
        macro_browser_helpers, "resolve_home_layout", lambda *_a, **_k: layout
    )
    monkeypatch.setattr(
        macro_browser_helpers,
        "display_path",
        lambda path, **_kwargs: str(path),
    )

    category, display_path, is_editable = macro_browser_helpers.classify_source(
        str(legacy_dir / "review.md")
    )

    assert category == "Project macros/ (legacy)"
    assert display_path.endswith("sase/xprompts/review.md")
    assert is_editable is True


def test_classify_source_labels_legacy_home_macro_path(
    tmp_path: Path, monkeypatch
) -> None:
    project_root = tmp_path / "workspace"
    home_root = Path.home()
    new_project_dir = project_root / "sase" / "macros"
    legacy_project_dir = project_root / "sase" / "xprompts"
    new_home_dir = home_root / "sase" / "macros"
    legacy_home_dir = home_root / "sase" / "xprompts"
    project_layout = SimpleNamespace(
        macros=SimpleNamespace(
            candidates=(new_project_dir,), write_path=new_project_dir
        ),
        xprompts=SimpleNamespace(write_path=legacy_project_dir),
        memory=SimpleNamespace(candidates=()),
    )
    home_layout = SimpleNamespace(
        macros=SimpleNamespace(candidates=(new_home_dir,), write_path=new_home_dir),
        xprompts=SimpleNamespace(write_path=legacy_home_dir),
        memory=SimpleNamespace(candidates=()),
    )
    monkeypatch.setattr(
        macro_browser_helpers, "discover_project_root", lambda: project_root
    )
    monkeypatch.setattr(
        macro_browser_helpers,
        "resolve_project_layout",
        lambda *_a, **_k: project_layout,
    )
    monkeypatch.setattr(
        macro_browser_helpers,
        "resolve_home_layout",
        lambda *_a, **_k: home_layout,
    )
    monkeypatch.setattr(
        macro_browser_helpers,
        "display_path",
        lambda path, **_kwargs: str(path),
    )

    category, display_path, is_editable = macro_browser_helpers.classify_source(
        str(legacy_home_dir / "review.md")
    )

    assert category == "Home macros/ (legacy)"
    assert display_path.endswith("sase/xprompts/review.md")
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
    assert is_yaml_backed_source("/home/u/.macros/note.md") is False
    assert is_yaml_backed_source("plugin:demo/helper.md") is False
    # ``None`` is a programmatic built-in with no file: treated as non-YAML.
    assert is_yaml_backed_source(None) is False


def test_is_yaml_backed_source_flags_yaml_paths() -> None:
    assert is_yaml_backed_source("/home/u/macros/flow.yml") is True
    assert is_yaml_backed_source("/home/u/macros/flow.yaml") is True
    # Case-insensitive on the extension.
    assert is_yaml_backed_source("/home/u/macros/FLOW.YAML") is True
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


def test_browser_hint_text_toggles_filter_and_load_segments() -> None:
    browse = browser_hint_text(loadable=True)
    assert browse.startswith("j/k: move  /: filter")
    assert "^i: load  " in browse
    assert browse.endswith("Esc: close")
    assert "Tab/Shift+Tab" not in browse

    filtering = browser_hint_text(loadable=True, filtering=True)
    assert filtering.startswith("^n/^p: move  enter/Esc: done")
    assert "^i: load  " in filtering
    assert "Esc: close" not in filtering
    assert "/: filter" not in filtering
    assert "Tab/Shift+Tab" not in filtering


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
            "sase.ace.tui.modals.macro_browser_pane.get_all_prompts",
            return_value=prompts,
        ),
        patch("sase.macro.loader.get_all_project_local_prompts", return_value={}),
    ):
        pane = MacroBrowserPane()

    pane._rebuild_groups("file to inspect")
    assert [item.name for item in pane._get_flat_items()] == ["review"]
    preview = pane._create_simple_preview(prompts["review"])
    assert "Review a selected diff." in preview
    assert "Diff file to inspect." in preview


def test_browser_labels_and_previews_memory_entries() -> None:
    from sase.ace.tui.modals.macro_browser_helpers import BrowserItem

    workflow = Workflow(
        name="memory/glossary",
        description="Glossary terms.",
        memory_type="reference",
        steps=[WorkflowStep(name="prompt", prompt_part="Memory body")],
    )
    item = BrowserItem(
        name="memory/glossary",
        workflow=workflow,
        source_category="Project sase/memory/",
        source_path="/tmp/sase/memory/glossary.md",
        display_path="sase/memory/glossary.md",
        is_editable=True,
        item_type="macro",
        kind="memory",
        insertion="#memory/glossary",
    )

    assert create_item_label(item).plain == "  #memory/glossary  memory · reference"
    preview = create_simple_preview(workflow)
    assert "# Memory: memory/glossary" in preview
    assert "memory type: reference" in preview
    assert "Type: memory · reference (simple)" in create_meta_text(item).plain
