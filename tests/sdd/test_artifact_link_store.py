from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.feature_flags import FeatureFlag, override_flags
from sase.sdd.artifact_link_store import (
    ARTIFACT_LINK_ROW_SCHEMA_VERSION,
    ArtifactLinkStore,
    ArtifactLinksDisabledError,
    assembled_artifact_relations,
    artifact_link_aggregate_path,
    artifact_links_enabled,
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


def test_flag_defaults_off_and_writes_are_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _store(tmp_path, monkeypatch)
    assert artifact_links_enabled() is False
    with pytest.raises(ArtifactLinksDisabledError, match="artifact_links"):
        store.upsert_row(_row())
    assert not any((tmp_path / "plans").rglob("*.json"))


def test_upsert_writes_both_sidecars_and_rebuilds_aggregate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _store(tmp_path, monkeypatch)
    with override_flags(artifact_links=True):
        assert FeatureFlag.artifact_links
        assert artifact_links_enabled() is True
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
    with override_flags(artifact_links=True):
        store.upsert_row(
            _row(source="plan:202608/a.md", relation="related", target="bead:sase-js")
        )

    plan_index = _plan_index(tmp_path, "a.md")
    assert plan_index.is_file()
    assert list((tmp_path / "plans" / "links").rglob("*.json")) == [plan_index]
    rows = store.load_artifact_rows("bead:sase-js")
    assert len(rows) == 1
    assert rows[0]["source_ref"] == "plan:202608/a.md"


def test_bead_bead_row_lives_only_in_the_aggregate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _store(tmp_path, monkeypatch)
    with override_flags(artifact_links=True):
        store.upsert_row(
            _row(
                source="bead:sase-js",
                relation="related",
                target="bead:sase-ct",
                description="shares the ACE-TUI flake root cause",
            )
        )
        store.rebuild_aggregate()

    assert list((tmp_path / "plans").rglob("*.json")) == []
    aggregate = store.load_aggregate()
    assert len(aggregate["rows"]) == 1
    assert aggregate["rows"][0]["relation"] == "related"


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
    with override_flags(artifact_links=True):
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
    with override_flags(artifact_links=True):
        with pytest.raises(ValueError, match="sase bead dep"):
            store.upsert_row(
                _row(source="bead:sase-a", relation="blocks", target="bead:sase-b")
            )


def test_v1_sidecar_file_migrates_on_flag_on_write(
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

    with override_flags(artifact_links=True):
        store.upsert_row(
            _row(
                source="plan:202608/monitor_followup_wait_release.md",
                relation="implements",
                target="plan:202608/other.md",
            )
        )

    payload = json.loads(index_path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 2
    relations = {row["relation"] for row in payload["rows"]}
    assert relations == {"cites", "implements"}


def test_upsert_canonicalizes_historical_aliases(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _store(tmp_path, monkeypatch)
    with override_flags(artifact_links=True):
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
