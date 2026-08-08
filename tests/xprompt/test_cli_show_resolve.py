"""Tests for xprompt show definition resolution and its JSON record."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from sase.xprompt._catalog_sources import classify, source_path_display
from sase.xprompt.cli_show_model import SHOW_SCHEMA_VERSION, XPromptShowRecord
from sase.xprompt.cli_show_resolve import (
    ShowLookupMiss,
    normalize_show_name,
    resolve_show_record,
)
from sase.xprompt.config_yaml import config_entry_line_span
from sase.xprompt.models import InputArg, InputType, OutputSpec, XPrompt
from sase.xprompt.workflow_models import Workflow, WorkflowStep
from sase.xprompt.xprompt_sources import (
    definition_file_for_source,
    definition_line_for,
)


@pytest.mark.parametrize(
    ("raw", "expected", "stripped"),
    [
        ("foo", "foo", False),
        ("#foo", "foo", False),
        ("#!foo", "foo", False),
        ("/foo", "foo", False),
        ("#foo(a, b)", "foo", True),
        ("#foo:bar", "foo", True),
        ("#foo+", "foo", True),
        ("#ns/foo", "ns/foo", False),
    ],
)
def test_normalize_show_name(
    raw: str,
    expected: str,
    stripped: bool,
) -> None:
    assert normalize_show_name(raw) == (expected, stripped)


def test_workflow_wins_over_shadowed_xprompt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sase.xprompt.cli_show_resolve as resolve_module

    workflow_path = tmp_path / "same.yml"
    workflow_path.write_text("steps:\n  - prompt_part: workflow body\n")
    xprompt_path = tmp_path / "same.md"
    xprompt_path.write_text("xprompt body\n")
    workflow = Workflow(
        name="same",
        source_path=str(workflow_path),
        steps=[WorkflowStep(name="body", prompt_part="workflow body")],
    )
    xprompt = XPrompt(
        name="same", content="xprompt body", source_path=str(xprompt_path)
    )
    _patch_catalog(
        monkeypatch,
        resolve_module,
        workflows={"same": workflow},
        xprompts={"same": xprompt},
    )

    record = resolve_show_record("same")

    assert isinstance(record, XPromptShowRecord)
    assert record.body == "workflow body"
    assert record.raw == workflow_path.read_text()
    assert any("shadows xprompt" in warning for warning in record.warnings)


def test_lookup_miss_suggests_copyable_reference_markers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sase.xprompt.cli_show_resolve as resolve_module

    workflows = {
        "sync": Workflow(
            name="sync",
            steps=[WorkflowStep(name="run", bash="true")],
        )
    }
    xprompts = {"reads": XPrompt(name="reads", content="read")}
    _patch_catalog(
        monkeypatch,
        resolve_module,
        workflows=workflows,
        xprompts=xprompts,
    )

    near = resolve_show_record("syn")
    far = resolve_show_record("zzzzzzzz")

    assert near == ShowLookupMiss("syn", ["#!sync"])
    assert far == ShowLookupMiss("zzzzzzzz", [])


def test_markdown_raw_and_body_line_are_exact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sase.xprompt.cli_show_resolve as resolve_module

    path = tmp_path / "article.md"
    raw = "---\ndescription: Read it\n---\nbody line\n"
    path.write_bytes(raw.encode())
    xprompt = XPrompt(
        name="article",
        content="body line\n",
        source_path=str(path),
        description="Read it",
    )
    _patch_catalog(
        monkeypatch,
        resolve_module,
        xprompts={"article": xprompt},
    )

    record = resolve_show_record("article")

    assert isinstance(record, XPromptShowRecord)
    assert record.raw == raw
    assert record.body_first_line == 4


def test_config_raw_is_exact_entry_span_with_crlf(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sase.xprompt.cli_show_resolve as resolve_module

    path = tmp_path / "sase.yml"
    raw = (
        "owner: test\r\n"
        "xprompts:\r\n"
        "  alpha: |-\r\n"
        "    first\r\n"
        "    second\r\n"
        "  beta: |-\r\n"
        "    neighbor\r\n"
    )
    path.write_bytes(raw.encode())
    xprompt = XPrompt(name="alpha", content="first\nsecond", source_path="config")
    _patch_catalog(
        monkeypatch,
        resolve_module,
        xprompts={"alpha": xprompt},
    )
    monkeypatch.setattr(
        resolve_module,
        "catalog_definition_path",
        lambda _entry: str(path),
    )

    record = resolve_show_record("alpha")

    assert isinstance(record, XPromptShowRecord)
    assert record.raw == "  alpha: |-\r\n    first\r\n    second\r\n"
    assert record.provenance.definition_line == 3
    assert config_entry_line_span(path, "alpha") == (3, 5)


def test_unreadable_definition_degrades_to_warning(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sase.xprompt.cli_show_resolve as resolve_module

    path = tmp_path / "definition.md"
    path.mkdir()
    xprompt = XPrompt(name="broken", content="body", source_path=str(path))
    _patch_catalog(
        monkeypatch,
        resolve_module,
        xprompts={"broken": xprompt},
    )
    monkeypatch.setattr(
        resolve_module,
        "catalog_definition_path",
        lambda _entry: str(path),
    )

    record = resolve_show_record("broken")

    assert isinstance(record, XPromptShowRecord)
    assert record.raw is None
    assert record.raw_available is False
    assert any("raw definition unavailable" in warning for warning in record.warnings)


def test_hosted_resolver_failure_is_a_warning(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sase.xprompt.cli_show_resolve as resolve_module

    path = tmp_path / "hosted.md"
    path.write_text("body")
    xprompt = XPrompt(name="hosted", content="body", source_path=str(path))
    _patch_catalog(
        monkeypatch,
        resolve_module,
        xprompts={"hosted": xprompt},
    )

    def fail_hosted(**_kwargs: Any) -> str | None:
        raise RuntimeError("git exploded")

    monkeypatch.setattr(resolve_module, "_hosted_url_for_definition", fail_hosted)

    record = resolve_show_record("hosted")

    assert isinstance(record, XPromptShowRecord)
    assert record.provenance.hosted_url is None
    assert "hosted URL unavailable: git exploded" in record.warnings


def test_references_are_resolved_and_deduplicated_in_document_order(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sase.xprompt.cli_show_resolve as resolve_module

    path = tmp_path / "refs.md"
    path.write_text("#_helper #nope #_helper")
    helper = XPrompt(name="_helper", content="help", source_path=str(path))
    xprompt = XPrompt(
        name="refs",
        content="#_helper #nope #_helper",
        source_path=str(path),
        local_xprompts={"_helper": helper},
    )
    _patch_catalog(
        monkeypatch,
        resolve_module,
        xprompts={"refs": xprompt},
    )
    scanned = [
        SimpleNamespace(
            raw_ref="#_helper",
            name="_helper",
            kind="part",
            item=helper,
        ),
        SimpleNamespace(raw_ref="#nope", name="nope", kind=None, item=None),
        SimpleNamespace(
            raw_ref="#_helper",
            name="_helper",
            kind="part",
            item=helper,
        ),
    ]
    monkeypatch.setattr(
        resolve_module,
        "scan_xprompt_references",
        lambda *_args, **_kwargs: scanned,
    )

    record = resolve_show_record("refs")

    assert isinstance(record, XPromptShowRecord)
    assert [(ref.raw_ref, ref.resolved) for ref in record.references] == [
        ("#_helper", True),
        ("#nope", False),
    ]
    assert record.references[0].kind == "local helper"


def test_record_json_projection_is_complete_and_serializable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sase.xprompt.cli_show_resolve as resolve_module

    path = tmp_path / "typed.md"
    path.write_text("body")
    xprompt = XPrompt(
        name="typed",
        content="body",
        source_path=str(path),
        inputs=[
            InputArg("required", InputType.WORD),
            InputArg("optional", InputType.TEXT, default=None),
        ],
    )
    _patch_catalog(
        monkeypatch,
        resolve_module,
        xprompts={"typed": xprompt},
    )

    record = resolve_show_record("typed")

    assert isinstance(record, XPromptShowRecord)
    projection = record.to_json_dict()
    assert projection["schema_version"] == SHOW_SCHEMA_VERSION
    assert projection["raw_available"] is True
    assert projection["inputs"][1]["default_display"] == "null"
    assert set(projection) == {
        "schema_version",
        "name",
        "reference",
        "prefix",
        "kind",
        "is_skill",
        "skill_name",
        "ref_kind",
        "ref_sidecar_role",
        "ref_path_globs",
        "ref_shadowed_sources",
        "is_swarm",
        "segment_count",
        "description",
        "project",
        "provenance",
        "tags",
        "skill",
        "snippet",
        "log_skill_use",
        "input_signature",
        "inputs",
        "local_xprompts",
        "steps",
        "body",
        "body_first_line",
        "raw",
        "warnings",
        "references",
        "memory_type",
        "raw_available",
    }
    json.loads(json.dumps(projection))


def test_memory_record_projects_kind_and_type(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sase.xprompt.cli_show_resolve as resolve_module

    path = tmp_path / "glossary.md"
    path.write_text("---\ntype: long\n---\nbody\n")
    xprompt = XPrompt(
        name="memory/glossary",
        content="body\n",
        source_path=str(path),
        description="Glossary terms.",
        memory_type="long",
    )
    _patch_catalog(
        monkeypatch,
        resolve_module,
        xprompts={"memory/glossary": xprompt},
    )

    record = resolve_show_record("#memory/glossary")

    assert isinstance(record, XPromptShowRecord)
    assert record.reference == "#memory/glossary"
    assert record.kind == "memory"
    assert record.memory_type == "long"
    projection = record.to_json_dict()
    assert projection["kind"] == "memory"
    assert projection["memory_type"] == "long"


def test_step_record_reuses_shared_type_and_output_schema(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sase.xprompt.cli_show_resolve as resolve_module

    path = tmp_path / "flow.yml"
    path.write_text("steps:\n  - python: print('ok')\n")
    workflow = Workflow(
        name="flow",
        source_path=str(path),
        steps=[
            WorkflowStep(
                name="compute",
                python="print('ok')",
                hidden=True,
                condition="ready",
                output=OutputSpec("json_schema", {"type": "object"}),
            )
        ],
    )
    _patch_catalog(
        monkeypatch,
        resolve_module,
        workflows={"flow": workflow},
    )

    record = resolve_show_record("flow")

    assert isinstance(record, XPromptShowRecord)
    assert record.steps[0].type == "python"
    assert record.steps[0].label == "print('ok')"
    assert record.steps[0].hidden is True
    assert record.steps[0].output_schema == {"type": "object"}
    assert record.steps[0].body == "print('ok')"


def test_public_definition_helpers(tmp_path: Path) -> None:
    path = tmp_path / "config.yml"
    path.write_text("xprompts:\n  item: value\n")

    assert definition_file_for_source(str(path)) == path.resolve()
    assert definition_line_for(path, "item") == 2


@pytest.mark.parametrize(
    ("source", "bucket", "display"),
    [
        ("default_config", "config", "sase default_config.yml"),
        ("config", "config", "~/.config/sase/sase.yml"),
        ("config_overlay:sase_work.yml", "config", "~/.config/sase/sase_work.yml"),
        ("plugin:demo/prompts.md", "plugin", "plugin:demo/prompts.md"),
        ("plugin_config:demo", "plugin", "plugin_config:demo"),
    ],
)
def test_source_id_classification_and_display(
    source: str,
    bucket: str,
    display: str,
) -> None:
    entry = classify(XPrompt(name="item", content="", source_path=source), None)

    assert entry.bucket == bucket
    assert source_path_display(entry) == display


def test_explicit_project_classifies_unregistered_definition_as_project(
    tmp_path: Path,
) -> None:
    path = tmp_path / "project.md"
    path.write_text("body")

    entry = classify(
        XPrompt(name="demo/item", content="body", source_path=str(path)),
        "demo",
    )

    assert entry.bucket == "project"
    assert entry.project == "demo"


def _patch_catalog(
    monkeypatch: pytest.MonkeyPatch,
    resolve_module: Any,
    *,
    workflows: dict[str, Workflow] | None = None,
    xprompts: dict[str, XPrompt] | None = None,
) -> None:
    monkeypatch.setattr(
        resolve_module,
        "get_all_workflows",
        lambda *, project=None: workflows or {},
    )
    monkeypatch.setattr(
        resolve_module,
        "get_all_xprompts",
        lambda *, project=None: xprompts or {},
    )
    monkeypatch.setattr(
        resolve_module,
        "_hosted_url_for_definition",
        lambda **_kwargs: None,
    )
    monkeypatch.setattr(
        resolve_module,
        "scan_xprompt_references",
        lambda *_args, **_kwargs: [],
    )
