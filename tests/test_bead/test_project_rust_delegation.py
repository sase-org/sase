"""Compatibility wrappers delegate primary bead paths to Rust facades."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from sase.bead.model import BeadSearchMatch, Issue, IssueType, Status
from sase.bead.project import BeadProject, EpicPreclaimRollback
from sase.core import bead_mutation_facade, bead_read_facade


def _stub_resolve_id(
    project: BeadProject, monkeypatch: pytest.MonkeyPatch
) -> list[str]:
    calls: list[str] = []

    def fake_resolve_id(issue_id: str) -> str:
        calls.append(issue_id)
        return issue_id

    monkeypatch.setattr(project, "resolve_id", fake_resolve_id)
    return calls


def test_bead_project_show_delegates_to_rust_read(tmp_path: Path, monkeypatch) -> None:
    with BeadProject.init(tmp_path) as project:
        expected = Issue(id="delegated-1", title="Delegated", issue_type=IssueType.PLAN)
        calls: list[tuple[Path | str, str]] = []

        def fake_show(beads_dir: Path | str, issue_id: str) -> Issue:
            calls.append((beads_dir, issue_id))
            return expected

        monkeypatch.setattr(bead_read_facade, "show", fake_show)
        resolve_calls = _stub_resolve_id(project, monkeypatch)

        assert project.show("delegated-1") is expected
        assert resolve_calls == ["delegated-1"]
        assert calls == [(project.beads_dir, "delegated-1")]


def test_bead_project_create_delegates_to_rust_mutation(
    tmp_path: Path, monkeypatch
) -> None:
    with BeadProject.init(tmp_path) as project:
        expected = Issue(id="delegated-1", title="Delegated", issue_type=IssueType.PLAN)
        calls: list[dict[str, Any]] = []

        def fake_create(
            beads_dir: Path | str, **kwargs: Any
        ) -> tuple[Issue, dict[str, Any]]:
            calls.append({"beads_dir": beads_dir, **kwargs})
            return expected, {"operation": "create"}

        monkeypatch.setattr(bead_mutation_facade, "create", fake_create)
        monkeypatch.setattr(project, "_refresh_db_from_jsonl", lambda: None)

        assert project.create("Delegated", IssueType.PLAN) is expected
        assert calls[0]["beads_dir"] == project.beads_dir
        assert calls[0]["title"] == "Delegated"
        assert calls[0]["issue_type"] == IssueType.PLAN
        assert "workspace_beads_dirs" not in calls[0]


def test_bead_project_claim_for_agent_launch_delegates_and_refreshes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with BeadProject.init(tmp_path) as project:
        expected = Issue(
            id="delegated-1",
            title="Delegated",
            issue_type=IssueType.PHASE,
            status=Status.IN_PROGRESS,
            assignee="agent-1",
        )
        calls: list[dict[str, Any]] = []
        refreshes: list[bool] = []

        def fake_claim(
            beads_dir: Path | str,
            bead_id: str,
            agent_name: str,
            *,
            now: str | None = None,
        ) -> tuple[Issue, dict[str, Any]]:
            calls.append(
                {
                    "beads_dir": beads_dir,
                    "bead_id": bead_id,
                    "agent_name": agent_name,
                    "now": now,
                }
            )
            return expected, {"operation": "claim_for_agent_launch"}

        monkeypatch.setattr(bead_mutation_facade, "claim_for_agent_launch", fake_claim)
        monkeypatch.setattr("sase.bead.project._now", lambda: "2026-01-01T00:00:00Z")
        monkeypatch.setattr(
            project, "_refresh_db_from_jsonl", lambda: refreshes.append(True)
        )
        resolve_calls = _stub_resolve_id(project, monkeypatch)

        assert project.claim_for_agent_launch("delegated-1", "agent-1") is expected
        assert resolve_calls == ["delegated-1"]
        assert calls == [
            {
                "beads_dir": project.beads_dir,
                "bead_id": "delegated-1",
                "agent_name": "agent-1",
                "now": "2026-01-01T00:00:00Z",
            }
        ]
        assert refreshes == [True]


def test_bead_project_claim_failure_does_not_refresh_compatibility_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with BeadProject.init(tmp_path) as project:
        refreshes: list[bool] = []

        def fail_claim(
            *_args: object, **_kwargs: object
        ) -> tuple[Issue, dict[str, Any]]:
            raise ValueError("closed: cannot claim closed bead")

        monkeypatch.setattr(bead_mutation_facade, "claim_for_agent_launch", fail_claim)
        monkeypatch.setattr(
            project, "_refresh_db_from_jsonl", lambda: refreshes.append(True)
        )
        _stub_resolve_id(project, monkeypatch)

        with pytest.raises(ValueError, match="closed"):
            project.claim_for_agent_launch("delegated-1", "agent-1")
        assert refreshes == []


def test_bead_project_preclaim_epic_work_returns_typed_rollback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with BeadProject.init(tmp_path) as project:
        calls: list[dict[str, Any]] = []
        refreshes: list[bool] = []
        assigned = [
            Issue(
                id="epic.1",
                title="First",
                issue_type=IssueType.PHASE,
                status=Status.IN_PROGRESS,
                assignee="epic.1",
            ),
            Issue(
                id="epic",
                title="Epic",
                issue_type=IssueType.PLAN,
                status=Status.IN_PROGRESS,
                assignee="epic.land",
            ),
        ]

        def fake_preclaim(
            beads_dir: Path | str,
            epic_id: str,
            assignments: list[tuple[str, str]],
            *,
            land_agent_name: str,
            now: str | None = None,
        ) -> tuple[list[Issue], dict[str, Any]]:
            calls.append(
                {
                    "beads_dir": beads_dir,
                    "epic_id": epic_id,
                    "assignments": assignments,
                    "land_agent_name": land_agent_name,
                    "now": now,
                }
            )
            return assigned, {
                "operation": "preclaim_epic_work",
                "changed": True,
                "rollback_preclaims": [
                    {"bead_id": "epic.1", "status": "open", "assignee": ""},
                    {
                        "bead_id": "epic",
                        "status": "in_progress",
                        "assignee": "old-land",
                    },
                ],
            }

        monkeypatch.setattr(bead_mutation_facade, "preclaim_epic_work", fake_preclaim)
        monkeypatch.setattr("sase.bead.project._now", lambda: "2026-01-01T00:00:00Z")
        monkeypatch.setattr(
            project, "_refresh_db_from_jsonl", lambda: refreshes.append(True)
        )
        monkeypatch.setattr(project, "resolve_id", lambda issue_id: issue_id)

        rollback = project.preclaim_epic_work(
            "epic",
            [("epic.1", "epic.1")],
            "epic.land",
        )

        assert calls == [
            {
                "beads_dir": project.beads_dir,
                "epic_id": "epic",
                "assignments": [("epic.1", "epic.1")],
                "land_agent_name": "epic.land",
                "now": "2026-01-01T00:00:00Z",
            }
        ]
        assert rollback == (
            EpicPreclaimRollback("epic.1", Status.OPEN, ""),
            EpicPreclaimRollback("epic", Status.IN_PROGRESS, "old-land"),
        )
        assert project.mutation_changed is True
        assert refreshes == [True]


@pytest.mark.parametrize(
    ("method_name", "facade_name", "status", "changed"),
    [
        ("claim_for_agent_wait", "claim_for_agent_wait", Status.CLAIMED, True),
        ("release_agent_claim", "release_agent_claim", Status.OPEN, False),
    ],
)
def test_bead_project_wait_claim_methods_return_mutation_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    method_name: str,
    facade_name: str,
    status: Status,
    changed: bool,
) -> None:
    with BeadProject.init(tmp_path) as project:
        expected = Issue(
            id="delegated-1",
            title="Delegated",
            issue_type=IssueType.PHASE,
            status=status,
            assignee="agent-1" if status == Status.CLAIMED else "",
        )
        refreshes: list[bool] = []

        def fake_mutation(
            beads_dir: Path | str,
            bead_id: str,
            agent_name: str,
            *,
            now: str | None = None,
        ) -> tuple[Issue, dict[str, Any]]:
            assert (beads_dir, bead_id, agent_name, now) == (
                project.beads_dir,
                "delegated-1",
                "agent-1",
                "2026-01-01T00:00:00Z",
            )
            return expected, {"changed": changed}

        monkeypatch.setattr(bead_mutation_facade, facade_name, fake_mutation)
        monkeypatch.setattr("sase.bead.project._now", lambda: "2026-01-01T00:00:00Z")
        monkeypatch.setattr(
            project, "_refresh_db_from_jsonl", lambda: refreshes.append(True)
        )
        resolve_calls = _stub_resolve_id(project, monkeypatch)

        method = getattr(project, method_name)
        assert method("delegated-1", "agent-1") == (expected, changed)
        assert resolve_calls == ["delegated-1"]
        assert refreshes == [True]


def test_bead_project_remove_many_delegates_and_refreshes_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with BeadProject.init(tmp_path) as project:
        removed = [
            Issue(id="delegated-1", title="First", issue_type=IssueType.PLAN),
            Issue(id="delegated-2", title="Second", issue_type=IssueType.PLAN),
        ]
        calls: list[tuple[Path | str, list[str]]] = []
        refreshes: list[bool] = []

        def fake_remove_many(
            beads_dir: Path | str, issue_ids: list[str]
        ) -> tuple[list[Issue], dict[str, Any]]:
            calls.append((beads_dir, issue_ids))
            return removed, {"operation": "rm"}

        monkeypatch.setattr(bead_mutation_facade, "remove_many", fake_remove_many)
        monkeypatch.setattr(
            project, "_refresh_db_from_jsonl", lambda: refreshes.append(True)
        )
        resolve_calls = _stub_resolve_id(project, monkeypatch)

        assert project.remove_many(["delegated-1", "delegated-2"]) == removed
        assert resolve_calls == ["delegated-1", "delegated-2"]
        assert calls == [(project.beads_dir, ["delegated-1", "delegated-2"])]
        assert refreshes == [True]


def test_bead_project_update_many_delegates_and_refreshes_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with BeadProject.init(tmp_path) as project:
        updated = [
            Issue(id="delegated-1", title="First", issue_type=IssueType.TASK),
            Issue(id="delegated-2", title="Second", issue_type=IssueType.TASK),
        ]
        calls: list[dict[str, Any]] = []
        refreshes: list[bool] = []

        def fake_update_many(
            beads_dir: Path | str, issue_ids: list[str], **fields: Any
        ) -> tuple[list[Issue], dict[str, Any]]:
            calls.append({"beads_dir": beads_dir, "issue_ids": issue_ids, **fields})
            return updated, {"operation": "update", "changed": True}

        monkeypatch.setattr(bead_mutation_facade, "update_many", fake_update_many)
        monkeypatch.setattr(
            project, "_refresh_db_from_jsonl", lambda: refreshes.append(True)
        )
        resolve_calls = _stub_resolve_id(project, monkeypatch)

        result = project.update_many(
            ["delegated-1", "delegated-2"], status="in_progress"
        )

        assert result == updated
        assert resolve_calls == [
            "delegated-1",
            "delegated-2",
            "delegated-1",
            "delegated-2",
        ]
        assert len(calls) == 1
        assert calls[0]["beads_dir"] == project.beads_dir
        assert calls[0]["issue_ids"] == ["delegated-1", "delegated-2"]
        assert calls[0]["status"] == "in_progress"
        assert refreshes == [True]


def test_bead_project_show_returns_issue_with_model(
    tmp_path: Path, monkeypatch
) -> None:
    with BeadProject.init(tmp_path) as project:
        expected = Issue(
            id="delegated-1",
            title="Delegated",
            issue_type=IssueType.PLAN,
            model="codex/gpt-5.5",
        )

        calls: list[tuple[Path | str, str]] = []

        def fake_show(beads_dir: Path | str, issue_id: str) -> Issue:
            calls.append((beads_dir, issue_id))
            return expected

        monkeypatch.setattr(bead_read_facade, "show", fake_show)
        resolve_calls = _stub_resolve_id(project, monkeypatch)

        result = project.show("delegated-1")
        assert result is not None
        assert result.model == "codex/gpt-5.5"
        assert resolve_calls == ["delegated-1"]
        assert calls == [(project.beads_dir, "delegated-1")]


def test_bead_project_search_delegates_to_rust_read(
    tmp_path: Path, monkeypatch
) -> None:
    with BeadProject.init(tmp_path) as project:
        expected = [
            BeadSearchMatch(
                issue=Issue(
                    id="delegated-1",
                    title="Delegated",
                    issue_type=IssueType.PLAN,
                ),
                matched_fields=["title"],
            )
        ]
        calls: list[dict[str, Any]] = []

        def fake_search(
            beads_dir: Path | str, query: str, **kwargs: Any
        ) -> list[BeadSearchMatch]:
            calls.append({"beads_dir": beads_dir, "query": query, **kwargs})
            return expected

        monkeypatch.setattr(bead_read_facade, "search", fake_search)

        assert project.search("delegated", statuses=[Status.OPEN], limit=1) is expected
        assert calls == [
            {
                "beads_dir": project.beads_dir,
                "query": "delegated",
                "statuses": [Status.OPEN],
                "issue_types": None,
                "tiers": None,
                "limit": 1,
            }
        ]
