"""Sanitized LinkIndex parity oracle for bead:sase-1kj.8.1.1."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from sase.ace.tui.relations.link_index import _build_link_index
from tests.perf.artifact_link_index_bench import (
    FIXTURE_CHIPS_PATH,
    SYNTHETIC_SCALE_ROWS,
    build_synthetic_scale_rows,
    fixture_snapshot,
    identity_from_payload,
    load_fixture_input,
    parity_diff,
    pinned_identity,
    serialize_link_index,
    write_fixture_goldens,
)


def test_parity_fixture_pins_every_link_chip_and_target_field() -> None:
    payload = load_fixture_input()
    snapshot = fixture_snapshot(payload)
    expected = json.loads(FIXTURE_CHIPS_PATH.read_text(encoding="utf-8"))
    with pinned_identity(identity_from_payload(payload)):
        actual = serialize_link_index(_build_link_index(snapshot), snapshot.rows)
    diffs = parity_diff(actual, expected)
    assert diffs == [], "\n".join(diffs[:50])


def test_parity_fixture_skips_empty_refs_and_keeps_malformed_endpoints() -> None:
    payload = load_fixture_input()
    snapshot = fixture_snapshot(payload)
    with pinned_identity(identity_from_payload(payload)):
        index = _build_link_index(snapshot)
    assert index.chips_for("") == ()
    assert index.chips_for("   ") == ()
    malformed = index.chips_for("not-a-ref")
    assert malformed
    assert malformed[0].neighbor_ref == "bead:sase-1"
    assert index.target_for("not-a-ref") is None


def test_parity_fixture_first_wins_equal_uses_and_max_uses_unequal() -> None:
    payload = load_fixture_input()
    snapshot = fixture_snapshot(payload)
    with pinned_identity(identity_from_payload(payload)):
        index = _build_link_index(snapshot)
    cites = index.chips_for("agent:worker")
    plan_chips = [chip for chip in cites if chip.neighbor_ref == "plan:202608/x.md"]
    assert len(plan_chips) == 1
    assert plan_chips[0].uses == 5
    assert plan_chips[0].why == "high uses wins"
    related = [
        chip
        for chip in index.chips_for("file:doc")
        if chip.neighbor_ref == "file:other"
    ]
    assert len(related) == 1
    assert related[0].why == "first equal uses"


def test_parity_fixture_alias_collision_does_not_shadow_canonical() -> None:
    payload = load_fixture_input()
    snapshot = fixture_snapshot(payload)
    with pinned_identity(identity_from_payload(payload)):
        index = _build_link_index(snapshot)
    assert index.chips_for("ref:plan:202608/x.md")[0].relation == "cites"
    assert index.chips_for("plan:202608/x.md")[0].relation == "related"
    assert index.chips_for("agent:athena.foo") == index.chips_for("agent:foo")
    full = "stitch:sase@0123456789abcdef0123456789abcdef01234567"
    assert index.chips_for("stitch:sase@0123456") == index.chips_for(full)


def test_parity_fixture_self_edge_and_projected_writability() -> None:
    payload = load_fixture_input()
    snapshot = fixture_snapshot(payload)
    with pinned_identity(identity_from_payload(payload)):
        index = _build_link_index(snapshot)
    self_chips = index.chips_for("bead:sase-self")
    assert len(self_chips) == 2
    assert {chip.this_is_source for chip in self_chips} == {True, False}
    awaits = index.chips_for("agent:alice.athena.9w")
    assert awaits
    assert awaits[0].writable is False
    assert awaits[0].origin == "projected"


def test_write_fixture_goldens_is_idempotent_with_current_code(tmp_path: Path) -> None:
    dest = tmp_path / "artifact_link_parity"
    dest.mkdir()
    shutil.copy(FIXTURE_CHIPS_PATH.parent / "input.json", dest / "input.json")
    write_fixture_goldens(fixture_dir=dest)
    committed = json.loads(FIXTURE_CHIPS_PATH.read_text(encoding="utf-8"))
    written = json.loads((dest / "expected_chips.json").read_text(encoding="utf-8"))
    assert parity_diff(written, committed) == []


def test_synthetic_scale_builder_matches_documented_45k_shape() -> None:
    rows = build_synthetic_scale_rows()
    assert len(rows) == SYNTHETIC_SCALE_ROWS
    assert rows[0]["source_ref"].startswith("bead:sase-syn-")
    assert rows[-1]["relation"] in {
        "related",
        "cites",
        "implements",
        "read",
        "derives-from",
    }
