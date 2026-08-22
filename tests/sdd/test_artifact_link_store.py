from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from sase.sdd.artifact_link_store import (
    ARTIFACT_LINK_ROW_SCHEMA_VERSION,
    ArtifactLinkStore,
    assembled_artifact_relations,
    artifact_link_aggregate_path,
    resolve_artifact_link_project_key,
)
from tests._conftest_environment import redirect_sase_home


def _row(
    source: str = "plan:202608/a.md",
    relation: str = "implements",
    target: str = "plan:202608/b.md",
    *,
    origin: str = "manual",
    description: str = "extends the ref contract this epic landed",
    created_by: str = "bbugyi200.athena.y2",
    created_at: str = "2026-08-18T23:40:00Z",
    uses: int = 1,
) -> dict[str, object]:
    return {
        "schema_version": ARTIFACT_LINK_ROW_SCHEMA_VERSION,
        "source_ref": source,
        "relation": relation,
        "target_ref": target,
        "description": description,
        "origin": origin,
        "created_by": created_by,
        "created_at": created_at,
        "uses": uses,
    }


def _store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ArtifactLinkStore:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    plans = tmp_path / "plans"
    research = tmp_path / "research"
    plans.mkdir()
    research.mkdir()
    return ArtifactLinkStore(
        project_key="gh_sase-org__sase",
        sidecar_roots={"plan": plans, "research": research},
    )


def _plan_index(tmp_path: Path, stem: str) -> Path:
    return tmp_path / "plans" / "links" / "202608" / f"{stem}.json"


def test_assembled_relations_are_builtins_then_plugins_then_config() -> None:
    plugin = {
        "schema_version": 1,
        "slug": "plugin-rel",
        "inverse": "plugin-rel-by",
        "directed": True,
        "written_by": "plugin",
    }
    relations = assembled_artifact_relations(plugins=(plugin,), config=())
    slugs = [item["slug"] for item in relations]
    assert slugs[:6] == [
        "cites",
        "read",
        "related",
        "supersedes",
        "implements",
        "derives-from",
    ]
    assert slugs[-1] == "plugin-rel"


def test_project_key_resolution_maps_provider_slug_to_canonical_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    marker = SimpleNamespace(project_key="sase-org/sase", project_name="sase")
    record = SimpleNamespace(
        project_name="gh_sase-org__sase",
        display_name="sase",
        aliases=[],
    )
    monkeypatch.setattr(
        "sase.workspace_provider.marker.find_marker_from_cwd",
        lambda _cwd: (str(tmp_path), marker),
    )
    monkeypatch.setattr(
        "sase.core.project_lifecycle_facade.list_project_records",
        lambda *_args, **_kwargs: [record],
    )

    assert resolve_artifact_link_project_key(tmp_path) == "gh_sase-org__sase"


def test_invalid_project_key_is_rejected_before_sidecar_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plans = tmp_path / "plans"
    plans.mkdir()
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    with pytest.raises(ValueError, match="invalid project key"):
        ArtifactLinkStore(
            project_key="sase-org/sase",
            sidecar_roots={"plan": plans},
        )
    assert not list(plans.rglob("*.json"))
    assert not list(plans.rglob("*.lock"))


def test_unresolvable_provider_slug_returns_no_project_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    marker = SimpleNamespace(project_key="missing-org/missing", project_name="")
    record = SimpleNamespace(
        project_name="gh_sase-org__sase",
        display_name="sase",
        aliases=[],
    )
    monkeypatch.setattr(
        "sase.workspace_provider.marker.find_marker_from_cwd",
        lambda _cwd: (str(tmp_path), marker),
    )
    monkeypatch.setattr(
        "sase.core.project_lifecycle_facade.list_project_records",
        lambda *_args, **_kwargs: [record],
    )

    assert resolve_artifact_link_project_key(tmp_path) is None


def test_marker_display_name_does_not_become_direct_project_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    marker = SimpleNamespace(project_key="sase-org/sase", project_name="sase")
    monkeypatch.setattr(
        "sase.workspace_provider.marker.find_marker_from_cwd",
        lambda _cwd: (str(tmp_path), marker),
    )
    monkeypatch.setattr(
        "sase.core.project_lifecycle_facade.list_project_records",
        lambda *_args, **_kwargs: [],
    )

    assert resolve_artifact_link_project_key(tmp_path) is None


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


def test_bead_endpoint_is_not_written_to_sidecar_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _store(tmp_path, monkeypatch)
    store.upsert_row(
        _row(source="plan:202608/a.md", relation="related", target="bead:sase-js")
    )

    plan_index = _plan_index(tmp_path, "a.md")
    assert plan_index.is_file()
    assert list((tmp_path / "plans" / "links").rglob("*.json")) == [plan_index]
    rows = store.load_artifact_rows("bead:sase-js")
    assert len(rows) == 1
    assert rows[0]["source_ref"] == "plan:202608/a.md"


def test_bead_bead_row_lives_in_the_event_stream(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.bead.model import IssueType
    from sase.bead.project import BeadProject

    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    with BeadProject.init(tmp_path) as project:
        left = project.create("Left", IssueType.PLAN)
        right = project.create("Right", IssueType.PLAN)
        store = ArtifactLinkStore(
            project_key="gh_sase-org__sase",
            sidecar_roots={"plan": tmp_path / "plans"},
            beads_dir=project.beads_dir,
        )
        (tmp_path / "plans").mkdir(exist_ok=True)
        store.upsert_row(
            _row(
                source=f"bead:{left.id}",
                relation="related",
                target=f"bead:{right.id}",
                description="shares the ACE-TUI flake root cause",
            )
        )

        assert list((tmp_path / "plans").rglob("*.json")) == []
        rows = store.load_artifact_rows(f"bead:{left.id}")
        assert len(rows) == 1
        assert rows[0]["relation"] == "related"
        assert project.show(left.id).links[0].target_ref == f"bead:{right.id}"


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


def test_schema_v1_sidecar_file_is_unsupported_after_graduation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _store(tmp_path, monkeypatch)
    index_path = _plan_index(tmp_path, "monitor_followup_wait_release.md")
    index_path.parent.mkdir(parents=True)
    live = (
        Path(__file__).parent
        / "fixtures"
        / "referenced_by_v1"
        / ("live_monitor_followup_wait_release.json")
    )
    index_path.write_text(live.read_text(encoding="utf-8"), encoding="utf-8")

    with pytest.raises(RuntimeError, match="schema-v1 Referenced By"):
        store.load_artifact_rows("plan:202608/monitor_followup_wait_release.md")
    assert json.loads(index_path.read_text(encoding="utf-8"))["schema_version"] == 1


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


def test_bead_load_includes_aggregate_only_incoming_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.bead.model import IssueType
    from sase.bead.project import BeadProject

    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    with BeadProject.init(tmp_path) as project:
        issue = project.create("Left", IssueType.PLAN)
        store = ArtifactLinkStore(
            project_key="gh_sase-org__sase",
            sidecar_roots={"plan": tmp_path / "plans"},
            beads_dir=project.beads_dir,
        )
        (tmp_path / "plans").mkdir(exist_ok=True)
        store.upsert_row(
            _row(
                source="agent:alice.athena.reviewer",
                relation="cites",
                target=f"bead:{issue.id}",
                origin="prompt_ref",
                description="Prompt citation of the bead.",
                uses=3,
            )
        )

        rows = store.load_artifact_rows(f"bead:{issue.id}")
        assert len(rows) == 1
        assert rows[0]["source_ref"] == "agent:alice.athena.reviewer"
        assert rows[0]["uses"] == 3


def test_bead_owned_rows_skip_a_second_bead_store_reduction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.bead.model import IssueType
    from sase.bead.project import BeadProject

    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    with BeadProject.init(tmp_path) as project:
        left = project.create("Left", IssueType.PLAN)
        store = ArtifactLinkStore(
            project_key="gh_sase-org__sase",
            sidecar_roots={"plan": tmp_path / "plans"},
            beads_dir=project.beads_dir,
        )
        (tmp_path / "plans").mkdir(exist_ok=True)
        owned = _row(
            source=f"bead:{left.id}",
            relation="implements",
            target="plan:202608/a.md",
            description="lands the approved CLI design",
        )
        calls = {"list": 0}
        real = ArtifactLinkStore._list_bead_issues

        def counting(self: ArtifactLinkStore) -> tuple[object, ...]:
            calls["list"] += 1
            return real(self)

        monkeypatch.setattr(ArtifactLinkStore, "_list_bead_issues", counting)
        rows = store.load_artifact_rows(
            f"bead:{left.id}",
            bead_owned_rows=(owned,),
        )
        assert calls["list"] == 0
        assert rows[0]["target_ref"] == "plan:202608/a.md"
        store.load_artifact_rows(f"bead:{left.id}")
        assert calls["list"] == 1


def test_bead_merge_includes_sidecar_and_deduplicates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.bead.model import IssueType
    from sase.bead.project import BeadProject

    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    with BeadProject.init(tmp_path) as project:
        issue = project.create("Left", IssueType.PLAN)
        store = ArtifactLinkStore(
            project_key="gh_sase-org__sase",
            sidecar_roots={"plan": tmp_path / "plans"},
            beads_dir=project.beads_dir,
        )
        (tmp_path / "plans").mkdir(exist_ok=True)
        sidecar = _row(
            source="plan:202608/a.md",
            relation="related",
            target=f"bead:{issue.id}",
            description="plan sidecar row",
        )
        store.upsert_row(sidecar)
        owned = _row(
            source=f"bead:{issue.id}",
            relation="related",
            target="plan:202608/a.md",
            description="bead owned duplicate",
        )
        rows = store.load_artifact_rows(
            f"bead:{issue.id}",
            bead_owned_rows=(owned,),
        )
        related = [row for row in rows if row["relation"] == "related"]
        assert len(related) == 1
        assert related[0]["description"] == "bead owned duplicate"


def test_missing_sidecar_root_is_not_an_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = ArtifactLinkStore(
        project_key="gh_sase-org__sase",
        sidecar_roots={"plan": tmp_path / "missing-plans"},
    )
    assert store.load_artifact_rows("plan:202608/a.md") == ()


def test_malformed_sidecar_index_is_fail_loud(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _store(tmp_path, monkeypatch)
    index_path = _plan_index(tmp_path, "a.md")
    index_path.parent.mkdir(parents=True)
    index_path.write_text("{not-json", encoding="utf-8")
    with pytest.raises((json.JSONDecodeError, RuntimeError)):
        store.load_artifact_rows("plan:202608/a.md")


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
