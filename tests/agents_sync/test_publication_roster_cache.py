from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase._interruptions import PublicationDrainTimedOut
from sase.agents_sync.publication_roster import (
    HoodRosterSummary,
    read_roster_summary_cache,
    write_roster_summary_cache,
)


def _summary(hood: str) -> HoodRosterSummary:
    return HoodRosterSummary(hood, 2, 1, {"completed": 1, "failed": 1})


def test_cache_round_trip_and_prunes_hoods_missing_from_manifests(
    tmp_path: Path,
) -> None:
    cache_path = tmp_path / "summary-cache.json"
    repo = tmp_path / "sidecar"
    key_foo = ("alice", "athena", "proj", "Project", "foo", "a" * 64)
    key_work = ("alice", "athena", "proj", "Project", "work", "b" * 64)

    cache = read_roster_summary_cache(repo, "proj", path_override=cache_path)
    write_roster_summary_cache(
        cache,
        current_keys={key_foo, key_work},
        additions={key_foo: _summary("foo"), key_work: _summary("work")},
    )
    loaded = read_roster_summary_cache(repo, "proj", path_override=cache_path)
    assert loaded.summaries == {
        key_foo: _summary("foo"),
        key_work: _summary("work"),
    }

    write_roster_summary_cache(
        loaded,
        current_keys={key_foo},
        additions={},
    )
    pruned = read_roster_summary_cache(repo, "proj", path_override=cache_path)

    assert pruned.summaries == {key_foo: _summary("foo")}


@pytest.mark.parametrize("corruption", [b"{not-json", b"x" * (9 * 1024 * 1024)])
def test_malformed_and_oversized_cache_files_are_empty(
    tmp_path: Path,
    corruption: bytes,
) -> None:
    cache_path = tmp_path / "summary-cache.json"
    cache_path.write_bytes(corruption)

    cache = read_roster_summary_cache(
        tmp_path / "sidecar", "proj", path_override=cache_path
    )

    assert cache.summaries == {}


def test_semantically_corrupt_summary_record_is_empty(tmp_path: Path) -> None:
    cache_path = tmp_path / "summary-cache.json"
    key = ["alice", "athena", "proj", "Project", "foo", "a" * 64]
    cache_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "project_key": "proj",
                "sidecar_path": str((tmp_path / "sidecar").resolve()),
                "summaries": [
                    {
                        "key": key,
                        "local_hood": "foo",
                        "run_count": 2,
                        "session_count": 1,
                        "state_counts": {"completed": 1, "failed": 1},
                        "summary_digest": "0" * 64,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    cache = read_roster_summary_cache(
        tmp_path / "sidecar", "proj", path_override=cache_path
    )

    assert cache.summaries == {}


def test_publication_timeout_propagates_from_cache_read_and_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sase.agents_sync.publication_roster as roster

    cache_path = tmp_path / "summary-cache.json"
    repo = tmp_path / "sidecar"
    cache = read_roster_summary_cache(repo, "proj", path_override=cache_path)
    cache_path.write_text("{}", encoding="utf-8")
    original_read_bytes = Path.read_bytes

    def timeout_read(path: Path) -> bytes:
        if path == cache_path:
            raise PublicationDrainTimedOut("cache read deadline")
        return original_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", timeout_read)
    with pytest.raises(PublicationDrainTimedOut, match="cache read deadline"):
        read_roster_summary_cache(repo, "proj", path_override=cache_path)
    monkeypatch.setattr(Path, "read_bytes", original_read_bytes)

    def timeout_replace(_source: Path, _destination: Path) -> None:
        raise PublicationDrainTimedOut("cache write deadline")

    monkeypatch.setattr(roster.os, "replace", timeout_replace)
    key = ("alice", "athena", "proj", "Project", "foo", "a" * 64)
    with pytest.raises(PublicationDrainTimedOut, match="cache write deadline"):
        write_roster_summary_cache(
            cache,
            current_keys={key},
            additions={key: _summary("foo")},
        )
