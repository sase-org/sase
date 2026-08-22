"""Parity tests for the Rust bead read facade."""

from __future__ import annotations

import shutil
import json
from pathlib import Path

import pytest

from sase.artifact_ref_models import ArtifactRefContext
from sase.bead.model import BeadSearchMatch, Issue, IssueType, Status
from sase.bead.project import BeadProject
from sase.core import bead_read_facade as rust_beads

GOLDEN = Path(__file__).parents[1] / "test_bead" / "golden"


def _ids(issues: list[Issue]) -> list[str]:
    return [issue.id for issue in issues]


def _match_pairs(matches: list[BeadSearchMatch]) -> list[tuple[str, list[str]]]:
    return [(match.issue.id, match.matched_fields) for match in matches]


@pytest.fixture
def bead_store(tmp_path: Path) -> tuple[BeadProject, Path, dict[str, Issue]]:
    shutil.copytree(GOLDEN / "stores" / "current", tmp_path / "sdd/beads")
    project = BeadProject(tmp_path)
    return (
        project,
        tmp_path / "sdd/beads",
        {
            "epic": project.show("beads-1"),
            "first": project.show("beads-1.1"),
            "second": project.show("beads-1.2"),
            "other": project.show("beads-3"),
        },
    )


def test_read_facade_matches_bead_project_queries(
    bead_store: tuple[BeadProject, Path, dict[str, Issue]],
) -> None:
    project, beads_dir, issues = bead_store
    try:
        assert rust_beads.show(beads_dir, issues["epic"].id) == project.show(
            issues["epic"].id
        )
        detail = rust_beads.show_issue_detail(beads_dir, issues["second"].id)
        assert detail.issue == issues["second"]
        assert [issue.id if issue else None for issue in detail.ancestors] == [
            issues["epic"].id
        ]
        assert detail.children == ()
        assert [issue.id if issue else None for issue in detail.depends_on] == [
            issues["first"].id
        ]
        assert detail.blocks == ()
        assert _ids(rust_beads.list_issues(beads_dir)) == _ids(project.list_issues())
        assert _ids(rust_beads.list_issues(beads_dir, statuses=[Status.OPEN])) == _ids(
            project.list_issues(statuses=[Status.OPEN])
        )
        assert _ids(
            rust_beads.list_issues(beads_dir, issue_types=[IssueType.PLAN])
        ) == _ids(project.list_issues(issue_types=[IssueType.PLAN]))
        assert _ids(rust_beads.ready(beads_dir)) == _ids(project.ready())
        assert _ids(rust_beads.blocked(beads_dir)) == _ids(project.blocked())
        assert _match_pairs(rust_beads.search(beads_dir, "alpha")) == _match_pairs(
            project.search("alpha")
        )
        assert _match_pairs(
            rust_beads.search(beads_dir, "alp.*", regex=True)
        ) == _match_pairs(project.search("alp.*", regex=True))
        assert rust_beads.stats(beads_dir) == project.stats()
        assert _ids(rust_beads.get_epic_children(beads_dir, issues["epic"].id)) == _ids(
            project.get_epic_children(issues["epic"].id)
        )
    finally:
        project.__exit__()


def test_read_facade_show_issue_detail_can_skip_link_projection(
    tmp_path: Path,
) -> None:
    from sase.bead.model import IssueType
    from sase.bead.project import BeadProject
    from sase.sdd.artifact_link_beads import add_bead_endpoint_link

    with BeadProject.init(tmp_path) as project:
        left = project.create("Left", IssueType.PLAN)
        right = project.create("Right", IssueType.PLAN)
        add_bead_endpoint_link(
            project.beads_dir,
            issue_id=left.id,
            target_ref=f"bead:{right.id}",
            relation="related",
            description="shares the same rendering contract",
            origin="manual",
            now="2026-08-22T14:10:00Z",
        )
        enabled = rust_beads.show_issue_detail(project.beads_dir, left.id)
        disabled = rust_beads.show_issue_detail(
            project.beads_dir, left.id, include_links=False
        )

    assert enabled.artifact_links
    assert enabled.artifact_links[0].created_at == "2026-08-22T14:10:00Z"
    assert disabled.artifact_links == ()
    assert disabled.issue.links


def test_read_facade_missing_issue_raises_key_error(
    bead_store: tuple[BeadProject, Path, dict[str, Issue]],
) -> None:
    project, beads_dir, _ = bead_store
    try:
        with pytest.raises(KeyError, match="Issue not found"):
            rust_beads.show(beads_dir, "missing")
        with pytest.raises(KeyError, match="Issue not found"):
            rust_beads.show_issue_detail(beads_dir, "missing")
    finally:
        project.__exit__()


def test_read_facade_search_forwards_regex_keyword(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def binding(*args: object, **kwargs: object) -> list[dict[str, object]]:
        calls.append((args, kwargs))
        return []

    monkeypatch.setattr(
        rust_beads,
        "require_rust_binding",
        lambda name: binding if name == "bead_search" else None,
    )

    assert rust_beads.search(tmp_path, "needle", limit=2, regex=True) == []
    assert calls == [
        (
            (str(tmp_path), "needle", None, None, None, 2),
            {"regex": True},
        )
    ]


def test_doctor_reads_jsonl_without_requiring_sqlite(tmp_path: Path) -> None:
    beads_dir = tmp_path / "sdd/beads"
    with BeadProject.init(tmp_path) as project:
        project.create("Epic", IssueType.PLAN)
    (beads_dir / "beads.db").unlink()

    assert rust_beads.list_issues(beads_dir)
    assert rust_beads.doctor(beads_dir) == ["WARNING: beads.db missing"]


def test_doctor_forwards_optional_reference_context(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[object, ...]] = []

    def binding(*args: object) -> list[str]:
        calls.append(args)
        return ["OK"]

    monkeypatch.setattr(
        rust_beads,
        "require_rust_binding",
        lambda name: binding if name == "bead_doctor" else None,
    )
    beads_dir = tmp_path / "beads"
    root = tmp_path / "plans"
    context = ArtifactRefContext(
        document_roots=(),
        chats_root=tmp_path / "chats",
        artifact_index_path=tmp_path / "artifacts/index.jsonl",
        repositories=(),
        projects=(),
    )

    assert rust_beads.doctor(beads_dir) == ["OK"]
    assert rust_beads.doctor(beads_dir, (root,)) == ["OK"]
    assert rust_beads.doctor(beads_dir, ()) == ["OK"]
    assert rust_beads.doctor(beads_dir, None, context) == ["OK"]
    assert calls == [
        (str(beads_dir),),
        (str(beads_dir), [str(root)], None),
        (str(beads_dir), [], None),
        (str(beads_dir), None, context.to_wire()),
    ]


def test_event_store_wins_over_stale_jsonl_projection(tmp_path: Path) -> None:
    beads_dir = tmp_path / "sdd/beads"
    beads_dir.mkdir(parents=True)
    (beads_dir / "config.json").write_text("{}\n")
    (beads_dir / "beads.db").write_text("")
    _write_event_store(beads_dir, [_issue_event("beads-1", "Canonical Epic")])
    (beads_dir / "issues.jsonl").write_text(
        json.dumps(
            _issue_payload("beads-1", "Stale Legacy Epic"), separators=(",", ":")
        )
        + "\n"
    )

    assert rust_beads.show(beads_dir, "beads-1").title == "Canonical Epic"
    assert any(
        "issues.jsonl is 1 row(s) stale" in message and "--fix-projection" in message
        for message in rust_beads.doctor(beads_dir)
    )


def test_event_store_reads_without_legacy_projection(tmp_path: Path) -> None:
    beads_dir = tmp_path / "sdd/beads"
    beads_dir.mkdir(parents=True)
    (beads_dir / "config.json").write_text("{}\n")
    (beads_dir / "beads.db").write_text("")
    _write_event_store(
        beads_dir,
        [
            _issue_event("beads-1", "Canonical Epic"),
            _issue_event("beads-1.1", "Canonical Child", parent_id="beads-1"),
        ],
    )

    assert _ids(rust_beads.list_issues(beads_dir)) == ["beads-1", "beads-1.1"]
    assert _ids(rust_beads.get_epic_children(beads_dir, "beads-1")) == ["beads-1.1"]
    assert "WARNING: issues.jsonl missing" in rust_beads.doctor(beads_dir)


def _write_event_store(beads_dir: Path, events: list[dict[str, object]]) -> None:
    events_dir = beads_dir / "events"
    streams_dir = events_dir / "streams"
    streams_dir.mkdir(parents=True)
    (events_dir / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "stream_count": 1,
                "generated_from": "issues.jsonl",
                "migration_tool": "test",
            },
            separators=(",", ":"),
        )
    )
    (streams_dir / "beads-1.jsonl").write_text(
        "".join(json.dumps(event, separators=(",", ":")) + "\n" for event in events)
    )


def _issue_event(
    issue_id: str, title: str, *, parent_id: str | None = None
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "event_id": f"beads-1:issue_created:{issue_id}",
        "timestamp": "2026-01-01T00:00:00Z",
        "actor": "",
        "operation": "issue_created",
        "issue_id": issue_id,
        "payload": {
            "kind": "issue_created",
            "issue": _issue_payload(issue_id, title, parent_id),
        },
    }


def _issue_payload(
    issue_id: str, title: str, parent_id: str | None = None
) -> dict[str, object]:
    return {
        "id": issue_id,
        "title": title,
        "status": "open",
        "issue_type": "phase" if parent_id else "plan",
        "parent_id": parent_id,
        "owner": "",
        "assignee": "",
        "created_at": "2026-01-01T00:00:00Z",
        "created_by": "",
        "updated_at": "2026-01-01T00:00:00Z",
        "closed_at": None,
        "close_reason": None,
        "description": "",
        "notes": "",
        "design": "",
        "model": "",
        "is_ready_to_work": False,
        "changespec_name": "",
        "changespec_bug_id": "",
        "dependencies": [],
    }
