from __future__ import annotations

import argparse
import io
import json
from pathlib import Path

import pytest

from sase.integrations.editor_helpers import handle_editor_helper_bridge
from sase.main.parser import create_parser
from sase.xprompt.models import UNSET, InputArg, XPrompt
from sase.xprompt.catalog import (
    StructuredCatalogEntry,
    StructuredCatalogProjection,
    StructuredCatalogStats,
)


def test_parser_accepts_editor_helper_bridge_xprompt_catalog() -> None:
    args = create_parser().parse_args(["editor", "helper-bridge", "xprompt-catalog"])

    assert args.command == "editor"
    assert args.editor_subcommand == "helper-bridge"
    assert args.editor_helper_bridge_subcommand == "xprompt-catalog"


def test_parser_accepts_editor_helper_bridge_snippet_catalog() -> None:
    args = create_parser().parse_args(["editor", "helper-bridge", "snippet-catalog"])

    assert args.command == "editor"
    assert args.editor_subcommand == "helper-bridge"
    assert args.editor_helper_bridge_subcommand == "snippet-catalog"


def test_parser_accepts_editor_helper_bridge_vcs_repo_catalog() -> None:
    args = create_parser().parse_args(["editor", "helper-bridge", "vcs-repo-catalog"])

    assert args.command == "editor"
    assert args.editor_subcommand == "helper-bridge"
    assert args.editor_helper_bridge_subcommand == "vcs-repo-catalog"


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


def test_editor_helper_bridge_vcs_repo_catalog_round_trip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.integrations.editor_helpers.vcs_repo_catalog_response",
        lambda request: {
            "schema_version": 1,
            "status": "ok",
            "error_kind": None,
            "message": "",
            "provider_display": "GitHub",
            "stale": False,
            "entries": [
                {
                    "name": "sase",
                    "ref": "bbugyi200/sase",
                    "description": "",
                    "visibility": "PUBLIC",
                    "is_fork": False,
                    "is_archived": False,
                    "pushed_at": None,
                }
            ],
            "request_echo": request,
        },
    )
    stdout = io.StringIO()
    stderr = io.StringIO()

    code = handle_editor_helper_bridge(
        argparse.Namespace(editor_helper_bridge_subcommand="vcs-repo-catalog"),
        stdin=io.StringIO(
            json.dumps(
                {
                    "schema_version": 1,
                    "workflow": "gh",
                    "namespace": "bbugyi200",
                }
            )
        ),
        stdout=stdout,
        stderr=stderr,
    )

    data = json.loads(stdout.getvalue())
    assert code == 0
    assert stderr.getvalue() == ""
    assert data["request_echo"] == {
        "schema_version": 1,
        "workflow": "gh",
        "namespace": "bbugyi200",
    }
    assert data["entries"][0]["ref"] == "bbugyi200/sase"


def test_editor_helper_bridge_vcs_repo_catalog_reports_bad_request() -> None:
    stdout = io.StringIO()
    stderr = io.StringIO()

    code = handle_editor_helper_bridge(
        argparse.Namespace(editor_helper_bridge_subcommand="vcs-repo-catalog"),
        stdin=io.StringIO(
            json.dumps(
                {
                    "schema_version": 1,
                    "namespace": "bbugyi200",
                }
            )
        ),
        stdout=stdout,
        stderr=stderr,
    )

    assert code == 2
    assert stdout.getvalue() == ""
    assert stderr.getvalue().startswith("editor helper bridge error:")


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


def test_editor_helper_bridge_snippet_catalog_merges_xprompt_and_user_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    xprompts = {
        "helper": XPrompt(
            name="helper",
            content="Help with {{ topic }}",
            inputs=[InputArg(name="topic", default=UNSET)],
            source_path="xprompts/helper.md",
            snippet=True,
            description="Helper prompt",
        )
    }
    monkeypatch.setattr(
        "sase.xprompt.loader.get_all_xprompts",
        lambda project=None: xprompts,
    )
    monkeypatch.setattr(
        "sase.integrations._editor_helper_snippets.load_merged_config",
        lambda: {"ace": {"snippets": {"user_snip": "User $1$0"}}},
    )

    stdout = io.StringIO()
    stderr = io.StringIO()
    code = handle_editor_helper_bridge(
        argparse.Namespace(editor_helper_bridge_subcommand="snippet-catalog"),
        stdin=io.StringIO(json.dumps({"schema_version": 1, "project": "sase"})),
        stdout=stdout,
        stderr=stderr,
    )

    data = json.loads(stdout.getvalue())
    entries = {entry["trigger"]: entry for entry in data["entries"]}
    assert code == 0
    assert stderr.getvalue() == ""
    assert data["context"] == {"project": "sase", "scope": "explicit"}
    assert data["stats"] == {"total_count": 2}
    assert entries["helper"] == {
        "trigger": "helper",
        "template": "Help with $1$0",
        "source": "xprompt",
        "xprompt_name": "helper",
        "description": "Helper prompt",
        "source_path_display": "xprompts/helper.md",
    }
    assert entries["user_snip"] == {
        "trigger": "user_snip",
        "template": "User $1$0",
        "source": "user_config",
        "xprompt_name": None,
        "description": None,
        "source_path_display": "ace.snippets",
    }


def test_editor_helper_bridge_snippet_catalog_user_overrides_xprompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    xprompts = {
        "shared": XPrompt(
            name="shared",
            content="from xprompt",
            source_path="xprompts/shared.md",
            snippet=True,
        )
    }
    monkeypatch.setattr(
        "sase.xprompt.loader.get_all_xprompts",
        lambda project=None: xprompts,
    )
    monkeypatch.setattr(
        "sase.integrations._editor_helper_snippets.load_merged_config",
        lambda: {"ace": {"snippets": {"shared": "from user", "bad-trigger": "no"}}},
    )

    stdout = io.StringIO()
    stderr = io.StringIO()
    code = handle_editor_helper_bridge(
        argparse.Namespace(editor_helper_bridge_subcommand="snippet-catalog"),
        stdin=io.StringIO(json.dumps({"schema_version": 1})),
        stdout=stdout,
        stderr=stderr,
    )

    data = json.loads(stdout.getvalue())
    entries = {entry["trigger"]: entry for entry in data["entries"]}
    assert code == 0
    assert stderr.getvalue() == ""
    assert list(entries) == ["shared"]
    assert entries["shared"]["template"] == "from user"
    assert entries["shared"]["source"] == "user_config"


def test_editor_helper_bridge_snippet_catalog_composes_nested_xprompts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    xprompts = {
        "leaf": XPrompt(name="leaf", content="leaf text", snippet=None),
        "outer": XPrompt(name="outer", content="outer #leaf", snippet=True),
    }
    monkeypatch.setattr(
        "sase.xprompt.loader.get_all_xprompts",
        lambda project=None: xprompts,
    )
    monkeypatch.setattr(
        "sase.integrations._editor_helper_snippets.load_merged_config",
        lambda: {},
    )

    stdout = io.StringIO()
    stderr = io.StringIO()
    code = handle_editor_helper_bridge(
        argparse.Namespace(editor_helper_bridge_subcommand="snippet-catalog"),
        stdin=io.StringIO(json.dumps({"schema_version": 1})),
        stdout=stdout,
        stderr=stderr,
    )

    data = json.loads(stdout.getvalue())
    assert code == 0
    assert stderr.getvalue() == ""
    assert data["entries"] == [
        {
            "trigger": "outer",
            "template": "outer leaf text$0",
            "source": "xprompt",
            "xprompt_name": "outer",
            "description": None,
            "source_path_display": None,
        }
    ]


def test_editor_helper_bridge_snippet_catalog_resolves_snippet_references(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    xprompts = {
        "helper": XPrompt(
            name="helper",
            content="Help {{ topic }}",
            inputs=[InputArg(name="topic", default=UNSET)],
            snippet=True,
        ),
        "outer": XPrompt(
            name="outer",
            content="#[user_snip] {{ topic }}",
            inputs=[InputArg(name="topic", default=UNSET)],
            snippet=True,
        ),
    }
    monkeypatch.setattr(
        "sase.xprompt.loader.get_all_xprompts",
        lambda project=None: xprompts,
    )
    monkeypatch.setattr(
        "sase.integrations._editor_helper_snippets.load_merged_config",
        lambda: {
            "ace": {
                "snippets": {"user_snip": "User $1$0", "wrap": "#[helper(World)] $1$0"}
            }
        },
    )

    stdout = io.StringIO()
    stderr = io.StringIO()
    code = handle_editor_helper_bridge(
        argparse.Namespace(editor_helper_bridge_subcommand="snippet-catalog"),
        stdin=io.StringIO(json.dumps({"schema_version": 1})),
        stdout=stdout,
        stderr=stderr,
    )

    data = json.loads(stdout.getvalue())
    entries = {entry["trigger"]: entry for entry in data["entries"]}
    assert code == 0
    assert stderr.getvalue() == ""
    assert entries["outer"]["template"] == "User $1 $2$0"
    assert entries["wrap"]["template"] == "Help World $1$0"


def test_parser_accepts_editor_helper_bridge_agent_catalog() -> None:
    args = create_parser().parse_args(["editor", "helper-bridge", "agent-catalog"])

    assert args.command == "editor"
    assert args.editor_subcommand == "helper-bridge"
    assert args.editor_helper_bridge_subcommand == "agent-catalog"


def test_editor_helper_bridge_agent_catalog_is_fresh_and_deduplicated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.agent.running_listing import RunningAgentInfo

    calls = 0

    def list_agents() -> list[RunningAgentInfo]:
        nonlocal calls
        calls += 1
        return [
            RunningAgentInfo(
                name="planner",
                project="sase",
                pid=1,
                model=None,
                provider=None,
                workspace_num=14,
                duration="1m",
                approve=False,
                status="RUNNING",
            ),
            RunningAgentInfo(
                name="planner",
                project="sase-old",
                pid=None,
                model=None,
                provider=None,
                workspace_num=None,
                duration="2m",
                approve=False,
                status="DONE",
            ),
            RunningAgentInfo(
                name="coder",
                project="core",
                pid=None,
                model=None,
                provider=None,
                workspace_num=None,
                duration="2m",
                approve=False,
                status="DONE",
            ),
        ]

    monkeypatch.setattr("sase.agent.running_listing.list_all_agents", list_agents)

    for _ in range(2):
        stdout = io.StringIO()
        stderr = io.StringIO()
        code = handle_editor_helper_bridge(
            argparse.Namespace(editor_helper_bridge_subcommand="agent-catalog"),
            stdin=io.StringIO(json.dumps({"schema_version": 1})),
            stdout=stdout,
            stderr=stderr,
        )

        assert code == 0
        assert stderr.getvalue() == ""
        assert json.loads(stdout.getvalue())["entries"] == [
            {"name": "planner", "status": "RUNNING", "project": "sase"},
            {"name": "coder", "status": "DONE", "project": "core"},
        ]

    assert calls == 2
