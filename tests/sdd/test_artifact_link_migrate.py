from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.sdd.artifact_link_migrate import migrate_links_tree, migrate_v1_index_to_v2
from sase.sdd.referenced_by_index import read_referenced_by_index

_FIXTURES = Path(__file__).parent / "fixtures" / "referenced_by_v1"
_LIVE_NAME = "live_monitor_followup_wait_release.json"
_CORPUS = (
    _LIVE_NAME,
    "artifact_ref_contract.json",
    "research_link_graph.json",
    "multi_row.json",
)


def _load_fixture(name: str) -> dict[object, object]:
    return json.loads((_FIXTURES / name).read_text(encoding="utf-8"))


def test_v1_reader_still_loads_the_live_index() -> None:
    payload = _load_fixture(_LIVE_NAME)

    assert payload["schema_version"] == 1
    assert payload["artifact_id"] == "plan:202608/monitor_followup_wait_release.md"
    assert payload["rows"][0]["agent"] == "bbugyi200.athena.002--1"


@pytest.mark.parametrize("name", _CORPUS)
def test_v1_fixtures_round_trip_to_v2_cites_rows(name: str) -> None:
    payload = _load_fixture(name)
    migrated = migrate_v1_index_to_v2(payload)

    assert migrated["schema_version"] == 2
    assert migrated["artifact_ref"]
    assert len(migrated["rows"]) == len(payload["rows"])
    for original, row in zip(payload["rows"], migrated["rows"], strict=True):
        assert row["relation"] == "cites"
        assert row["origin"] == "prompt_ref"
        assert row["source_ref"] == f"agent:{original['agent']}"
        assert row["target_ref"] == migrated["artifact_ref"]
        assert row["uses"] == original["uses"]
        assert row["created_by"] == original["agent"]
        assert "Cited in launch prompt" not in row["description"]
        assert original["canonical_ref"].lstrip("@") in row["description"] or (
            original["published"] in row["description"]
        )


def test_live_v1_index_migrates_to_agent_cites_row() -> None:
    migrated = migrate_v1_index_to_v2(_load_fixture(_LIVE_NAME))
    row = migrated["rows"][0]

    assert migrated["artifact_ref"] == ("plan:202608/monitor_followup_wait_release.md")
    assert row["source_ref"] == "agent:bbugyi200.athena.002--1"
    assert row["uses"] == 1
    assert row["created_at"] == "2026-08-13T00:00:00Z"


def test_migrate_links_tree_rewrites_v1_and_skips_v2(tmp_path: Path) -> None:
    links = tmp_path / "links" / "202608"
    links.mkdir(parents=True)
    v1_path = links / "live.md.json"
    v2_path = links / "already.md.json"
    v1_path.write_text(
        json.dumps(_load_fixture(_LIVE_NAME), indent=2) + "\n",
        encoding="utf-8",
    )
    v2_path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "artifact_ref": "plan:202608/already.md",
                "rows": [],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    before_v2 = v2_path.read_text(encoding="utf-8")

    dry = migrate_links_tree(tmp_path, write=False)
    assert dry == (v1_path,)
    assert json.loads(v1_path.read_text(encoding="utf-8"))["schema_version"] == 1

    written = migrate_links_tree(tmp_path, write=True)
    assert written == (v1_path,)
    migrated = json.loads(v1_path.read_text(encoding="utf-8"))
    assert migrated["schema_version"] == 2
    assert migrated["rows"][0]["relation"] == "cites"
    assert v2_path.read_text(encoding="utf-8") == before_v2
    with pytest.raises(RuntimeError, match="unsupported"):
        read_referenced_by_index(v1_path)
