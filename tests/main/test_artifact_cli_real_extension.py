"""Smoke and e2e tests for ``sase artifact`` against the Rust extension."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.core.rust import RUST_EXTENSION_MODULE_NAME

from tests.main.artifact_cli_helpers import run_entry


def test_artifact_cli_real_extension_temp_index_e2e(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    rust_module = pytest.importorskip(RUST_EXTENSION_MODULE_NAME)
    required = {
        "artifact_add",
        "artifact_remove",
        "artifact_list",
        "artifact_search",
        "artifact_show",
        "artifact_graph",
        "artifact_doctor",
    }
    missing = sorted(name for name in required if not hasattr(rust_module, name))
    if missing:
        pytest.skip(f"sase_core_rs is too old: missing {missing}")

    index_path = tmp_path / "artifacts.sqlite"

    code, output, error = run_entry(
        monkeypatch,
        capsys,
        "artifact",
        "add",
        "-j",
        "-i",
        str(index_path),
        "-a",
        "doc:parent",
        "-k",
        "note",
        "-t",
        "Parent note",
        "-q",
        "parent note",
        "-l",
        "parent|doc:parent|/",
    )
    assert (code, error) == (0, "")
    assert json.loads(output)["affected_node_ids"] == ["doc:parent"]

    code, output, error = run_entry(
        monkeypatch,
        capsys,
        "artifact",
        "add",
        "-j",
        "-i",
        str(index_path),
        "-a",
        "doc:child",
        "-k",
        "note",
        "-t",
        "Child note",
        "-q",
        "child note",
        "-P",
        "summary",
        "-p",
        '{"body": "child payload"}',
        "-l",
        "parent|doc:child|doc:parent",
    )
    add_payload = json.loads(output)
    assert (code, error) == (0, "")
    assert add_payload["affected_node_ids"] == ["doc:child"]
    assert add_payload["nodes_added"] == 1
    assert add_payload["links_added"] == 1

    code, output, error = run_entry(
        monkeypatch,
        capsys,
        "artifact",
        "list",
        "-j",
        "-i",
        str(index_path),
        "-q",
        "child",
        "-l",
        "10",
    )
    listed = json.loads(output)
    assert (code, error) == (0, "")
    assert [node["id"] for node in listed] == ["doc:child"]

    code, output, error = run_entry(
        monkeypatch,
        capsys,
        "artifact",
        "search",
        "-j",
        "-i",
        str(index_path),
        "-q",
        "child",
        "-l",
        "10",
    )
    searched = json.loads(output)
    assert (code, error) == (0, "")
    assert [node["id"] for node in searched] == ["doc:child"]

    code, output, error = run_entry(
        monkeypatch,
        capsys,
        "artifact",
        "show",
        "-j",
        "-i",
        str(index_path),
        "-a",
        "doc:child",
    )
    detail = json.loads(output)
    assert (code, error) == (0, "")
    assert detail["node"]["display_title"] == "Child note"
    assert detail["payloads"][0]["payload"] == {"body": "child payload"}
    assert [node["id"] for node in detail["path_to_root"]] == [
        "doc:child",
        "doc:parent",
        "/",
    ]

    code, output, error = run_entry(
        monkeypatch,
        capsys,
        "artifact",
        "graph",
        "-f",
        "text",
        "-i",
        str(index_path),
        "-a",
        "doc:parent",
        "-d",
        "2",
        "-I",
        "-l",
        "20",
    )
    assert (code, error) == (0, "")
    assert "doc:child -[parent]-> doc:parent" in output
    assert "truncated: false" in output

    code, output, error = run_entry(
        monkeypatch,
        capsys,
        "artifact",
        "doctor",
        "-j",
        "-i",
        str(index_path),
    )
    assert (code, error) == (0, "")
    assert json.loads(output)["ok"] is True

    code, output, error = run_entry(
        monkeypatch,
        capsys,
        "artifact",
        "remove",
        "-j",
        "-i",
        str(index_path),
        "-T",
        "parent",
        "-S",
        "doc:child",
        "-D",
        "doc:parent",
        "-p",
        "manual",
        "-r",
        "integration test cleanup",
    )
    removed_link = json.loads(output)
    assert (code, error) == (0, "")
    assert removed_link["links_removed"] + removed_link["tombstones_added"] >= 1

    code, output, error = run_entry(
        monkeypatch,
        capsys,
        "artifact",
        "remove",
        "-j",
        "-i",
        str(index_path),
        "-a",
        "doc:child",
        "-p",
        "manual",
        "-r",
        "integration test cleanup",
    )
    removed_node = json.loads(output)
    assert (code, error) == (0, "")
    assert removed_node["affected_node_ids"] == ["doc:child"]


def test_artifact_cli_real_extension_migration_fixture_smoke(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    rust_module = pytest.importorskip(RUST_EXTENSION_MODULE_NAME)
    required = {
        "artifact_rebuild",
        "artifact_list",
        "artifact_search",
        "artifact_show",
        "artifact_graph",
        "artifact_doctor",
    }
    missing = sorted(name for name in required if not hasattr(rust_module, name))
    if missing:
        pytest.skip(f"sase_core_rs is too old: missing {missing}")

    index_path = tmp_path / "artifacts.sqlite"
    projects_root = tmp_path / "projects"
    project_dir = projects_root / "acme"
    project_file = project_dir / "acme.gp"
    workspace_root = tmp_path / "workspace"
    beads_dir = workspace_root / "sdd" / "beads"
    artifact_dir = project_dir / "artifacts" / "ace-run" / "20260505120000"
    response_path = artifact_dir / "response.md"

    project_dir.mkdir(parents=True)
    beads_dir.mkdir(parents=True)
    artifact_dir.mkdir(parents=True)
    project_file.write_text(
        "NAME: cl-one\n"
        "DESCRIPTION: Build the artifact graph migration.\n"
        "STATUS: WIP\n"
        "COMMITS:\n"
        "  (1) Initial note\n",
        encoding="utf-8",
    )
    response_path.write_text("migration response\n", encoding="utf-8")
    (artifact_dir / "agent_meta.json").write_text(
        json.dumps(
            {
                "name": "agent-alpha",
                "artifact_agent_id": "agent-alpha",
                "changespec_name": "cl-one",
                "llm_provider": "codex",
                "phase_bead_id": "sase-10.1",
            }
        ),
        encoding="utf-8",
    )
    (artifact_dir / "done.json").write_text(
        json.dumps(
            {
                "name": "agent-alpha",
                "cl_name": "cl-one",
                "response_path": str(response_path),
            }
        ),
        encoding="utf-8",
    )
    (artifact_dir / "codex_thinking.jsonl").write_text(
        json.dumps(
            {
                "text": "verify migrated graph relationships",
                "timestamp": "2026-05-05T12:00:00Z",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (beads_dir / "issues.jsonl").write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "id": "sase-10",
                        "title": "Epic",
                        "status": "open",
                        "issue_type": "plan",
                        "tier": "epic",
                        "owner": "owner@example.com",
                        "assignee": "",
                        "created_at": "2026-05-05T00:00:00Z",
                        "created_by": "owner@example.com",
                        "updated_at": "2026-05-05T00:00:00Z",
                        "description": "",
                        "notes": "",
                        "design": "",
                        "is_ready_to_work": True,
                        "changespec_name": "cl-one",
                        "dependencies": [],
                    }
                ),
                json.dumps(
                    {
                        "id": "sase-10.1",
                        "title": "Phase",
                        "status": "in_progress",
                        "issue_type": "phase",
                        "parent_id": "sase-10",
                        "owner": "owner@example.com",
                        "assignee": "agent-alpha",
                        "created_at": "2026-05-05T00:00:00Z",
                        "created_by": "owner@example.com",
                        "updated_at": "2026-05-05T00:00:00Z",
                        "description": "",
                        "notes": "",
                        "design": "",
                        "is_ready_to_work": False,
                        "dependencies": [],
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    code, output, error = run_entry(
        monkeypatch,
        capsys,
        "artifact",
        "rebuild",
        "-j",
        "-i",
        str(index_path),
        "-p",
        str(projects_root),
        "-w",
        str(workspace_root),
        "-b",
        str(beads_dir),
    )
    rebuild = json.loads(output)
    assert (code, error) == (0, "")
    assert rebuild["errors"] == []
    assert rebuild["nodes_added"] > 0
    assert rebuild["links_added"] > 0

    code, output, error = run_entry(
        monkeypatch,
        capsys,
        "artifact",
        "doctor",
        "-j",
        "-i",
        str(index_path),
    )
    assert (code, error) == (0, "")
    assert json.loads(output)["ok"] is True

    code, output, error = run_entry(
        monkeypatch,
        capsys,
        "artifact",
        "list",
        "-j",
        "-i",
        str(index_path),
        "-k",
        "thought",
        "-l",
        "5",
    )
    thoughts = json.loads(output)
    assert (code, error) == (0, "")
    assert len(thoughts) == 1
    assert thoughts[0]["id"].startswith("thought:")

    code, output, error = run_entry(
        monkeypatch,
        capsys,
        "artifact",
        "show",
        "-j",
        "-i",
        str(index_path),
        "-a",
        "agent-alpha",
    )
    agent = json.loads(output)
    assert (code, error) == (0, "")
    assert agent["node"]["kind"] == "agent"
    assert agent["node"]["metadata"]["source_artifact_dir"] == str(artifact_dir)
    assert any(
        link["link_type"] == "related"
        and link["source_id"] == "agent-alpha"
        and link["target_id"] == "cl-one"
        for link in agent["outbound_links"]
    )
    assert any(
        link["link_type"] == "created" and link["target_id"] == str(response_path)
        for link in agent["outbound_links"]
    )
    assert any(
        link["link_type"] == "created" and link["target_id"].startswith("thought:")
        for link in agent["outbound_links"]
    )

    code, output, error = run_entry(
        monkeypatch,
        capsys,
        "artifact",
        "show",
        "-j",
        "-i",
        str(index_path),
        "-a",
        "sase-10.1",
    )
    phase = json.loads(output)
    assert (code, error) == (0, "")
    assert any(
        link["link_type"] == "worker"
        and link["source_id"] == "sase-10.1"
        and link["target_id"] == "agent-alpha"
        for link in phase["outbound_links"]
    )

    code, output, error = run_entry(
        monkeypatch,
        capsys,
        "artifact",
        "graph",
        "-j",
        "-i",
        str(index_path),
        "-a",
        "cl-one",
        "-d",
        "1",
        "-I",
        "-l",
        "50",
    )
    graph = json.loads(output)
    graph_ids = {node["id"] for node in graph["nodes"]}
    assert (code, error) == (0, "")
    assert {"cl-one", "cl-one:1", "agent-alpha", "sase-10"} <= graph_ids
