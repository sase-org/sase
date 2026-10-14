"""Fast smoke coverage for the artifact-link index bench helper."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.ace.tui.relations.link_index import _build_link_index
from tests.perf.artifact_link_index_bench import (
    FIXTURE_INPUT_PATH,
    SYNTHETIC_SCALE_ROWS,
    build_synthetic_scale_rows,
    consume_eager_index,
    fixture_patches,
    fixture_snapshot,
    identity_from_payload,
    input_hash,
    load_fixture_input,
    load_saved_aggregate,
    measure_snapshot,
    parity_diff,
    pinned_identity,
    serialize_link_index,
    snapshot_from_saved_aggregate,
)


def test_measure_snapshot_records_required_phases_on_the_parity_fixture() -> None:
    payload = load_fixture_input()
    snapshot = fixture_snapshot(payload)
    patches = fixture_patches(payload)
    with pinned_identity(identity_from_payload(payload)):
        report = measure_snapshot(
            snapshot,
            patches=patches,
            query_refs=list(payload["query_refs"]),
        )
    phases = report["phases"]
    for name in (
        "cold_build_link_index",
        "eager_consume",
        "full_patch_projection",
        "input_load",
        "public_cold_link_index_for_snapshot",
        "representative_queries",
        "warm_reuse_link_index_for_snapshot",
    ):
        assert phases[name]["wall_s"] >= 0.0
        assert phases[name]["cpu_s"] >= 0.0
    assert report["input_hash"] == input_hash(snapshot.rows)
    assert report["counts"]["raw_row_count"] == len(payload["rows"])
    assert report["host"]["python_version"]
    assert report["host"]["sase_core_revision"]
    assert "loadavg" in report["host"]
    warm = phases["warm_reuse_link_index_for_snapshot"]["wall_s"]
    cold = phases["public_cold_link_index_for_snapshot"]["wall_s"]
    assert warm <= cold or warm < 0.05


def test_saved_aggregate_round_trip_preserves_rows(tmp_path: Path) -> None:
    payload = load_fixture_input()
    snapshot = fixture_snapshot(payload)
    saved = {
        "rows": [dict(row) for row in snapshot.rows],
        "schema_version": 2,
        "source_key": ["artifact-link-parity"],
    }
    path = tmp_path / "aggregate.json"
    path.write_text(json.dumps(saved), encoding="utf-8")
    loaded = load_saved_aggregate(path)
    assert [dict(row) for row in loaded.rows] == [dict(row) for row in snapshot.rows]
    assert loaded.source_key == ("artifact-link-parity",)


def test_parity_diff_reports_chip_field_mismatch() -> None:
    diffs = parity_diff({"uses": 1}, {"uses": 5})
    assert diffs == ["$.uses: 1 != 5"]


def test_eager_consume_counts_match_serialized_index() -> None:
    payload = load_fixture_input()
    snapshot = fixture_snapshot(payload)
    with pinned_identity(identity_from_payload(payload)):
        index = _build_link_index(snapshot)
        counts = consume_eager_index(index, snapshot.rows)
        serialized = serialize_link_index(index, snapshot.rows)
    assert counts["ref_count"] == len(serialized["by_ref"])
    assert counts["target_count"] == len(serialized["targets_by_ref"])
    assert counts["chip_count"] == sum(
        len(chips) for chips in serialized["by_ref"].values()
    )


def test_synthetic_builder_count_constant_is_45000() -> None:
    assert SYNTHETIC_SCALE_ROWS == 45_000
    assert FIXTURE_INPUT_PATH.is_file()
    assert len(build_synthetic_scale_rows(3)) == 3


def test_snapshot_from_saved_aggregate_rejects_non_list_rows() -> None:
    with pytest.raises(ValueError, match="must be a list"):
        snapshot_from_saved_aggregate({"rows": {}})
