from __future__ import annotations

import argparse
import io
import json
from pathlib import Path

import pytest

from sase.integrations.editor_helpers import handle_editor_helper_bridge


@pytest.fixture(autouse=True)
def _empty_editor_helper_bead_catalog(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep helper-bridge tests off the live bead stores unless they opt in."""
    monkeypatch.setattr(
        "sase.xprompt.project_identity.get_known_project_workspaces",
        lambda: {},
    )


def test_editor_helper_bridge_agent_catalog_includes_bounded_bead_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.agent.running_listing import RunningAgentInfo
    from sase.bead.model import Issue, IssueType, Status

    monkeypatch.setattr(
        "sase.agent.running_listing.list_all_agents",
        lambda: [
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
            )
        ],
    )
    monkeypatch.setattr(
        "sase.xprompt.project_identity.get_known_project_workspaces",
        lambda: {"sase": Path("/tmp/sase"), "other": Path("/tmp/other")},
    )

    def open_beads(project: str) -> tuple[Issue, ...] | None:
        if project != "sase":
            return ()
        return (
            Issue(
                id="sase-b",
                title="Ready work",
                status=Status.READY,
                issue_type=IssueType.TASK,
                created_at="2026-08-01T00:00:00Z",
                updated_at="2026-08-21T12:00:00Z",
            ),
            Issue(
                id="sase-a",
                title="Active bug",
                status=Status.IN_PROGRESS,
                issue_type=IssueType.TASK,
                created_at="2026-08-01T00:00:00Z",
                updated_at="2026-08-20T12:00:00Z",
                task_type="bug",
            ),
        )

    monkeypatch.setattr(
        "sase.bead.store_locator.open_bead_candidates_for_project",
        open_beads,
    )
    monkeypatch.setattr(
        "sase.project_display_names.project_display_name_for",
        lambda key, *args, **kwargs: "sase" if key == "sase" else key,
    )

    stdout = io.StringIO()
    code = handle_editor_helper_bridge(
        argparse.Namespace(editor_helper_bridge_subcommand="agent-catalog"),
        stdin=io.StringIO(json.dumps({"schema_version": 1, "project": "sase"})),
        stdout=stdout,
        stderr=io.StringIO(),
    )

    assert code == 0
    data = json.loads(stdout.getvalue())
    assert [entry["name"] for entry in data["entries"]] == ["planner"]
    assert [row["id"] for row in data["beads"]] == ["sase-a", "sase-b"]
    assert data["beads"][0]["title"] == "Active bug"
    assert data["beads"][0]["status"] == "in_progress"
    assert data["beads"][0]["task_type"] == "bug"
    assert data["beads"][0]["project"] == "sase"


def test_editor_helper_bridge_agent_catalog_omits_beads_on_store_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.agent.running_listing import RunningAgentInfo

    monkeypatch.setattr(
        "sase.agent.running_listing.list_all_agents",
        lambda: [
            RunningAgentInfo(
                name="planner",
                project="sase",
                pid=None,
                model=None,
                provider=None,
                workspace_num=None,
                duration="1m",
                approve=False,
                status="RUNNING",
            )
        ],
    )
    monkeypatch.setattr(
        "sase.xprompt.project_identity.get_known_project_workspaces",
        lambda: (_ for _ in ()).throw(RuntimeError("no projects")),
    )
    monkeypatch.setattr(
        "sase.bead.store_locator.open_bead_candidates_for_project",
        lambda project: (_ for _ in ()).throw(RuntimeError("store down")),
    )

    stdout = io.StringIO()
    code = handle_editor_helper_bridge(
        argparse.Namespace(editor_helper_bridge_subcommand="agent-catalog"),
        stdin=io.StringIO(
            json.dumps({"schema_version": 1, "unknown_future_field": True})
        ),
        stdout=stdout,
        stderr=io.StringIO(),
    )

    assert code == 0
    data = json.loads(stdout.getvalue())
    assert [entry["name"] for entry in data["entries"]] == ["planner"]
    assert "beads" not in data
