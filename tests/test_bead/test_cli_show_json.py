"""CLI coverage for JSON bead show output and machine-readable parity."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
import json
from pathlib import Path

import pytest

from sase.bead import cli as bead_cli
from sase.bead.model import BeadNote, Dependency, Issue, IssueType
from sase.bead.project import BeadProject
from sase.main.parser import create_parser
from tests.test_bead.cli_show_test_helpers import (
    show,
    show_with_format,
    use_single_issue_view,
)


def test_show_json_includes_page_url_when_resolved(
    nested_store: dict[str, Issue],
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = nested_store["root"]
    monkeypatch.setattr(
        "sase.bead.cli_query.resolve_bead_page_url",
        lambda bead_id: f"https://example.test/pages/{bead_id}",
    )

    payload = json.loads(show_with_format(root, "json", capsys))

    assert payload["page_url"] == f"https://example.test/pages/{root.id}"


def test_show_json_includes_creator_url_only_when_resolved(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    issue = Issue(
        id="beads-agent",
        title="Agent-created task",
        issue_type=IssueType.TASK,
        owner="owner@example.com",
        created_by="bbugyi200.athena.q8--plan",
    )
    creator_url = "https://example.test/agents/q8--plan"
    use_single_issue_view(monkeypatch, issue)
    monkeypatch.setattr(
        "sase.bead.cli_query.resolve_bead_creator_url",
        lambda _name: creator_url,
    )

    resolved = json.loads(show_with_format(issue, "json", capsys))

    assert resolved["created_by_url"] == creator_url

    monkeypatch.setattr(
        "sase.bead.cli_query.resolve_bead_creator_url",
        lambda _name: None,
    )
    unresolved = json.loads(show_with_format(issue, "json", capsys))

    assert "created_by_url" not in unresolved


def test_show_json_includes_external_ref(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    issue = Issue(
        id="beads-external",
        title="Mirrored task",
        issue_type=IssueType.TASK,
        external_ref="bug:sase#42",
    )
    use_single_issue_view(monkeypatch, issue)

    payload = json.loads(show_with_format(issue, "json", capsys))

    assert payload["issue"]["external_ref"] == "bug:sase#42"


def test_show_json_emits_structured_notes_and_flat_notes_text(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    issue = Issue(
        id="beads-notes-json",
        title="Notes JSON",
        issue_type=IssueType.TASK,
        notes=[
            BeadNote(
                id="note-1",
                timestamp="2026-08-01T11:30:00Z",
                author="agent.alpha",
                text="First note body.",
            ),
            BeadNote(
                id="note-2",
                timestamp="2026-08-01T11:45:00Z",
                author="owner@example.com",
                text="Corrected note body.",
                edited_at="2026-08-01T11:50:00Z",
                edited_by="owner@example.com",
            ),
        ],
    )
    use_single_issue_view(monkeypatch, issue)

    payload = json.loads(show_with_format(issue, "json", capsys))

    assert payload["issue"]["notes"] == [
        {
            "id": "note-1",
            "timestamp": "2026-08-01T11:30:00Z",
            "author": "agent.alpha",
            "text": "First note body.",
        },
        {
            "id": "note-2",
            "timestamp": "2026-08-01T11:45:00Z",
            "author": "owner@example.com",
            "text": "Corrected note body.",
            "edited_at": "2026-08-01T11:50:00Z",
            "edited_by": "owner@example.com",
        },
    ]
    assert payload["issue"]["notes_text"] == (
        "[2026-08-01T11:30:00Z · agent.alpha] First note body.\n\n"
        "[2026-08-01T11:45:00Z · owner@example.com] Corrected note body."
    )


def test_show_json_root_includes_children_and_self_plan(
    nested_store: dict[str, Issue],
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = nested_store["root"]

    payload = json.loads(show_with_format(root, "json", capsys))

    assert payload["issue"]["id"] == root.id
    assert payload["ancestors"] == []
    assert [ref["id"] for ref in payload["children"]["phases"]] == [
        nested_store["phase"].id,
        nested_store["childless_phase"].id,
    ]
    assert [ref["id"] for ref in payload["children"]["epics"]] == [
        nested_store["epic_child"].id
    ]
    assert payload["plan"]["source"] == "self"
    assert payload["plan"]["from"] is None
    assert payload["plan"]["path"] == root.design


def test_show_json_nested_phase_includes_nearest_first_lineage_and_parent_plan(
    nested_store: dict[str, Issue],
    capsys: pytest.CaptureFixture[str],
) -> None:
    nested_phase = nested_store["nested_phase"]

    payload = json.loads(show_with_format(nested_phase, "json", capsys))

    assert [ref["id"] for ref in payload["ancestors"]] == [
        nested_store["phase_child"].id,
        nested_store["phase"].id,
        nested_store["root"].id,
    ]
    assert payload["plan"]["source"] == "parent"
    assert payload["plan"]["section"] == "EPIC PLAN"
    assert payload["plan"]["from"]["id"] == nested_store["phase_child"].id


def test_show_json_includes_resolved_dependencies_and_blockers(
    nested_store: dict[str, Issue],
    capsys: pytest.CaptureFixture[str],
) -> None:
    phase = nested_store["phase"]
    childless_phase = nested_store["childless_phase"]
    with BeadProject(Path.cwd()) as project:
        project.add_dependency(childless_phase.id, phase.id)

    depends_payload = json.loads(show_with_format(childless_phase, "json", capsys))
    blocks_payload = json.loads(show_with_format(phase, "json", capsys))

    assert [(ref["id"], ref["resolved"]) for ref in depends_payload["depends_on"]] == [
        (phase.id, True)
    ]
    assert [(ref["id"], ref["resolved"]) for ref in blocks_payload["blocks"]] == [
        (childless_phase.id, True)
    ]


def test_show_json_and_full_mirror_dangling_relationships(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    issue = Issue(
        id="beads-dangling",
        title="Dangling",
        issue_type=IssueType.PHASE,
        parent_id="beads-missing-parent",
        dependencies=[
            Dependency(
                issue_id="beads-dangling",
                depends_on_id="beads-missing-dependency",
                created_at="2026-07-27T00:00:00Z",
            )
        ],
    )

    class _DanglingView:
        def show(self, issue_id: str) -> Issue:
            if issue_id == issue.id:
                return issue
            raise KeyError(issue_id)

        def get_epic_children(self, _issue_id: str) -> list[Issue]:
            return []

        def list_issues(self) -> list[Issue]:
            return [issue]

    @contextmanager
    def read_view() -> Iterator[_DanglingView]:
        yield _DanglingView()

    monkeypatch.setattr("sase.bead.cli_query.get_read_view", read_view)
    monkeypatch.setattr(
        "sase.bead.cli_query.design_paths_are_relative",
        lambda: False,
    )

    payload = json.loads(show_with_format(issue, "json", capsys))
    full_out = show(issue, capsys)

    unresolved_parent = payload["ancestors"][0]
    unresolved_dependency = payload["depends_on"][0]
    assert unresolved_parent == {
        "id": "beads-missing-parent",
        "resolved": False,
        "title": None,
        "status": None,
        "issue_type": None,
        "tier": None,
        "size": None,
    }
    assert unresolved_dependency == {
        "id": "beads-missing-dependency",
        "resolved": False,
        "title": None,
        "status": None,
        "issue_type": None,
        "tier": None,
        "size": None,
    }
    assert "beads-missing-parent (not found)" in full_out
    assert "beads-missing-dependency (not found)" in full_out


def test_show_json_contains_every_bead_id_from_full_output(
    nested_store: dict[str, Issue],
    capsys: pytest.CaptureFixture[str],
) -> None:
    for issue in nested_store.values():
        full_out = show(issue, capsys)
        payload = json.loads(show_with_format(issue, "json", capsys))
        json_text = json.dumps(payload)
        ids_in_full = {
            candidate.id
            for candidate in nested_store.values()
            if candidate.id in full_out
        }
        assert all(issue_id in json_text for issue_id in ids_in_full)


def test_show_json_missing_id_exits_with_stderr_only(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    args = create_parser().parse_args(
        ["bead", "show", "beads-missing", "--format", "json"]
    )

    with pytest.raises(SystemExit) as excinfo:
        bead_cli.handle_bead_show(args)

    captured = capsys.readouterr()
    assert excinfo.value.code == 1
    assert captured.out == ""
    assert captured.err == "Error: issue not found: beads-missing\n"


def test_search_json_keeps_phase_size_in_machine_output(
    nested_store: dict[str, Issue],
    capsys: pytest.CaptureFixture[str],
) -> None:
    phase = nested_store["phase"]
    args = create_parser().parse_args(["bead", "search", "medium", "--format", "json"])

    bead_cli.handle_bead_search(args)

    payload = json.loads(capsys.readouterr().out)
    assert payload["count"] == 1
    assert payload["results"][0]["issue"]["id"] == phase.id
    assert payload["results"][0]["issue"]["size"] == "medium"
    assert payload["results"][0]["matched_fields"] == ["size"]


def test_search_json_uses_structured_notes_shape(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with BeadProject(project_dir) as project:
        project.create("Notes Carrier", IssueType.PLAN, notes="private needle note")

    args = create_parser().parse_args(["bead", "search", "needle", "--format", "json"])
    bead_cli.handle_bead_search(args)

    payload = json.loads(capsys.readouterr().out)
    note_payload = payload["results"][0]["issue"]["notes"][0]
    assert note_payload["author"]
    assert note_payload["timestamp"]
    assert note_payload["text"] == "private needle note"
    assert "private needle note" in payload["results"][0]["issue"]["notes_text"]


def test_show_renders_recorded_and_unrecorded_resolution(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with BeadProject(project_dir) as project:
        recorded = project.create("Canceled", IssueType.PLAN)
        project.close(
            [recorded.id],
            reason="Replaced by a newer plan",
            resolution="canceled",
        )
        historical = project.create("Historical", IssueType.PLAN)
        project.update(historical.id, status="closed")

    recorded_out = show(recorded, capsys)
    assert "RESOLUTION" in recorded_out
    assert "Resolution: canceled" in recorded_out
    assert "Close reason: Replaced by a newer plan" in recorded_out
    assert "Closed at:" in recorded_out

    historical_out = show(historical, capsys)
    assert "Resolution: (unrecorded)" in historical_out

    payload = json.loads(show_with_format(recorded, "json", capsys))
    assert payload["issue"]["resolution"] == "canceled"
