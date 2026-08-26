"""Invariant, precedence, and non-persistence tests for projected rows."""

from __future__ import annotations

import itertools
from pathlib import Path
import time
from typing import Any

import pytest

from sase.sdd._artifact_link_store_support import is_projected_row, store_backed_rows
from sase.sdd.artifact_link_store import ArtifactLinkStore
from tests._conftest_environment import redirect_sase_home
from tests.sdd._artifact_link_store_helpers import _row, _store

_PROJECTED_ROW: dict[str, Any] = {
    "schema_version": 2,
    "source_ref": "stitch:sase@0123456789abcdef0123456789abcdef01234567",
    "relation": "implements",
    "target_ref": "bead:sase-xx",
    "description": "commit trailer names bead sase-xx",
    "origin": "projected",
    "created_by": "projection:stitch-bead",
    "created_at": "2026-08-20T00:00:00Z",
    "uses": 1,
}


def _patch_projected_rows(
    monkeypatch: pytest.MonkeyPatch, rows: tuple[dict[str, Any], ...]
) -> None:
    monkeypatch.setattr(
        "sase.sdd._artifact_link_store_projected.project_link_rows",
        lambda _inputs: rows,
    )


def test_is_projected_row_and_store_backed_rows() -> None:
    manual = _row(origin="manual")
    assert is_projected_row(_PROJECTED_ROW) is True
    assert is_projected_row(manual) is False
    assert store_backed_rows([_PROJECTED_ROW, manual]) == [manual]


def test_bead_neighborhood_excludes_projected_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.bead.project import BeadProject

    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    with BeadProject.init(tmp_path) as project:
        store = ArtifactLinkStore(
            project_key="gh_sase-org__sase",
            sidecar_roots={"plan": tmp_path / "plans"},
            beads_dir=project.beads_dir,
        )
        (tmp_path / "plans").mkdir(exist_ok=True)
        agent_bead_row = dict(_PROJECTED_ROW)
        agent_bead_row["source_ref"] = "agent:alice.athena.9w"
        agent_bead_row["target_ref"] = "bead:sase-xx"
        _patch_projected_rows(monkeypatch, (agent_bead_row,))
        store.rebuild_aggregate()

        assert (
            store._aggregate_only_rows_touching(  # noqa: SLF001
                "bead:sase-xx"
            )
            == []
        )


def test_projected_rows_are_materialized_into_the_aggregate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _store(tmp_path, monkeypatch)
    _patch_projected_rows(monkeypatch, (_PROJECTED_ROW,))

    rebuilt = store.rebuild_aggregate()

    assert _PROJECTED_ROW in rebuilt["rows"]
    assert _PROJECTED_ROW in store.load_aggregate()["rows"]


def test_a_stale_projected_row_disappears_once_its_rule_stops_matching(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _store(tmp_path, monkeypatch)
    _patch_projected_rows(monkeypatch, (_PROJECTED_ROW,))
    store.rebuild_aggregate()
    assert _PROJECTED_ROW in store.load_aggregate()["rows"]

    _patch_projected_rows(monkeypatch, ())
    rebuilt = store.rebuild_aggregate()

    assert rebuilt["rows"] == []
    assert store.load_aggregate()["rows"] == []


def test_a_stored_row_beats_a_projected_row_with_the_same_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _store(tmp_path, monkeypatch)
    manual_pair = _row(
        source="stitch:sase@0123456789abcdef0123456789abcdef01234567",
        relation="implements",
        target="bead:sase-xx",
        origin="manual",
        description="hand-curated: this commit really implements sase-xx",
    )
    colliding_projected = dict(_PROJECTED_ROW)
    _patch_projected_rows(monkeypatch, (colliding_projected,))
    store._upsert_aggregate_row(manual_pair)  # noqa: SLF001 - direct aggregate seed

    rebuilt = store.rebuild_aggregate()

    matching = [
        row
        for row in rebuilt["rows"]
        if row["source_ref"] == manual_pair["source_ref"]
        and row["target_ref"] == manual_pair["target_ref"]
    ]
    assert len(matching) == 1
    assert matching[0]["origin"] == "manual"
    assert matching[0]["description"] == manual_pair["description"]


def test_projected_rows_never_reach_sidecar_or_bead_storage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.bead.project import BeadProject

    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    with BeadProject.init(tmp_path) as project:
        store = ArtifactLinkStore(
            project_key="gh_sase-org__sase",
            sidecar_roots={"plan": tmp_path / "plans"},
            beads_dir=project.beads_dir,
        )
        (tmp_path / "plans").mkdir(exist_ok=True)
        _patch_projected_rows(monkeypatch, (_PROJECTED_ROW,))

        store.rebuild_aggregate()
        assert _PROJECTED_ROW in store.load_aggregate()["rows"]
        assert list((tmp_path / "plans").rglob("*.json")) == []

        counts = store.backfill_bead_endpoint_links()
        assert counts["candidates"] == 0
        assert counts["written"] == 0
        assert list((tmp_path / "plans").rglob("*.json")) == []


def test_load_artifact_rows_excludes_projected_rows_for_an_aggregate_only_ref(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _store(tmp_path, monkeypatch)
    _patch_projected_rows(monkeypatch, (_PROJECTED_ROW,))
    store.rebuild_aggregate()

    assert store.load_artifact_rows(_PROJECTED_ROW["source_ref"]) == ()
    assert _PROJECTED_ROW in store.load_aggregate()["rows"]


def test_stored_link_keys_excludes_projected_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.sdd.artifact_link_backfill import _stored_link_keys

    store = _store(tmp_path, monkeypatch)
    _patch_projected_rows(monkeypatch, (_PROJECTED_ROW,))
    store.rebuild_aggregate()

    assert _stored_link_keys(store) == frozenset()


def test_remove_rows_refuses_to_delete_a_purely_projected_pair(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _store(tmp_path, monkeypatch)
    _patch_projected_rows(monkeypatch, (_PROJECTED_ROW,))
    store.rebuild_aggregate()

    with pytest.raises(ValueError, match="projection:stitch-bead"):
        store.remove_rows(_PROJECTED_ROW["source_ref"], _PROJECTED_ROW["target_ref"])

    # The refusal must be a pure read: nothing was mutated.
    assert _PROJECTED_ROW in store.load_aggregate()["rows"]


def test_remove_rows_still_removes_a_stored_row_sharing_no_identity_with_projected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _store(tmp_path, monkeypatch)
    _patch_projected_rows(monkeypatch, (_PROJECTED_ROW,))
    store.upsert_row(
        _row(source="plan:202608/a.md", relation="related", target="plan:202608/b.md")
    )

    removal = store.remove_rows("plan:202608/a.md", "plan:202608/b.md")

    assert len(removal.rows) == 1
    assert _PROJECTED_ROW in store.load_aggregate()["rows"]


def test_every_aggregate_writer_converges_with_projected_rows_present(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    writers = {
        "rebuild": lambda store: store.rebuild_aggregate(),
        "reconcile": lambda store: store.reconcile_aggregate(),
    }

    def row_set(document: dict[str, Any]) -> set[tuple[str, str, str]]:
        return {
            (row["source_ref"], row["relation"], row["target_ref"])
            for row in document["rows"]
        }

    expected = {
        (
            _PROJECTED_ROW["source_ref"],
            _PROJECTED_ROW["relation"],
            _PROJECTED_ROW["target_ref"],
        ),
    }
    for order in itertools.permutations(writers):
        store = _store(tmp_path / "-".join(order), monkeypatch)
        _patch_projected_rows(monkeypatch, (_PROJECTED_ROW,))

        last: dict[str, Any] = {}
        for name in order:
            last = writers[name](store)

        assert row_set(last) == expected, order
        assert row_set(store.load_aggregate()) == expected, order


def test_volume_smoke_12500_projected_rows_rebuild_inside_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression guard for the plan's measured ~12,500-row projected subgraph.

    Not a tight timing assertion -- the chop that runs this in production has
    a 240-second budget; this only checks for a wall-clock bound with
    generous headroom, per the plan's volume-smoke requirement.
    """

    store = _store(tmp_path, monkeypatch)
    synthetic_rows = tuple(
        {
            "schema_version": 2,
            "source_ref": f"stitch:sase@{i:040x}",
            "relation": "produced-by",
            "target_ref": f"agent:synthetic.athena.agent{i}",
            "description": f"synthetic row {i}",
            "origin": "projected",
            "created_by": "projection:stitch-agent",
            "created_at": "2026-08-20T00:00:00Z",
            "uses": 1,
        }
        for i in range(12_500)
    )
    _patch_projected_rows(monkeypatch, synthetic_rows)

    started = time.monotonic()
    rebuilt = store.rebuild_aggregate()
    elapsed = time.monotonic() - started

    assert len(rebuilt["rows"]) == 12_500
    assert elapsed < 60.0, f"rebuild_aggregate() took {elapsed:.1f}s for 12,500 rows"
