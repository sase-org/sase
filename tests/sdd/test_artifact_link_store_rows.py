"""Row upsert, canonicalization, and removal for the artifact link store."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.bead.model import IssueType
from sase.bead.project import BeadProject
from sase.sdd.artifact_link_store import ArtifactLinkStore, artifact_link_aggregate_path
from tests._conftest_environment import redirect_sase_home
from tests.sdd._artifact_link_store_helpers import _plan_index, _row, _store


def test_upsert_writes_both_sidecars_and_rebuilds_aggregate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _store(tmp_path, monkeypatch)
    outcome = store.upsert_row(_row())

    assert outcome["kind"] == "added"
    source_path = _plan_index(tmp_path, "a.md")
    target_path = _plan_index(tmp_path, "b.md")
    source_index = json.loads(source_path.read_text(encoding="utf-8"))
    target_index = json.loads(target_path.read_text(encoding="utf-8"))
    assert source_index["schema_version"] == 2
    assert len(source_index["rows"]) == 1
    assert source_index["rows"][0]["relation"] == "implements"
    assert target_index["rows"][0]["source_ref"] == "plan:202608/a.md"
    aggregate = json.loads(
        artifact_link_aggregate_path("gh_sase-org__sase").read_text(encoding="utf-8")
    )
    assert len(aggregate["rows"]) == 1
    assert store.load_artifact_rows("plan:202608/a.md")[0]["target_ref"] == (
        "plan:202608/b.md"
    )


def test_prompt_ref_upsert_converges_uses_instead_of_incrementing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _store(tmp_path, monkeypatch)
    prompt_ref = _row(
        source="agent:alice.athena.worker",
        relation="cites",
        target="plan:202608/a.md",
        origin="prompt_ref",
        description="prompt reference @plan:202608/a.md",
        uses=2,
    )

    assert store.upsert_row(prompt_ref)["kind"] == "added"
    assert store.upsert_row(prompt_ref)["kind"] == "unchanged"
    assert store.load_artifact_rows("plan:202608/a.md")[0]["uses"] == 2

    store.upsert_row({**prompt_ref, "uses": 3})
    assert store.load_artifact_rows("plan:202608/a.md")[0]["uses"] == 3

    store.upsert_row({**prompt_ref, "uses": 1})
    assert store.load_artifact_rows("plan:202608/a.md")[0]["uses"] == 3


def test_derived_bead_endpoint_upsert_does_not_increment_uses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    plans = tmp_path / "plans"
    plans.mkdir()
    with BeadProject.init(tmp_path / "beads") as project:
        issue = project.create("Plan bead", IssueType.PLAN)
        store = ArtifactLinkStore(
            project_key="gh_sase-org__sase",
            sidecar_roots={"plan": plans},
            beads_dir=project.beads_dir,
        )
        row = _row(
            source="plan:202608/a.md",
            relation="implements",
            target=f"bead:{issue.id}",
            origin="derived",
            description="derived from the plan's `bead_id:` frontmatter field",
            created_by="sase",
        )

        store.upsert_row(row)
        second = store.upsert_row(row)
        rows = store.load_artifact_rows(f"bead:{issue.id}")

    assert second["beads_changed"] is False
    assert len(rows) == 1
    assert rows[0]["uses"] == 1


def test_undirected_related_is_idempotent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _store(tmp_path, monkeypatch)
    forward = _row(
        source="plan:202608/a.md",
        relation="related",
        target="plan:202608/b.md",
        description="first",
    )
    reverse = _row(
        source="plan:202608/b.md",
        relation="related",
        target="plan:202608/a.md",
        description="shares the ACE-TUI flake root cause",
    )
    added = store.upsert_row(forward)
    updated = store.upsert_row(reverse)

    assert added["kind"] == "added"
    assert updated["kind"] == "updated"
    rows = store.load_artifact_rows("plan:202608/a.md")
    assert len(rows) == 1
    assert rows[0]["description"] == "shares the ACE-TUI flake root cause"


def test_reserved_relation_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _store(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="sase bead dep"):
        store.upsert_row(
            _row(source="bead:sase-a", relation="blocks", target="bead:sase-b")
        )


def test_remove_rows_drops_every_edge_between_a_pair(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _store(tmp_path, monkeypatch)
    store.upsert_row(_row())
    store.upsert_row(_row(relation="related", description="shares a root cause"))
    removed = store.remove_rows("plan:202608/a.md", "plan:202608/b.md")

    assert {row["relation"] for row in removed} == {"implements", "related"}
    assert store.load_artifact_rows("plan:202608/a.md") == ()
    assert store.load_aggregate()["rows"] == []


def test_remove_rows_can_target_one_relation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _store(tmp_path, monkeypatch)
    store.upsert_row(_row())
    store.upsert_row(_row(relation="related", description="shares a root cause"))
    removed = store.remove_rows(
        "plan:202608/a.md", "plan:202608/b.md", relation="implements"
    )

    assert [row["relation"] for row in removed] == ["implements"]
    remaining = store.load_artifact_rows("plan:202608/a.md")
    assert len(remaining) == 1
    assert remaining[0]["relation"] == "related"


def test_file_file_row_persists_in_the_aggregate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _store(tmp_path, monkeypatch)
    store.upsert_row(
        _row(
            source="file:explicit:0123456789abcdef01234567",
            relation="related",
            target="file:default:abcdef0123456789abcdef01",
            description="same diagram family",
        )
    )

    assert list((tmp_path / "plans").rglob("*.json")) == []
    rows = store.load_aggregate()["rows"]
    assert len(rows) == 1
    assert rows[0]["source_ref"] == "file:explicit:0123456789abcdef01234567"


def test_upsert_canonicalizes_historical_aliases(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _store(tmp_path, monkeypatch)
    store.upsert_row(
        _row(
            source="plans:202608/a.md",
            relation="implements",
            target="@plan:202608/b.md",
        )
    )
    payload = json.loads(_plan_index(tmp_path, "a.md").read_text(encoding="utf-8"))
    assert payload["rows"][0]["source_ref"] == "plan:202608/a.md"
    assert payload["rows"][0]["target_ref"] == "plan:202608/b.md"
