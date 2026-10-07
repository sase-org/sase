"""``write_resolved_store`` projection coverage for projection-off.

Since sase-1h8.11 event stores resolve through streams plus manifest only;
the ``issues.jsonl`` compatibility projection is an on-demand export and is
never rewritten by conflict resolution. Legacy stores without ``events/``
keep today's behavior.
"""

from __future__ import annotations

from pathlib import Path

from sase.bead.conflict_resolver_store_writer import write_resolved_store


def _streams() -> list[dict[str, object]]:
    return [{"stream_id": "sase-1", "root_issue_id": "sase-1", "events": []}]


def test_event_store_resolution_writes_no_projection(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    beads_dir = repo / "beads"
    streams_dir = beads_dir / "events" / "streams"
    streams_dir.mkdir(parents=True)

    written = write_resolved_store(
        beads_dir,
        repo,
        _streams(),
        [{"id": "sase-1"}],
        {},
        set(),
    )

    assert not (beads_dir / "issues.jsonl").exists()
    assert (beads_dir / "events" / "manifest.json").is_file()
    assert (streams_dir / "sase-1.jsonl").is_file()
    assert all("issues.jsonl" not in path for path in written)


def test_legacy_resolution_still_writes_projection(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    beads_dir = repo / "beads"
    beads_dir.mkdir(parents=True)

    written = write_resolved_store(
        beads_dir,
        repo,
        _streams(),
        [{"id": "sase-1"}],
        {},
        set(),
    )

    assert (beads_dir / "issues.jsonl").is_file()
    assert any("issues.jsonl" in path for path in written)
