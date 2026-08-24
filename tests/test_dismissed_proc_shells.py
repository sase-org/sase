"""Tests for dismissed stand-alone proc-shell persistence."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from sase.ace.dismissed_proc_shells import (
    load_dismissed_proc_shells,
    prune_dismissed_proc_shells,
    record_dismissed_proc_shells,
)


def _patch_file(path: Path):
    return patch("sase.ace.dismissed_proc_shells._DISMISSED_PROC_SHELLS_FILE", path)


def test_load_empty_when_no_file(tmp_path: Path) -> None:
    with _patch_file(tmp_path / "missing.json"):
        assert load_dismissed_proc_shells() == set()


def test_round_trip_record_then_load(tmp_path: Path) -> None:
    test_file = tmp_path / "dismissed_proc_shells.json"
    with _patch_file(test_file):
        assert record_dismissed_proc_shells({"b-id", "a-id"})
        assert load_dismissed_proc_shells() == {"a-id", "b-id"}
        payload = json.loads(test_file.read_text(encoding="utf-8"))
        assert payload["schema_version"] == 1
        assert payload["proc_ids"] == ["a-id", "b-id"]


def test_second_writer_unions_instead_of_clobbering(tmp_path: Path) -> None:
    test_file = tmp_path / "dismissed_proc_shells.json"
    with _patch_file(test_file):
        assert record_dismissed_proc_shells({"alpha"})
        assert record_dismissed_proc_shells({"beta"})
        assert load_dismissed_proc_shells() == {"alpha", "beta"}


def test_load_accepts_bare_list(tmp_path: Path) -> None:
    test_file = tmp_path / "dismissed_proc_shells.json"
    test_file.write_text(json.dumps(["one", "two"]), encoding="utf-8")
    with _patch_file(test_file):
        assert load_dismissed_proc_shells() == {"one", "two"}


def test_load_ignores_non_string_entries(tmp_path: Path) -> None:
    test_file = tmp_path / "dismissed_proc_shells.json"
    test_file.write_text(
        json.dumps({"schema_version": 1, "proc_ids": ["ok", 1, None, {"x": 1}, ""]}),
        encoding="utf-8",
    )
    with _patch_file(test_file):
        assert load_dismissed_proc_shells() == {"ok"}


def test_load_malformed_or_wrong_shape_yields_empty(tmp_path: Path) -> None:
    malformed = tmp_path / "bad.json"
    malformed.write_text("not valid json {", encoding="utf-8")
    with _patch_file(malformed):
        assert load_dismissed_proc_shells() == set()
    wrong = tmp_path / "wrong.json"
    wrong.write_text(json.dumps({"proc_ids": "nope"}), encoding="utf-8")
    with _patch_file(wrong):
        assert load_dismissed_proc_shells() == set()


def test_write_failure_returns_false(tmp_path: Path) -> None:
    test_file = tmp_path / "dismissed_proc_shells.json"
    with (
        _patch_file(test_file),
        patch(
            "sase.ace.dismissed_proc_shells.write_json_file_atomic",
            side_effect=OSError("disk full"),
        ),
    ):
        assert record_dismissed_proc_shells({"alpha"}) is False


def test_record_with_live_ids_drops_absent(tmp_path: Path) -> None:
    test_file = tmp_path / "dismissed_proc_shells.json"
    with _patch_file(test_file):
        assert record_dismissed_proc_shells({"stale", "keep"})
        assert record_dismissed_proc_shells(
            {"fresh"},
            live_proc_ids={"keep", "fresh"},
        )
        assert load_dismissed_proc_shells() == {"keep", "fresh"}


def test_prune_drops_absent_ids_and_keeps_live(tmp_path: Path) -> None:
    test_file = tmp_path / "dismissed_proc_shells.json"
    with _patch_file(test_file):
        assert record_dismissed_proc_shells({"live", "gone", "also-gone"})
        pruned = prune_dismissed_proc_shells({"live", "other-live"})
        assert pruned == {"live"}
        assert load_dismissed_proc_shells() == {"live"}


def test_prune_does_not_rewrite_when_unchanged(tmp_path: Path) -> None:
    test_file = tmp_path / "dismissed_proc_shells.json"
    with _patch_file(test_file):
        assert record_dismissed_proc_shells({"keep-a", "keep-b"})
        before = test_file.stat()
        pruned = prune_dismissed_proc_shells({"keep-a", "keep-b", "unrelated"})
        after = test_file.stat()
        assert pruned == {"keep-a", "keep-b"}
        assert after.st_mtime_ns == before.st_mtime_ns
        assert after.st_size == before.st_size
