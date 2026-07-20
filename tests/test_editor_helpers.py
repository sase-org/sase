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
            {
                "name": "planner",
                "status": "RUNNING",
                "project": "sase",
                "kind": "agent",
                "member_count": 1,
                "detail": "RUNNING · sase",
            },
            {
                "name": "coder",
                "status": "DONE",
                "project": "core",
                "kind": "agent",
                "member_count": 1,
                "detail": "DONE · core",
            },
        ]

    assert calls == 2


def test_editor_helper_bridge_agent_catalog_derives_groups_from_one_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.agent.running_listing import RunningAgentInfo, _RunningAgentListing
    from sase.core.agent_scan_wire import (
        AGENT_SCAN_WIRE_SCHEMA_VERSION,
        AgentArtifactRecordWire,
        AgentArtifactScanOptionsWire,
        AgentArtifactScanStatsWire,
        AgentArtifactScanWire,
        AgentClanContextWire,
        AgentMetaWire,
        DoneMarkerWire,
    )

    def record(
        timestamp: str,
        name: str | None,
        **meta_values: object,
    ) -> AgentArtifactRecordWire:
        artifact_dir = f"/tmp/artifacts/{timestamp}"
        return AgentArtifactRecordWire(
            project_name="sase",
            project_dir="/tmp/sase",
            project_file="/tmp/sase/sase.sase",
            workflow_dir_name="ace-run",
            artifact_dir=artifact_dir,
            timestamp=timestamp,
            agent_meta=(
                AgentMetaWire(name=name, cl_name="change", **meta_values)
                if name is not None
                else None
            ),
            done=DoneMarkerWire(outcome="completed", cl_name="change"),
            has_done_marker=True,
        )

    records = [
        record(
            "20260719010101",
            "old.one",
            agent_clan="squad",
            agent_clan_generation="g1",
        ),
        record(
            "20260719020101",
            "squad.alpha",
            agent_clan="squad",
            agent_clan_generation="g2",
        ),
        record(
            "20260719020102",
            "squad.beta",
            agent_clan="squad",
            agent_clan_generation="g2",
        ),
        record(
            "20260719030101",
            "review--plan",
            agent_family="review",
        ),
        record(
            "20260719030102",
            "review--code",
            agent_family="review",
            parent_timestamp="20260719030101",
        ),
        record("20260719040101", "solo", tribe="writers"),
        record("20260719050101", None),
    ]
    snapshot = AgentArtifactScanWire(
        schema_version=AGENT_SCAN_WIRE_SCHEMA_VERSION,
        projects_root="/tmp/projects",
        options=AgentArtifactScanOptionsWire(),
        stats=AgentArtifactScanStatsWire(),
        records=records,
        clan_context=[
            AgentClanContextWire(
                agent_clan="squad",
                agent_clan_generation="g2",
                clan_tribe="builders",
                clan_tribe_source_launch_timestamp="20260719020000",
                clan_tribe_source_identity="/tmp/omitted-declarer",
            )
        ],
    )

    def info(record: AgentArtifactRecordWire, status: str) -> RunningAgentInfo:
        assert record.agent_meta is not None
        return RunningAgentInfo(
            name=record.agent_meta.name,
            project="sase",
            pid=None,
            model=None,
            provider=None,
            workspace_num=None,
            duration="1m",
            approve=False,
            status=status,
            artifacts_dir=record.artifact_dir,
        )

    listing = _RunningAgentListing(
        [
            info(records[1], "RUNNING"),
            info(records[2], "DONE"),
            info(records[3], "DONE"),
            info(records[4], "RUNNING"),
            info(records[5], "DONE"),
        ],
        artifact_snapshot=snapshot,
    )
    monkeypatch.setattr("sase.agent.running_listing.list_all_agents", lambda: listing)
    monkeypatch.setattr(
        "sase.core.agent_tribe.load_raw_agent_tribes",
        lambda: {("workflow", "change", "20260719020102"): "ops"},
    )

    stdout = io.StringIO()
    code = handle_editor_helper_bridge(
        argparse.Namespace(editor_helper_bridge_subcommand="agent-catalog"),
        stdin=io.StringIO(json.dumps({"schema_version": 1})),
        stdout=stdout,
        stderr=io.StringIO(),
    )

    assert code == 0
    data = json.loads(stdout.getvalue())
    by_target = {(entry["kind"], entry["name"]): entry for entry in data["entries"]}
    assert data["schema_version"] == 1
    assert by_target[("family", "review")]["member_count"] == 2
    assert by_target[("clan", "squad")] == {
        "name": "squad",
        "kind": "clan",
        "member_count": 2,
        "status": "RUNNING",
        "detail": "clan · 2 members · RUNNING",
    }
    assert by_target[("tribe", "@builders")]["detail"] == "tribe · 1 clan"
    assert by_target[("tribe", "@ops")]["detail"] == "tribe · 1 agent"
    assert by_target[("tribe", "@writers")]["detail"] == "tribe · 1 agent"


def test_editor_helper_bridge_agent_catalog_tolerates_group_derivation_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.agent.running_listing import RunningAgentInfo, _RunningAgentListing
    from sase.core.agent_scan_wire import (
        AGENT_SCAN_WIRE_SCHEMA_VERSION,
        AgentArtifactScanOptionsWire,
        AgentArtifactScanStatsWire,
        AgentArtifactScanWire,
    )

    snapshot = AgentArtifactScanWire(
        schema_version=AGENT_SCAN_WIRE_SCHEMA_VERSION,
        projects_root="/tmp/projects",
        options=AgentArtifactScanOptionsWire(),
        stats=AgentArtifactScanStatsWire(),
    )
    listing = _RunningAgentListing(
        [
            RunningAgentInfo(
                name="planner",
                project="sase",
                pid=None,
                model=None,
                provider=None,
                workspace_num=None,
                duration="1m",
                approve=False,
            )
        ],
        artifact_snapshot=snapshot,
    )
    monkeypatch.setattr("sase.agent.running_listing.list_all_agents", lambda: listing)
    monkeypatch.setattr(
        "sase.integrations._editor_helper_agents._derive_group_entries",
        lambda *_args: (_ for _ in ()).throw(ValueError("legacy metadata")),
    )

    stdout = io.StringIO()
    code = handle_editor_helper_bridge(
        argparse.Namespace(editor_helper_bridge_subcommand="agent-catalog"),
        stdin=io.StringIO(json.dumps({"schema_version": 1})),
        stdout=stdout,
        stderr=io.StringIO(),
    )

    assert code == 0
    entries = json.loads(stdout.getvalue())["entries"]
    assert [(entry["kind"], entry["name"]) for entry in entries] == [
        ("agent", "planner")
    ]
