"""Schema upgrade, snapshot, and lock-free outbox read tests."""

from __future__ import annotations

import json

import pytest
from sase.agents_sync.publication_outbox import (
    PUBLICATION_OUTBOX_SCHEMA_VERSION,
    PUBLICATION_SCOPE_REVISION,
    list_agent_publications,
    snapshot_agent_publications_from_path,
    snapshot_publication_document_from_path,
    update_agent_publications,
)
from tests.agents_sync.test_publication_outbox._helpers import make_outbox_item


def _v4_document() -> dict[str, object]:
    """Return a schema-4 outbox holding one request of every retired kind."""

    agent_row = {**make_outbox_item().to_json_dict(), "kind": "agent_hood", "rank": 0}
    return {
        "schema_version": 4,
        "items": [
            agent_row,
            {
                "id": "bead",
                "kind": "bead_pages",
                "rank": 1,
                "project_key": "proj",
                "project": "Project",
                "bead_id": "proj-ab.2",
                "lineage_root": "proj-ab",
                "primary_revision": "b" * 40,
                "attempts": 0,
                "last_error": None,
                "quarantined": False,
                "quarantined_at": None,
                "terminal": False,
                "terminal_reason": None,
                "created_at": 0.0,
                "updated_at": 0.0,
            },
            {
                "id": "plan",
                "kind": "plan_header",
                "rank": 2,
                "project_key": "proj",
                "project": "Project",
                "plan_ref": "plan:202608/example.md",
                "primary_revision": "c" * 40,
                "commit_message": "feat: example",
                "attempts": 0,
                "last_error": None,
                "quarantined": False,
                "quarantined_at": None,
                "terminal": False,
                "terminal_reason": None,
                "created_at": 0.0,
                "updated_at": 0.0,
            },
            {
                "id": "push",
                "kind": "sidecar_push",
                "rank": 3,
                "project_key": "proj",
                "project": "Project",
                "sidecar_kind": "beads",
                "attempts": 0,
                "last_error": None,
                "quarantined": False,
                "quarantined_at": None,
                "terminal": False,
                "terminal_reason": None,
                "created_at": 0.0,
                "updated_at": 0.0,
            },
        ],
    }


def test_schema_v1_backlog_is_read_and_upgraded_without_data_loss(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path))
    path = tmp_path / "projects" / "proj" / "agents-publication-outbox.json"
    path.parent.mkdir(parents=True)
    row = make_outbox_item().to_json_dict()
    row.pop("quarantined")
    row.pop("quarantined_at")
    row.pop("terminal")
    row.pop("terminal_reason")
    path.write_text(
        json.dumps({"schema_version": 1, "items": [row]}),
        encoding="utf-8",
    )

    loaded = list_agent_publications("proj")
    assert len(loaded) == 1
    assert not loaded[0].quarantined

    update_agent_publications(
        "proj",
        (loaded[0].logical_key,),
        error="still pending",
    )
    upgraded = json.loads(path.read_text(encoding="utf-8"))
    assert upgraded["schema_version"] == PUBLICATION_OUTBOX_SCHEMA_VERSION
    assert upgraded["items"][0]["quarantined"] is False
    assert upgraded["items"][0]["quarantined_at"] is None
    assert upgraded["items"][0]["terminal"] is False
    assert upgraded["items"][0]["terminal_reason"] is None


def test_schema_v2_backlog_loads_without_terminal_state_and_upgrades(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path))
    path = tmp_path / "projects" / "proj" / "agents-publication-outbox.json"
    path.parent.mkdir(parents=True)
    row = make_outbox_item().to_json_dict()
    row.pop("terminal")
    row.pop("terminal_reason")
    path.write_text(
        json.dumps({"schema_version": 2, "items": [row]}),
        encoding="utf-8",
    )

    [loaded] = list_agent_publications("proj")
    assert not loaded.terminal
    assert loaded.terminal_reason is None

    update_agent_publications("proj", (loaded.logical_key,), error="still pending")
    upgraded = json.loads(path.read_text(encoding="utf-8"))
    assert upgraded["schema_version"] == PUBLICATION_OUTBOX_SCHEMA_VERSION
    assert upgraded["items"][0]["terminal"] is False
    assert upgraded["items"][0]["terminal_reason"] is None


def test_lock_free_snapshot_reads_schema_v1_without_writing(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path))
    path = tmp_path / "projects" / "proj" / "agents-publication-outbox.json"
    path.parent.mkdir(parents=True)
    row = make_outbox_item().to_json_dict()
    row.pop("quarantined")
    row.pop("quarantined_at")
    row.pop("terminal")
    row.pop("terminal_reason")
    payload = json.dumps({"schema_version": 1, "items": [row]})
    path.write_text(payload, encoding="utf-8")

    [loaded] = snapshot_agent_publications_from_path(path, "proj")

    assert loaded.logical_key == make_outbox_item().logical_key
    assert loaded.attempts == 0
    assert loaded.quarantined is False
    assert path.read_text(encoding="utf-8") == payload
    assert not path.with_suffix(".json.lock").exists()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("attempts", True),
        ("attempts", "3"),
        ("attempts", -1),
        ("quarantined", 1),
        ("quarantined", "false"),
    ],
)
def test_typed_snapshot_rejects_malformed_consumed_fields(
    tmp_path,
    monkeypatch,
    field,
    value,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path))
    path = tmp_path / "projects" / "proj" / "agents-publication-outbox.json"
    path.parent.mkdir(parents=True)
    row = make_outbox_item().to_json_dict()
    row[field] = value
    path.write_text(
        json.dumps({"schema_version": 2, "items": [row]}),
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match=field):
        snapshot_agent_publications_from_path(path, "proj")


def test_schema_v2_snapshot_requires_quarantine_state(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path))
    path = tmp_path / "projects" / "proj" / "agents-publication-outbox.json"
    path.parent.mkdir(parents=True)
    row = make_outbox_item().to_json_dict()
    row.pop("quarantined")
    path.write_text(
        json.dumps({"schema_version": 2, "items": [row]}),
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="quarantined"):
        snapshot_agent_publications_from_path(path, "proj")


def test_schema_v3_agent_request_loads_with_same_logical_key(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path))
    path = tmp_path / "projects" / "proj" / "agents-publication-outbox.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps({"schema_version": 3, "items": [make_outbox_item().to_json_dict()]}),
        encoding="utf-8",
    )

    [loaded] = list_agent_publications("proj")

    assert loaded.logical_key == make_outbox_item().logical_key


def test_schema_v4_drops_non_agent_requests_with_a_visible_diagnostic(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path))
    path = tmp_path / "projects" / "proj" / "agents-publication-outbox.json"
    path.parent.mkdir(parents=True)
    payload = json.dumps(_v4_document())
    path.write_text(payload, encoding="utf-8")

    document = snapshot_publication_document_from_path(path, "proj")

    [survivor] = document.items
    assert survivor.logical_key == make_outbox_item().logical_key
    assert survivor.local_hood == "foo"
    [notice] = document.notices
    assert "dropped 3 obsolete publication request(s)" in notice
    assert "1 bead_pages, 1 plan_header, 1 sidecar_push" in notice
    assert "published inline on the commit path" in notice
    assert path.read_text(encoding="utf-8") == payload

    assert list_agent_publications("proj") == document.items

    update_agent_publications("proj", (survivor.logical_key,), error=None)
    rewritten = json.loads(path.read_text(encoding="utf-8"))
    assert rewritten["schema_version"] == PUBLICATION_OUTBOX_SCHEMA_VERSION
    assert PUBLICATION_OUTBOX_SCHEMA_VERSION == 7
    assert rewritten["items"][0]["scope"] == PUBLICATION_SCOPE_REVISION
    assert [row["global_agent"] for row in rewritten["items"]] == [
        make_outbox_item().global_agent
    ]
    assert "kind" not in rewritten["items"][0]
    assert snapshot_publication_document_from_path(path, "proj").notices == ()


def test_schema_v6_row_without_requested_revision_keeps_original(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path))
    path = tmp_path / "projects" / "proj" / "agents-publication-outbox.json"
    path.parent.mkdir(parents=True)
    row = make_outbox_item().to_json_dict()
    row.pop("requested_revision")
    path.write_text(
        json.dumps({"schema_version": 6, "items": [row]}),
        encoding="utf-8",
    )

    [loaded] = list_agent_publications("proj")
    assert loaded.requested_revision is None
    assert loaded.original_revision == make_outbox_item().primary_revision

    update_agent_publications("proj", (loaded.logical_key,), error="still pending")
    upgraded = json.loads(path.read_text(encoding="utf-8"))
    assert upgraded["schema_version"] == PUBLICATION_OUTBOX_SCHEMA_VERSION
    assert upgraded["items"][0]["requested_revision"] is None


def test_schema_v7_requested_revision_round_trip(tmp_path, monkeypatch) -> None:
    import dataclasses

    monkeypatch.setenv("SASE_HOME", str(tmp_path))
    path = tmp_path / "projects" / "proj" / "agents-publication-outbox.json"
    path.parent.mkdir(parents=True)
    repaired = dataclasses.replace(
        make_outbox_item(),
        primary_revision="b" * 40,
        requested_revision="a" * 40,
    )
    path.write_text(
        json.dumps(
            {
                "schema_version": 7,
                "items": [repaired.to_json_dict()],
            }
        ),
        encoding="utf-8",
    )

    [loaded] = list_agent_publications("proj")
    assert loaded.logical_key == ("alice.athena.foo--code", "b" * 40)
    assert loaded.original_revision == "a" * 40


def test_schema_v7_commit_context_round_trip_and_legacy_defaults(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path))
    path = tmp_path / "projects" / "proj" / "agents-publication-outbox.json"
    path.parent.mkdir(parents=True)
    row = {
        **make_outbox_item().to_json_dict(),
        "commit_cwd": "/work/project",
        "artifacts_dir": "/runs/run-1",
        "run_id": "run-1",
    }
    path.write_text(
        json.dumps({"schema_version": 7, "items": [row]}),
        encoding="utf-8",
    )

    [loaded] = list_agent_publications("proj")
    assert loaded.commit_cwd == "/work/project"
    assert loaded.artifacts_dir == "/runs/run-1"
    assert loaded.run_id == "run-1"

    legacy_row = make_outbox_item(revision="b" * 40).to_json_dict()
    legacy_row.pop("commit_cwd")
    legacy_row.pop("artifacts_dir")
    legacy_row.pop("run_id")
    path.write_text(
        json.dumps({"schema_version": 7, "items": [legacy_row]}),
        encoding="utf-8",
    )
    [legacy] = list_agent_publications("proj")
    assert legacy.commit_cwd is None
    assert legacy.artifacts_dir is None
    assert legacy.run_id is None


def test_schema_v5_row_without_scope_defaults_to_revision(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path))
    path = tmp_path / "projects" / "proj" / "agents-publication-outbox.json"
    path.parent.mkdir(parents=True)
    row = make_outbox_item().to_json_dict()
    row.pop("scope")
    path.write_text(
        json.dumps({"schema_version": 5, "items": [row]}),
        encoding="utf-8",
    )

    [loaded] = list_agent_publications("proj")
    assert loaded.scope == PUBLICATION_SCOPE_REVISION
