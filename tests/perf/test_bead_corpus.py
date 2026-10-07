"""Validity, determinism, and shape tests for the synthetic bead corpus."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

import sase_core_rs
from tests.perf._bead_corpus import generate_corpus, mint_event_id
from tests.perf._bead_scale_copy import copy_store_scaled


def _read_streams(beads_dir: Path) -> dict[str, list[dict]]:
    streams = {}
    for path in sorted((beads_dir / "events" / "streams").glob("*.jsonl")):
        with open(path, encoding="utf-8") as handle:
            streams[path.stem] = [json.loads(line) for line in handle if line.strip()]
    return streams


def _tree_bytes(root: Path) -> dict[str, bytes]:
    blobs = {}
    for path in sorted(root.rglob("*")):
        if ".git" in path.parts or not path.is_file():
            continue
        blobs[str(path.relative_to(root))] = path.read_bytes()
    return blobs


def test_mint_matches_core_issue_created(tmp_path: Path) -> None:
    """The Python mint reproduces core's event IDs on real mutations."""
    from sase.bead.model import IssueType
    from sase.core import bead_mutation_facade as mutations

    mutations.init_store(tmp_path, "beads", issue_prefix="probe", owner="owner")
    beads = str(tmp_path / "beads")
    mutations.create(
        beads,
        title="Mint probe",
        issue_type=IssueType.TASK,
        task_type="bug",
        size="small",
        external_ref="bench-ext-00001",
        now="2026-01-01T00:00:00Z",
        created_by="tester",
    )
    line = next(iter(open(tmp_path / "beads" / "events" / "streams" / "probe-1.jsonl")))
    event = json.loads(line)
    assert (
        mint_event_id(
            "probe-1",
            1,
            event["timestamp"],
            event["actor"],
            event["operation"],
            event["issue_id"],
            event["payload"],
        )
        == event["event_id"]
    )


def test_generated_store_is_valid(tmp_path: Path) -> None:
    """The reducer accepts the corpus and the doctor reports no issues."""
    beads_dir = tmp_path / "corpus"
    shape = generate_corpus(beads_dir, scale=0.02, seed=11)
    assert shape["beads"] > 100

    issues = sase_core_rs.bead_read_store(str(beads_dir))
    assert len(issues) == shape["beads"]
    assert sase_core_rs.bead_doctor(str(beads_dir)) == ["OK: no issues found"]

    manifest = json.loads((beads_dir / "events" / "manifest.json").read_text())
    streams = _read_streams(beads_dir)
    assert manifest["stream_count"] == len(streams) == shape["streams"]

    appended: set[str] = set()
    for stream_id, events in streams.items():
        assert events, f"empty stream {stream_id}"
        first = events[0]
        assert first["operation"] == "issue_created"
        assert first["issue_id"] == stream_id or first["issue_id"].startswith(
            stream_id + "."
        )
        ordinals = [event["event_id"].split(":")[1] for event in events]
        assert ordinals == [f"{num:06d}" for num in range(1, len(events) + 1)]
        for event in events:
            if event["operation"] == "note_appended":
                appended.add(event["event_id"])
    for stream_id, events in streams.items():
        for event in events:
            if event["operation"] in ("note_edited", "note_removed"):
                assert event["payload"]["note_id"] in appended


def test_generated_store_is_deterministic(tmp_path: Path) -> None:
    """The same parameters always yield byte-identical store files."""
    first = tmp_path / "first"
    second = tmp_path / "second"
    generate_corpus(first, scale=0.02, seed=12)
    generate_corpus(second, scale=0.02, seed=12)
    assert _tree_bytes(first) == _tree_bytes(second)

    third = tmp_path / "third"
    generate_corpus(third, scale=0.02, seed=13)
    assert _tree_bytes(first) != _tree_bytes(third)


def test_generated_shape_matches_research(tmp_path: Path) -> None:
    """Type mix, closure rate, and the required phenomena hold."""
    beads_dir = tmp_path / "corpus"
    shape = generate_corpus(beads_dir, scale=0.1, seed=14)
    total = shape["beads"]
    assert total > 500
    # Removed beads vanish from reads but keep their stream files.
    assert shape["streams"] == shape["plans"] + shape["tasks"] + shape["removed"]
    assert 0.65 < shape["phases"] / total < 0.77
    assert 0.12 < shape["plans"] / total < 0.18
    assert 0.13 < shape["tasks"] / total < 0.20
    assert 0.85 < shape["closed_fraction"] < 0.95
    assert 5.0 < shape["events_per_bead"] < 8.5

    issues = {
        issue["id"]: issue for issue in sase_core_rs.bead_read_store(str(beads_dir))
    }
    live_with_closed_phases = sum(
        1
        for issue in issues.values()
        if issue["issue_type"] == "plan"
        and issue["status"] != "closed"
        and any(
            child["parent_id"] == issue["id"] and child["status"] == "closed"
            for child in issues.values()
            if child["issue_type"] == "phase"
        )
    )
    assert live_with_closed_phases >= 5

    streams = _read_streams(beads_dir)
    close_at: dict[str, datetime] = {}
    late: list[str] = []
    edited = removed_notes = plus_ones = external_refs = removed = 0
    for events in streams.values():
        for event in events:
            if event["operation"] == "issue_closed":
                close_at[event["issue_id"]] = datetime.fromisoformat(
                    event["timestamp"].replace("Z", "+00:00")
                )
            if event["operation"] == "note_edited":
                edited += 1
            if event["operation"] == "note_removed":
                removed_notes += 1
            if event["operation"] == "task_plus_one_recorded":
                plus_ones += 1
            if event["operation"] == "issue_removed":
                removed += 1
            if event["operation"] == "issue_created" and event["payload"]["issue"].get(
                "external_ref"
            ):
                external_refs += 1
    for events in streams.values():
        for event in events:
            if event["operation"] in ("link_added", "issue_updated", "note_appended"):
                shut = close_at.get(event["issue_id"])
                if shut is not None:
                    when = datetime.fromisoformat(
                        event["timestamp"].replace("Z", "+00:00")
                    )
                    if (when - shut).days >= 7:
                        late.append(event["event_id"])
                        break
    assert late, "expected post-close events landing 7+ days after close"
    assert edited > 0 and removed_notes > 0
    assert plus_ones > 0 and external_refs > 0 and removed > 0

    refs = [
        event["payload"]["issue"].get("external_ref")
        for events in streams.values()
        for event in events
        if event["operation"] == "issue_created"
    ]
    refs = [ref for ref in refs if ref]
    assert len(set(refs)) == len(refs)


def test_copy_scaled_doubles_history(tmp_path: Path) -> None:
    """Prefix-renamed copies multiply beads/streams/events without edits."""
    source = tmp_path / "source"
    generate_corpus(source, scale=0.02, seed=15)
    before = _tree_bytes(source)

    dest = tmp_path / "scaled"
    shape = copy_store_scaled(source, dest, copies=2)
    assert _tree_bytes(source) == before
    assert shape["copies"] == 2
    src_beads = len(sase_core_rs.bead_read_store(str(source)))
    src_streams = len(list((source / "events" / "streams").glob("*.jsonl")))
    assert shape["beads"] == 2 * src_beads
    assert shape["streams"] == 2 * src_streams
    assert shape["prefixes"][0] == "bench"
    assert len(shape["prefixes"][1]) == len("bench")
    assert shape["prefixes"][1] != "bench"
    assert sase_core_rs.bead_doctor(str(dest)) == ["OK: no issues found"]
    issues = sase_core_rs.bead_read_store(str(dest))
    assert len(issues) == shape["beads"]

    seen_prefixes = {issue["id"].split("-")[0] for issue in issues}
    assert seen_prefixes == set(shape["prefixes"])
    renamed_lines = 0
    for path in (dest / "events" / "streams").glob("*.jsonl"):
        with open(path, encoding="utf-8") as handle:
            for raw in handle:
                event = json.loads(raw)
                assert event["event_id"].split(":")[0] == path.stem
                if path.stem.startswith(shape["prefixes"][1] + "-"):
                    renamed_lines += 1
                    # Re-minted digests match the core algorithm exactly.
                    assert (
                        mint_event_id(
                            path.stem,
                            int(event["event_id"].split(":")[1]),
                            event["timestamp"],
                            event["actor"],
                            event["operation"],
                            event["issue_id"],
                            event["payload"],
                        )
                        == event["event_id"]
                    )
    assert renamed_lines > 0


def test_copy_refuses_bad_destinations(tmp_path: Path) -> None:
    """Copies never land inside the source or a sidecar clone."""
    source = tmp_path / "source"
    generate_corpus(source, scale=0.01, seed=16)

    with pytest.raises(ValueError, match="inside itself"):
        copy_store_scaled(source, source / "nested", copies=1)

    existing = tmp_path / "existing"
    existing.mkdir()
    with pytest.raises(ValueError, match="existing"):
        copy_store_scaled(source, existing, copies=1)

    with pytest.raises(ValueError, match="copies must be"):
        copy_store_scaled(source, tmp_path / "zero", copies=0)

    sidecar = tmp_path / "ws"
    (sidecar / "sdd" / "beads" / "events").mkdir(parents=True)
    (sidecar / "sdd" / "beads" / "events" / "manifest.json").write_text("{}")
    (sidecar / "sdd" / "beads" / "config.json").write_text("{}")
    (sidecar / ".git").mkdir()
    with pytest.raises(ValueError, match="sidecar-clone"):
        copy_store_scaled(source, sidecar / "scratch", copies=1)

    # A plain directory that merely contains an sdd/beads store (like $HOME)
    # is not a clone: destinations below it are fine.
    homelike = tmp_path / "home"
    (homelike / "sdd" / "beads" / "events").mkdir(parents=True)
    (homelike / "sdd" / "beads" / "events" / "manifest.json").write_text("{}")
    (homelike / "sdd" / "beads" / "config.json").write_text("{}")
    shape = copy_store_scaled(source, homelike / "scratch", copies=1)
    assert shape["copies"] == 1
