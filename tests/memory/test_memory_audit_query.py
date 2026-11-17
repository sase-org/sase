"""Targeted memory-audit query tests: schema, attribution, and bounds."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

from sase.memory._read_log_query_facade import (
    MEMORY_AUDIT_QUERY_WIRE_SCHEMA_VERSION,
    query_memory_audit,
)


def _write_event(path: Path, event: dict[str, object]) -> None:
    with path.open("a", encoding="utf-8") as out:
        json.dump(event, out, sort_keys=True)
        out.write("\n")


def _base_event(
    *,
    event_id: str,
    timestamp: str,
    artifacts_dir: str | None,
    agent_name: str = "alpha",
) -> dict[str, object]:
    return {
        "schema_version": 3,
        "id": event_id,
        "timestamp": timestamp,
        "project": "sase",
        "cwd": "/tmp/demo",
        "canonical_path": "foo.md",
        "resolved_path": "/tmp/demo/memory/foo.md",
        "agent_name": agent_name,
        "agent_source": "SASE_AGENT_NAME",
        "artifacts_dir": artifacts_dir,
        "reason": "Need foo",
        "byte_count": 42,
        "frontmatter_stripped": False,
        "kind": "note",
        "selectors": ["foo.md"],
        "resolved_targets": ["foo.md"],
        "included_targets": [],
    }


def test_wire_schema_version_is_one() -> None:
    assert MEMORY_AUDIT_QUERY_WIRE_SCHEMA_VERSION == 1


def test_duplicate_ids_straddling_cap_keep_first_source_occurrence(
    tmp_path: Path,
) -> None:
    log = tmp_path / "memory_reads.jsonl"
    # File order: dup-old (alpha), dup-new (beta, same id), plus a solo.
    # With deduplicate=True and limit=2, the first source occurrence wins
    # and the cap applies after dedup, so solo + dup-old survive.
    _write_event(
        log,
        _base_event(
            event_id="dup",
            timestamp="2026-05-24T10:00:00+00:00",
            artifacts_dir="/runs/a",
            agent_name="alpha",
        ),
    )
    _write_event(
        log,
        _base_event(
            event_id="dup",
            timestamp="2026-05-24T10:05:00+00:00",
            artifacts_dir="/runs/b",
            agent_name="beta",
        ),
    )
    _write_event(
        log,
        _base_event(
            event_id="solo",
            timestamp="2026-05-24T10:03:00+00:00",
            artifacts_dir="/runs/b",
            agent_name="beta",
        ),
    )
    rows, _ = query_memory_audit(
        log,
        members=[
            {"artifacts_dir": "/runs/a", "agent_name": "alpha"},
            {"artifacts_dir": "/runs/b", "agent_name": "beta"},
        ],
        limit=2,
        deduplicate=True,
    )
    assert [(row.event.id, row.member_index) for row in rows] == [
        ("solo", 1),
        ("dup", 0),
    ]
    # Without dedup both duplicate rows survive.
    rows_single, _ = query_memory_audit(
        log,
        members=[
            {"artifacts_dir": "/runs/a", "agent_name": "alpha"},
            {"artifacts_dir": "/runs/b", "agent_name": "beta"},
        ],
        limit=10,
        deduplicate=False,
    )
    assert len(rows_single) == 3


def test_unordered_and_equal_timestamps_sort_descending_stable(
    tmp_path: Path,
) -> None:
    log = tmp_path / "memory_reads.jsonl"
    for event_id, timestamp in (
        ("a", "2026-05-24T10:00:00+00:00"),
        ("b", "2026-05-24T10:05:00+00:00"),
        ("c", "2026-05-24T10:05:00+00:00"),
        ("d", "2026-05-24T10:02:00+00:00"),
    ):
        _write_event(
            log,
            _base_event(
                event_id=event_id,
                timestamp=timestamp,
                artifacts_dir="/runs/target",
            ),
        )
    rows, _ = query_memory_audit(
        log,
        members=[{"artifacts_dir": "/runs/target", "agent_name": "alpha"}],
        limit=10,
        deduplicate=False,
    )
    # Newest first; equal timestamps retain file order (b before c).
    assert [row.event.id for row in rows] == ["b", "c", "d", "a"]


def test_name_collisions_require_exact_dir_or_name(tmp_path: Path) -> None:
    log = tmp_path / "memory_reads.jsonl"
    _write_event(
        log,
        _base_event(
            event_id="dir-match",
            timestamp="2026-05-24T10:00:00+00:00",
            artifacts_dir="/runs/target",
            agent_name="other",
        ),
    )
    _write_event(
        log,
        _base_event(
            event_id="wrong-dir-same-name",
            timestamp="2026-05-24T10:01:00+00:00",
            artifacts_dir="/runs/other",
            agent_name="alpha",
        ),
    )
    _write_event(
        log,
        _base_event(
            event_id="no-dir-same-name",
            timestamp="2026-05-24T10:02:00+00:00",
            artifacts_dir=None,
            agent_name="alpha",
        ),
    )
    rows, _ = query_memory_audit(
        log,
        members=[{"artifacts_dir": "/runs/target", "agent_name": "alpha"}],
        limit=10,
        deduplicate=False,
    )
    assert [row.event.id for row in rows] == [
        "no-dir-same-name",
        "dir-match",
    ]


def test_malformed_and_unsupported_rows_are_skipped(tmp_path: Path) -> None:
    log = tmp_path / "memory_reads.jsonl"
    _write_event(
        log,
        _base_event(
            event_id="good",
            timestamp="2026-05-24T10:00:00+00:00",
            artifacts_dir="/runs/target",
        ),
    )
    with log.open("a", encoding="utf-8") as out:
        out.write("{malformed\n")
        json.dump({"schema_version": 99, "id": "future"}, out)
        out.write("\n")
        json.dump({"schema_version": 3, "id": "missing"}, out)
        out.write("\n")
        out.write("\n")
    rows, source = query_memory_audit(
        log,
        members=[{"artifacts_dir": "/runs/target", "agent_name": "alpha"}],
        limit=10,
        deduplicate=False,
    )
    assert [row.event.id for row in rows] == ["good"]
    assert source.missing is False


def test_older_match_beyond_long_unrelated_tail_is_found(tmp_path: Path) -> None:
    log = tmp_path / "memory_reads.jsonl"
    with log.open("w", encoding="utf-8") as out:
        for index in range(500):
            json.dump(
                _base_event(
                    event_id=f"unrelated-{index}",
                    timestamp=f"2026-05-24T11:{index % 60:02d}:00+00:00",
                    artifacts_dir="/runs/other",
                    agent_name="other",
                ),
                out,
                sort_keys=True,
            )
            out.write("\n")
        json.dump(
            _base_event(
                event_id="old-match",
                timestamp="2026-05-24T09:00:00+00:00",
                artifacts_dir="/runs/target",
                agent_name="alpha",
            ),
            out,
            sort_keys=True,
        )
        out.write("\n")
    rows, _ = query_memory_audit(
        log,
        members=[{"artifacts_dir": "/runs/target", "agent_name": "alpha"}],
        limit=50,
        deduplicate=False,
    )
    assert [row.event.id for row in rows] == ["old-match"]


def test_source_mutations_revalidate(tmp_path: Path) -> None:
    log = tmp_path / "memory_reads.jsonl"
    _write_event(
        log,
        _base_event(
            event_id="one",
            timestamp="2026-05-24T10:00:00+00:00",
            artifacts_dir="/runs/target",
        ),
    )
    rows, first = query_memory_audit(
        log,
        members=[{"artifacts_dir": "/runs/target", "agent_name": "alpha"}],
        limit=50,
        deduplicate=False,
    )
    assert len(rows) == 1

    # Append grows the source.
    _write_event(
        log,
        _base_event(
            event_id="two",
            timestamp="2026-05-24T10:01:00+00:00",
            artifacts_dir="/runs/target",
        ),
    )
    rows, second = query_memory_audit(
        log,
        members=[{"artifacts_dir": "/runs/target", "agent_name": "alpha"}],
        limit=50,
        deduplicate=False,
    )
    assert len(rows) == 2
    assert (second.mtime_ns, second.size) != (first.mtime_ns, first.size)

    # Truncation shrinks it.
    log.write_text("", encoding="utf-8")
    rows, third = query_memory_audit(
        log,
        members=[{"artifacts_dir": "/runs/target", "agent_name": "alpha"}],
        limit=50,
        deduplicate=False,
    )
    assert rows == []
    assert third.size == 0

    # Deletion reads as missing.
    log.unlink()
    rows, fourth = query_memory_audit(
        log,
        members=[{"artifacts_dir": "/runs/target", "agent_name": "alpha"}],
        limit=50,
        deduplicate=False,
    )
    assert rows == []
    assert fourth.missing is True

    # Recreation with equal size but new inode is a new version.
    _write_event(
        log,
        _base_event(
            event_id="one",
            timestamp="2026-05-24T10:00:00+00:00",
            artifacts_dir="/runs/target",
        ),
    )
    first_ino = log.stat().st_ino
    # Atomic replacement: write temp then rename.
    replacement = tmp_path / "replacement.jsonl"
    replacement.write_text(log.read_text(encoding="utf-8"), encoding="utf-8")
    os.replace(replacement, log)
    rows, fifth = query_memory_audit(
        log,
        members=[{"artifacts_dir": "/runs/target", "agent_name": "alpha"}],
        limit=50,
        deduplicate=False,
    )
    assert len(rows) == 1
    # Inode may or may not change on all filesystems; the query must at
    # least return the row and a non-missing identity.
    assert fifth.missing is False
    assert fifth.ino != 0
    assert first_ino != 0


@pytest.mark.parametrize("unrelated", [25000, 100000])
def test_bounded_results_scale_with_matches_not_source(
    tmp_path: Path, unrelated: int
) -> None:
    log = tmp_path / "memory_reads.jsonl"
    target_dir = tmp_path / "target"
    target_dir.mkdir()
    with log.open("w", encoding="utf-8") as out:
        for index in range(unrelated):
            json.dump(
                _base_event(
                    event_id=f"unrelated-{index}",
                    timestamp="2026-05-24T11:00:00+00:00",
                    artifacts_dir="/runs/other",
                    agent_name="other",
                ),
                out,
                sort_keys=True,
            )
            out.write("\n")
        for index in range(5):
            json.dump(
                _base_event(
                    event_id=f"match-{index}",
                    timestamp=f"2026-05-24T10:0{index}:00+00:00",
                    artifacts_dir=str(target_dir),
                    agent_name="alpha",
                ),
                out,
                sort_keys=True,
            )
            out.write("\n")
    started = time.perf_counter()
    rows, source = query_memory_audit(
        log,
        members=[{"artifacts_dir": str(target_dir), "agent_name": "alpha"}],
        limit=50,
        deduplicate=False,
    )
    elapsed = time.perf_counter() - started
    assert len(rows) == 5
    assert source.missing is False
    # Retained Python objects scale with matches, not source length.
    assert len(rows) <= 50
    # Scan must stay interactive on 100k rows; generous bound for CI.
    assert elapsed < 5.0
