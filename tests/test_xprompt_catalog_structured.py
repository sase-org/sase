from __future__ import annotations

from pathlib import Path
from types import ModuleType
from unittest.mock import patch

import pytest

from sase import project_aliases, project_display_names
from sase.xprompt import project_identity
from sase.xprompt.catalog import (
    MAX_MOBILE_CONTENT_PREVIEW_CHARS,
    _gather_entries,
    build_structured_xprompts_catalog,
)
from sase.xprompt.loader import load_xprompts_from_internal
from sase.xprompt.models import UNSET, InputArg, InputType, OutputSpec
from sase.xprompt.tags import XPromptTag
from sase.xprompt.workflow_models import Workflow, WorkflowStep

from tests._xprompt_catalog_helpers import make_xprompt
from tests.main.project_handler_helpers import _disk_project_records, _write_project


def test_structured_catalog_projects_filters_and_caps_preview(
    tmp_path: Path,
) -> None:
    ws = tmp_path / "sase"
    ws.mkdir()
    local_source = ws / ".sase" / "xprompts" / "local.md"
    local_source.parent.mkdir(parents=True)
    local_source.write_text("local")
    long_body = "a" * (MAX_MOBILE_CONTENT_PREVIEW_CHARS + 25)
    global_xp = make_xprompt(
        "review",
        source_path="config",
        tags=frozenset({XPromptTag.mentor}),
        description="Review code",
    )
    local_xp = make_xprompt(
        "local_fix",
        source_path=str(local_source),
        tags=frozenset({XPromptTag.fix_hook}),
        inputs=[InputArg(name="path", type=InputType.PATH)],
        skill=True,
        content=long_body,
    )
    other_xp = make_xprompt("other", source_path=str(tmp_path / "other.md"))

    with (
        patch(
            "sase.xprompt.catalog.get_all_xprompts", return_value={"review": global_xp}
        ),
        patch("sase.xprompt.catalog.get_all_workflows", return_value={}),
        patch(
            "sase.xprompt.catalog.get_known_project_workspaces",
            return_value={"sase": ws, "other": tmp_path / "other"},
        ),
        patch(
            "sase.xprompt.catalog.load_project_local_xprompts",
            side_effect=[
                {"local_fix": local_xp},
                {"other": other_xp},
            ],
        ),
        patch(
            "sase.xprompt.catalog.get_sase_package_xprompts_dir",
            return_value=tmp_path / "pkg",
        ),
        patch(
            "sase.xprompt.catalog.get_sase_package_default_xprompts_dir",
            return_value=tmp_path / "default",
        ),
    ):
        projection = build_structured_xprompts_catalog(
            project="sase",
            tag="fix_hook",
            query="local",
        )

    assert [entry.name for entry in projection.entries] == ["local_fix"]
    entry = projection.entries[0]
    assert entry.project == "sase"
    assert entry.insertion == "#local_fix"
    assert entry.reference_prefix == "#"
    assert entry.kind == "xprompt"
    assert entry.input_signature == "(path: path)"
    assert [inp.name for inp in entry.inputs] == ["path"]
    assert entry.inputs[0].type == "path"
    assert entry.inputs[0].required is True
    assert entry.inputs[0].default_display is None
    assert entry.inputs[0].position == 0
    assert entry.is_skill is True
    assert entry.source_path_display == ".sase/xprompts/local.md"
    assert entry.content_preview is not None
    assert len(entry.content_preview) <= MAX_MOBILE_CONTENT_PREVIEW_CHARS + 3
    assert projection.stats.total_count == 1
    assert projection.stats.project_count == 1
    assert projection.stats.skill_count == 1


def test_project_catalog_uses_one_canonical_namespace_for_all_project_refs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    projects_root = tmp_path / "projects"
    workspace = tmp_path / "workspace"
    source = workspace / "sase" / "xprompts" / "thing.md"
    source.parent.mkdir(parents=True)
    source.write_text("Project-local body")
    projects_root.mkdir()
    monkeypatch.setenv("SASE_HOME", str(tmp_path))
    _write_project(
        projects_root,
        "gh_org__proj",
        "\n".join(
            (
                f"WORKSPACE_DIR: {workspace}",
                "PROJECT_STATE: enabled",
                "PROJECT_NAME: proj",
                "PROJECT_ALIASES: short",
            )
        )
        + "\n",
    )
    monkeypatch.setattr(project_aliases, "list_project_records", _disk_project_records)
    monkeypatch.setattr(
        project_display_names,
        "list_project_records",
        _disk_project_records,
    )
    project_identity._identity_registry.cache_clear()
    project_identity._canonical_xprompt_project.cache_clear()

    cwd_copy = make_xprompt("proj/thing", source_path=str(source))
    unrelated = make_xprompt("bd/next", source_path="config")
    try:
        with (
            patch(
                "sase.xprompt.catalog.get_all_xprompts",
                return_value={"proj/thing": cwd_copy, "bd/next": unrelated},
            ),
            patch("sase.xprompt.catalog.get_all_workflows", return_value={}),
            patch(
                "sase.xprompt.catalog.get_known_project_workspaces",
                return_value={"gh_org__proj": workspace},
            ),
            patch(
                "sase.xprompt.catalog.get_sase_package_xprompts_dir",
                return_value=tmp_path / "package",
            ),
            patch(
                "sase.xprompt.catalog.get_sase_package_default_xprompts_dir",
                return_value=tmp_path / "defaults",
            ),
        ):
            gathered = _gather_entries()
            projections = {
                ref: build_structured_xprompts_catalog(project=ref)
                for ref in ("proj", "gh_org__proj", "short")
            }
    finally:
        project_identity._identity_registry.cache_clear()
        project_identity._canonical_xprompt_project.cache_clear()

    gathered_project_entries = [
        entry for entry in gathered if entry.bucket == "project"
    ]
    assert [
        (entry.xprompt.name, entry.project) for entry in gathered_project_entries
    ] == [("proj/thing", "proj")]
    assert all(
        [entry.name for entry in projection.entries] == ["bd/next", "proj/thing"]
        for projection in projections.values()
    )
    assert all(
        projection.entries[1].project == "proj" for projection in projections.values()
    )
    assert all(
        entry.name != "gh_org__proj/thing"
        for projection in projections.values()
        for entry in projection.entries
    )


def test_structured_catalog_source_filter_keeps_global_entries(
    tmp_path: Path,
) -> None:
    config_xp = make_xprompt("global", source_path="config")
    project_xp = make_xprompt("project", source_path=str(tmp_path / "p.md"))

    with (
        patch(
            "sase.xprompt.catalog.get_all_xprompts", return_value={"global": config_xp}
        ),
        patch("sase.xprompt.catalog.get_all_workflows", return_value={}),
        patch(
            "sase.xprompt.catalog.get_known_project_workspaces",
            return_value={"sase": tmp_path},
        ),
        patch(
            "sase.xprompt.catalog.load_project_local_xprompts",
            return_value={"project": project_xp},
        ),
        patch(
            "sase.xprompt.catalog.get_sase_package_xprompts_dir",
            return_value=tmp_path / "pkg",
        ),
    ):
        projection = build_structured_xprompts_catalog(project="sase", source="config")

    assert [entry.name for entry in projection.entries] == ["global"]
    assert projection.entries[0].source_bucket == "config"


def test_structured_catalog_keeps_default_config_xprompts_for_other_projects(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sase_ws = tmp_path / "sase"
    bob_ws = tmp_path / "bob-cli"
    sase_ws.mkdir()
    bob_ws.mkdir()
    monkeypatch.chdir(sase_ws)
    plan_xp = make_xprompt("plan", source_path="default_config")

    with (
        patch(
            "sase.xprompt.catalog.get_all_xprompts",
            return_value={"plan": plan_xp},
        ),
        patch("sase.xprompt.catalog.get_all_workflows", return_value={}),
        patch(
            "sase.xprompt.catalog.get_known_project_workspaces",
            return_value={"sase": sase_ws, "bob-cli": bob_ws},
        ),
        patch("sase.xprompt.catalog.load_project_local_xprompts", return_value={}),
        patch(
            "sase.xprompt.catalog.get_sase_package_xprompts_dir",
            return_value=tmp_path / "pkg",
        ),
        patch(
            "sase.xprompt.catalog.get_sase_package_default_xprompts_dir",
            return_value=tmp_path / "default_xprompts",
        ),
    ):
        bob_projection = build_structured_xprompts_catalog(project="bob-cli")
        sase_projection = build_structured_xprompts_catalog(project="sase")

    assert [entry.name for entry in bob_projection.entries] == ["plan"]
    assert bob_projection.entries[0].project is None
    assert [entry.name for entry in sase_projection.entries] == ["plan"]
    assert sase_projection.entries[0].project is None


def test_structured_catalog_preserves_workflow_description() -> None:
    workflow = Workflow(
        name="ship",
        steps=[WorkflowStep(name="run", agent="Ship it")],
        source_path="config",
        description="Ship the selected target.",
    )

    with (
        patch("sase.xprompt.catalog.get_all_xprompts", return_value={}),
        patch(
            "sase.xprompt.catalog.get_all_workflows", return_value={"ship": workflow}
        ),
        patch("sase.xprompt.catalog.get_known_project_workspaces", return_value={}),
    ):
        projection = build_structured_xprompts_catalog()

    assert projection.entries[0].name == "ship"
    assert projection.entries[0].description == "Ship the selected target."


def test_structured_catalog_marks_packaged_skill_xprompts() -> None:
    internal_xprompts = load_xprompts_from_internal()

    with (
        patch(
            "sase.xprompt.catalog.get_all_xprompts",
            return_value=internal_xprompts,
        ),
        patch("sase.xprompt.catalog.get_all_workflows", return_value={}),
        patch("sase.xprompt.catalog.get_known_project_workspaces", return_value={}),
    ):
        projection = build_structured_xprompts_catalog(
            source="built-in",
            query="sase_plan",
        )

    by_name = {entry.name: entry for entry in projection.entries}
    assert "sase_plan" in by_name
    assert by_name["sase_plan"].is_skill is True
    assert by_name["sase_plan"].source_path_display == "xprompts/skills/sase_plan.md"
    assert projection.stats.skill_count >= 1


def test_structured_catalog_definition_paths_for_real_sources(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    ws = tmp_path / "workspace"
    pkg_dir = tmp_path / "pkg_xprompts"
    default_dir = tmp_path / "default_xprompts"
    config_dir = home / ".config" / "sase"
    for directory in (ws / ".xprompts", pkg_dir, default_dir, config_dir):
        directory.mkdir(parents=True)

    package_source = pkg_dir / "builtin.md"
    default_source = default_dir / "defaulted.md"
    local_source = ws / ".xprompts" / "local.md"
    config_source = config_dir / "sase.yml"
    for path in (
        package_source,
        default_source,
        local_source,
        config_source,
    ):
        path.write_text("body")

    monkeypatch.setenv("HOME", str(home))
    xprompts = {
        "builtin": make_xprompt("builtin", source_path=str(package_source)),
        "defaulted": make_xprompt("defaulted", source_path=str(default_source)),
        "cfg": make_xprompt("cfg", source_path="config"),
        "plugin": make_xprompt("plugin", source_path="plugin:module/plugin.md"),
        "runtime": make_xprompt("runtime", source_path="config:runtime"),
    }
    local_xp = make_xprompt("sase/local", source_path=str(local_source))

    with (
        patch("sase.xprompt.catalog.get_all_xprompts", return_value=xprompts),
        patch("sase.xprompt.catalog.get_all_workflows", return_value={}),
        patch(
            "sase.xprompt.catalog.get_known_project_workspaces",
            return_value={"sase": ws},
        ),
        patch(
            "sase.xprompt.catalog.load_project_local_xprompts",
            return_value={"sase/local": local_xp},
        ),
        patch(
            "sase.xprompt.catalog.get_sase_package_xprompts_dir",
            return_value=pkg_dir,
        ),
        patch(
            "sase.xprompt.catalog.get_sase_package_default_xprompts_dir",
            return_value=default_dir,
        ),
    ):
        projection = build_structured_xprompts_catalog(project="sase")

    by_name = {entry.name: entry for entry in projection.entries}
    assert by_name["builtin"].definition_path == str(package_source.resolve())
    assert by_name["defaulted"].definition_path == str(default_source.resolve())
    assert by_name["cfg"].definition_path == str(config_source.resolve())
    assert by_name["sase/local"].definition_path == str(local_source.resolve())
    assert by_name["plugin"].definition_path is None
    assert by_name["runtime"].definition_path is None


def test_structured_catalog_definition_paths_for_plugin_real_sources(
    tmp_path: Path,
) -> None:
    plugin_xprompts_dir = tmp_path / "fake_xprompts" / "xprompts"
    plugin_config_dir = tmp_path / "fake_config"
    plugin_xprompts_dir.mkdir(parents=True)
    plugin_config_dir.mkdir()
    plugin_md = plugin_xprompts_dir / "plug.md"
    plugin_flow = plugin_xprompts_dir / "flow.yml"
    plugin_config = plugin_config_dir / "default_config.yml"
    plugin_md.write_text("Plugin prompt body")
    plugin_flow.write_text("steps:\n  - name: main\n    prompt_part: body\n")
    plugin_config.write_text("xprompts:\n  cfg:\n    content: Config body\n")

    xprompt_module = ModuleType("fake_plugin.prompts")
    config_module = ModuleType("fake_plugin.config")

    def files(module: ModuleType) -> Path:
        if module.__name__ == "fake_plugin.prompts":
            return tmp_path / "fake_xprompts"
        if module.__name__ == "fake_plugin.config":
            return plugin_config_dir
        raise AssertionError(module.__name__)

    plugin_xp = make_xprompt(
        "plug",
        source_path="plugin:fake_plugin.prompts/plug.md",
    )
    plugin_cfg = make_xprompt(
        "cfg",
        source_path="plugin_config:fake_plugin.config",
    )
    plugin_workflow = Workflow(
        name="flow",
        steps=[WorkflowStep(name="main", prompt_part="Plugin workflow body")],
        source_path="plugin:fake_plugin.prompts/flow.yml",
    )

    with (
        patch(
            "sase.xprompt.catalog.get_all_xprompts",
            return_value={"plug": plugin_xp, "cfg": plugin_cfg},
        ),
        patch(
            "sase.xprompt.catalog.get_all_workflows",
            return_value={"flow": plugin_workflow},
        ),
        patch("sase.xprompt.catalog.get_known_project_workspaces", return_value={}),
        patch(
            "sase.xprompt._catalog_sources.discover_plugin_resources",
            side_effect=lambda group: (
                [xprompt_module] if group == "sase_xprompts" else [config_module]
            ),
        ),
        patch("sase.xprompt._catalog_sources.is_plugin_disabled", return_value=False),
        patch("sase.xprompt._catalog_sources.importlib.resources.files", files),
    ):
        projection = build_structured_xprompts_catalog()

    by_name = {entry.name: entry for entry in projection.entries}
    assert by_name["plug"].definition_path == str(plugin_md.resolve())
    assert by_name["flow"].definition_path == str(plugin_flow.resolve())
    assert by_name["cfg"].definition_path == str(plugin_config.resolve())


def test_structured_catalog_input_metadata_filters_step_inputs() -> None:
    xp = make_xprompt(
        "typed",
        source_path="config",
        inputs=[
            InputArg(name="required_word", type=InputType.WORD, default=UNSET),
            InputArg(name="string_default", type=InputType.LINE, default="secret"),
            InputArg(name="null_default", type=InputType.TEXT, default=None),
            InputArg(name="count", type=InputType.INT, default=3),
            InputArg(
                name="enabled",
                type=InputType.BOOL,
                default=False,
                description="Whether the feature is active.",
            ),
            InputArg(
                name="step_output",
                type=InputType.LINE,
                default=UNSET,
                is_step_input=True,
                output_schema=OutputSpec(type="json_schema", schema={"type": "object"}),
            ),
        ],
    )

    with (
        patch("sase.xprompt.catalog.get_all_xprompts", return_value={"typed": xp}),
        patch("sase.xprompt.catalog.get_all_workflows", return_value={}),
        patch("sase.xprompt.catalog.get_known_project_workspaces", return_value={}),
    ):
        projection = build_structured_xprompts_catalog()

    entry = projection.entries[0]
    assert entry.input_signature == (
        "(required_word: word, string_default?: line, null_default?: text, "
        "count?: int, enabled?: bool)"
    )
    assert [
        (inp.name, inp.type, inp.required, inp.default_display, inp.position)
        for inp in entry.inputs
    ] == [
        ("required_word", "word", True, None, 0),
        ("string_default", "line", False, None, 1),
        ("null_default", "text", False, None, 2),
        ("count", "int", False, "3", 3),
        ("enabled", "bool", False, "false", 4),
    ]
    assert entry.inputs[-1].description == "Whether the feature is active."


def test_structured_catalog_query_matches_input_descriptions() -> None:
    xp = make_xprompt(
        "repair",
        source_path="config",
        inputs=[
            InputArg(
                name="log",
                type=InputType.TEXT,
                description="Hook failure transcript to diagnose.",
            )
        ],
    )

    with (
        patch("sase.xprompt.catalog.get_all_xprompts", return_value={"repair": xp}),
        patch("sase.xprompt.catalog.get_all_workflows", return_value={}),
        patch("sase.xprompt.catalog.get_known_project_workspaces", return_value={}),
    ):
        projection = build_structured_xprompts_catalog(query="failure transcript")

    assert [entry.name for entry in projection.entries] == ["repair"]
    assert projection.entries[0].inputs[0].description == (
        "Hook failure transcript to diagnose."
    )


def test_structured_catalog_all_step_inputs_has_no_signature() -> None:
    xp = make_xprompt(
        "step_only",
        source_path="config",
        inputs=[
            InputArg(
                name="prior",
                type=InputType.LINE,
                is_step_input=True,
                output_schema=OutputSpec(type="json_schema", schema={"type": "object"}),
            )
        ],
    )

    with (
        patch("sase.xprompt.catalog.get_all_xprompts", return_value={"step_only": xp}),
        patch("sase.xprompt.catalog.get_all_workflows", return_value={}),
        patch("sase.xprompt.catalog.get_known_project_workspaces", return_value={}),
    ):
        projection = build_structured_xprompts_catalog()

    assert projection.entries[0].input_signature is None
    assert projection.entries[0].inputs == []


def test_structured_catalog_uses_canonical_standalone_insertion() -> None:
    standalone = Workflow(
        name="ship",
        inputs=[InputArg(name="target", type=InputType.WORD)],
        steps=[WorkflowStep(name="run", agent="Ship {{ target }}")],
        source_path="config",
    )
    multi_agent_xp = make_xprompt(
        "swarm",
        source_path="config",
        content="first\n---\nsecond",
    )

    with (
        patch(
            "sase.xprompt.catalog.get_all_xprompts",
            return_value={"swarm": multi_agent_xp},
        ),
        patch(
            "sase.xprompt.catalog.get_all_workflows", return_value={"ship": standalone}
        ),
        patch("sase.xprompt.catalog.get_known_project_workspaces", return_value={}),
    ):
        projection = build_structured_xprompts_catalog()

    by_name = {entry.name: entry for entry in projection.entries}
    assert by_name["ship"].kind == "standalone_workflow"
    assert by_name["ship"].reference_prefix == "#!"
    assert by_name["ship"].insertion == "#!ship"
    assert by_name["swarm"].kind == "xprompt"
    assert by_name["swarm"].reference_prefix == "#"
    assert by_name["swarm"].insertion == "#swarm"


def test_structured_catalog_pdf_engine_warning_does_not_block_records(
    tmp_path: Path,
) -> None:
    xp = make_xprompt("hello", source_path="config")
    with (
        patch("sase.xprompt.catalog.get_all_xprompts", return_value={"hello": xp}),
        patch("sase.xprompt.catalog.get_all_workflows", return_value={}),
        patch("sase.xprompt.catalog.get_known_project_workspaces", return_value={}),
        patch("sase.xprompt.catalog.shutil.which", return_value=None),
    ):
        projection = build_structured_xprompts_catalog(include_pdf=True)

    assert [entry.name for entry in projection.entries] == ["hello"]
    assert projection.stats.pdf_requested is True
    assert projection.catalog_attachment is None
    assert projection.warnings == ["PDF catalog was not generated"]
    assert projection.skipped[0].target == "xprompt-catalog.pdf"
