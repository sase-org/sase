"""Tests for dismissed stand-alone named-proc persistence."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from sase.ace.dismissed_procs import (
    load_dismissed_named_procs,
    load_dismissed_procs,
    prune_dismissed_named_procs,
    prune_dismissed_procs,
    record_dismissed_named_procs,
    record_dismissed_procs,
)


def _patch_file(path: Path):
    return patch("sase.ace.dismissed_procs._DISMISSED_PROCS_FILE", path)


def test_load_empty_when_no_file(tmp_path: Path) -> None:
    with _patch_file(tmp_path / "missing.json"):
        assert load_dismissed_procs() == set()


def test_round_trip_record_then_load(tmp_path: Path) -> None:
    test_file = tmp_path / "dismissed_procs.json"
    with _patch_file(test_file):
        assert record_dismissed_procs({"b-id", "a-id"})
        assert load_dismissed_procs() == {"a-id", "b-id"}
        payload = json.loads(test_file.read_text(encoding="utf-8"))
        assert payload["schema_version"] == 1
        assert payload["proc_ids"] == ["a-id", "b-id"]


def test_second_writer_unions_instead_of_clobbering(tmp_path: Path) -> None:
    test_file = tmp_path / "dismissed_procs.json"
    with _patch_file(test_file):
        assert record_dismissed_procs({"alpha"})
        assert record_dismissed_procs({"beta"})
        assert load_dismissed_procs() == {"alpha", "beta"}


def test_load_accepts_bare_list(tmp_path: Path) -> None:
    test_file = tmp_path / "dismissed_procs.json"
    test_file.write_text(json.dumps(["one", "two"]), encoding="utf-8")
    with _patch_file(test_file):
        assert load_dismissed_procs() == {"one", "two"}


def test_load_ignores_non_string_entries(tmp_path: Path) -> None:
    test_file = tmp_path / "dismissed_procs.json"
    test_file.write_text(
        json.dumps({"schema_version": 1, "proc_ids": ["ok", 1, None, {"x": 1}, ""]}),
        encoding="utf-8",
    )
    with _patch_file(test_file):
        assert load_dismissed_procs() == {"ok"}


def test_load_malformed_or_wrong_shape_yields_empty(tmp_path: Path) -> None:
    malformed = tmp_path / "bad.json"
    malformed.write_text("not valid json {", encoding="utf-8")
    with _patch_file(malformed):
        assert load_dismissed_procs() == set()
    wrong = tmp_path / "wrong.json"
    wrong.write_text(json.dumps({"proc_ids": "nope"}), encoding="utf-8")
    with _patch_file(wrong):
        assert load_dismissed_procs() == set()


def test_write_failure_returns_false(tmp_path: Path) -> None:
    test_file = tmp_path / "dismissed_procs.json"
    with (
        _patch_file(test_file),
        patch(
            "sase.ace.dismissed_procs.write_json_file_atomic",
            side_effect=OSError("disk full"),
        ),
    ):
        assert record_dismissed_procs({"alpha"}) is False


def test_record_with_live_ids_drops_absent(tmp_path: Path) -> None:
    test_file = tmp_path / "dismissed_procs.json"
    with _patch_file(test_file):
        assert record_dismissed_procs({"stale", "keep"})
        assert record_dismissed_procs(
            {"fresh"},
            live_proc_ids={"keep", "fresh"},
        )
        assert load_dismissed_procs() == {"keep", "fresh"}


def test_prune_drops_absent_ids_and_keeps_live(tmp_path: Path) -> None:
    test_file = tmp_path / "dismissed_procs.json"
    with _patch_file(test_file):
        assert record_dismissed_procs({"live", "gone", "also-gone"})
        pruned = prune_dismissed_procs({"live", "other-live"})
        assert pruned == {"live"}
        assert load_dismissed_procs() == {"live"}


def test_prune_does_not_rewrite_when_unchanged(tmp_path: Path) -> None:
    test_file = tmp_path / "dismissed_procs.json"
    with _patch_file(test_file):
        assert record_dismissed_procs({"keep-a", "keep-b"})
        before = test_file.stat()
        pruned = prune_dismissed_procs({"keep-a", "keep-b", "unrelated"})
        after = test_file.stat()
        assert pruned == {"keep-a", "keep-b"}
        assert after.st_mtime_ns == before.st_mtime_ns
        assert after.st_size == before.st_size


def test_legacy_file_reads_when_no_new_file(tmp_path: Path) -> None:
    """A pre-rename dismissed file still loads, then migrates on write."""
    from sase.ace import dismissed_procs as dismissed

    new_file = tmp_path / "dismissed_procs.json"
    legacy_file = tmp_path / "dismissed_named_procs.json"
    legacy_file.write_text(
        json.dumps({"schema_version": 1, "proc_ids": ["old-id"]}), encoding="utf-8"
    )
    with (
        patch.object(dismissed, "_DISMISSED_PROCS_FILE", new_file),
        patch.object(dismissed, "_DISMISSED_NAMED_PROCS_FILE", legacy_file),
    ):
        # legacy sase-shell spelling: old file loads when no new file exists.
        assert load_dismissed_procs() == {"old-id"}
        assert record_dismissed_procs({"new-id"})
        assert load_dismissed_procs() == {"old-id", "new-id"}
        assert not legacy_file.exists()
        assert new_file.is_file()


def test_legacy_aliases_still_work(tmp_path: Path) -> None:
    test_file = tmp_path / "dismissed_procs.json"
    with _patch_file(test_file):
        assert record_dismissed_named_procs({"legacy-id"})
        assert load_dismissed_named_procs() == {"legacy-id"}
        assert prune_dismissed_named_procs({"legacy-id"}) == {"legacy-id"}
