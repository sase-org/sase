from __future__ import annotations

import argparse
import io
import json
from pathlib import Path

import pytest

from sase.integrations.editor_helpers import handle_editor_helper_bridge
from sase.main.parser import create_parser
from sase.xprompt.catalog import (
    StructuredCatalogEntry,
    StructuredCatalogProjection,
    StructuredCatalogStats,
)
from sase.xprompt.models import XPrompt


def test_parser_accepts_editor_helper_bridge_xprompt_catalog() -> None:
    args = create_parser().parse_args(["editor", "helper-bridge", "xprompt-catalog"])

    assert args.command == "editor"
    assert args.editor_subcommand == "helper-bridge"
    assert args.editor_helper_bridge_subcommand == "xprompt-catalog"


def test_editor_helper_bridge_aliases_xprompt_catalog(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.integrations.mobile_helpers.build_structured_xprompts_catalog",
        lambda **_kwargs: StructuredCatalogProjection(
            entries=[
                StructuredCatalogEntry(
                    name="edit",
                    display_label="edit",
                    insertion="#edit",
                    reference_prefix="#",
                    kind="xprompt",
                    description="Editor helper prompt",
                    source_bucket="project",
                    project="sase",
                    tags=["editor"],
                    input_signature=None,
                    inputs=[],
                    is_skill=False,
                    content_preview="Prompt preview",
                    source_path_display="xprompts/edit.md",
                )
            ],
            stats=StructuredCatalogStats(
                total_count=1,
                project_count=1,
                skill_count=0,
                pdf_requested=False,
            ),
            warnings=[],
            skipped=[],
            catalog_attachment=None,
        ),
    )
    stdout = io.StringIO()
    stderr = io.StringIO()

    code = handle_editor_helper_bridge(
        argparse.Namespace(editor_helper_bridge_subcommand="xprompt-catalog"),
        stdin=io.StringIO(json.dumps({"schema_version": 1, "project": "sase"})),
        stdout=stdout,
        stderr=stderr,
    )

    data = json.loads(stdout.getvalue())
    assert code == 0
    assert stderr.getvalue() == ""
    assert data["context"] == {"project": "sase", "scope": "explicit"}
    assert data["entries"][0]["name"] == "edit"


def test_editor_helper_bridge_outputs_definition_path_for_real_catalog_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "workspace" / ".xprompts" / "jump.md"
    source.parent.mkdir(parents=True)
    source.write_text("Jump target", encoding="utf-8")
    xprompt = XPrompt(
        name="jump",
        content="Jump target",
        source_path=str(source),
    )

    monkeypatch.setattr(
        "sase.xprompt.catalog.get_all_xprompts", lambda: {"jump": xprompt}
    )
    monkeypatch.setattr("sase.xprompt.catalog.get_all_workflows", lambda: {})
    monkeypatch.setattr("sase.xprompt.catalog.get_known_project_workspaces", lambda: {})
    monkeypatch.setattr(
        "sase.xprompt.catalog.load_project_local_xprompts",
        lambda _workspace, _project: {},
    )
    monkeypatch.setattr(
        "sase.xprompt.catalog.get_sase_package_xprompts_dir",
        lambda: tmp_path / "package_xprompts",
    )
    monkeypatch.setattr(
        "sase.xprompt.catalog.get_sase_package_default_xprompts_dir",
        lambda: tmp_path / "default_xprompts",
    )

    stdout = io.StringIO()
    stderr = io.StringIO()

    code = handle_editor_helper_bridge(
        argparse.Namespace(editor_helper_bridge_subcommand="xprompt-catalog"),
        stdin=io.StringIO(json.dumps({"schema_version": 1, "query": "jump"})),
        stdout=stdout,
        stderr=stderr,
    )

    data = json.loads(stdout.getvalue())
    assert code == 0
    assert stderr.getvalue() == ""
    assert data["entries"][0]["name"] == "jump"
    assert data["entries"][0]["definition_path"] == str(source.resolve())
