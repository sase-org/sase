"""Tests for the file_references module."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from sase.history.file_references import (
    extract_recordable_file_refs,
    load_file_references,
    record_file_references,
)


class TestExtractRecordableFileRefs:
    def test_keeps_absolute_and_tilde_paths(self) -> None:
        text = "check /etc/hosts and ~/notes/ideas.md please"
        assert extract_recordable_file_refs(text) == [
            "/etc/hosts",
            "~/notes/ideas.md",
        ]

    def test_strips_at_prefix(self) -> None:
        text = "look at @src/foo.py"
        assert extract_recordable_file_refs(text) == ["src/foo.py"]

    def test_excludes_bare_relative_paths(self) -> None:
        text = "touching src/foo.py but not recorded"
        assert extract_recordable_file_refs(text) == []

    def test_includes_at_prefixed_tilde_and_absolute(self) -> None:
        text = "@~/notes.md @/tmp/a.txt @docs/x.md"
        assert extract_recordable_file_refs(text) == [
            "~/notes.md",
            "/tmp/a.txt",
            "docs/x.md",
        ]

    def test_preserves_prompt_order(self) -> None:
        text = "second ~/b first: /a and @c/d.py last"
        assert extract_recordable_file_refs(text) == [
            "~/b",
            "/a",
            "c/d.py",
        ]

    def test_ignores_email_addresses(self) -> None:
        text = "mail me at user@domain.com and key@abc"
        assert extract_recordable_file_refs(text) == []

    def test_empty_text(self) -> None:
        assert extract_recordable_file_refs("") == []

    def test_tilde_alone_is_not_recorded(self) -> None:
        assert extract_recordable_file_refs("just ~ here") == []


class TestFileReferenceStore:
    def test_load_missing_file_returns_empty(self, tmp_path: Path) -> None:
        with patch(
            "sase.history.file_references._HISTORY_FILE", tmp_path / "missing.json"
        ):
            assert load_file_references() == []

    def test_record_then_load_roundtrip(self, tmp_path: Path) -> None:
        store = tmp_path / "hist.json"
        with patch("sase.history.file_references._HISTORY_FILE", store):
            record_file_references(["/etc/hosts", "~/a.md"])
            # Last in refs ends up at index 0 (most recent).
            assert load_file_references() == ["~/a.md", "/etc/hosts"]

    def test_record_dedups_across_calls_keeping_most_recent(
        self, tmp_path: Path
    ) -> None:
        store = tmp_path / "hist.json"
        with patch("sase.history.file_references._HISTORY_FILE", store):
            record_file_references(["/a", "/b"])
            record_file_references(["/a"])
            # /a was just recorded → index 0; /b stays.
            assert load_file_references() == ["/a", "/b"]

    def test_record_within_single_call_dedups(self, tmp_path: Path) -> None:
        store = tmp_path / "hist.json"
        with patch("sase.history.file_references._HISTORY_FILE", store):
            record_file_references(["/a", "/b", "/a"])
            # Last-wins within the same call; earlier duplicate dropped.
            assert load_file_references() == ["/a", "/b"]

    def test_record_empty_iterable_is_noop(self, tmp_path: Path) -> None:
        store = tmp_path / "hist.json"
        with patch("sase.history.file_references._HISTORY_FILE", store):
            record_file_references([])
            assert load_file_references() == []
            assert not store.exists()

    def test_load_corrupt_json_returns_empty(self, tmp_path: Path) -> None:
        store = tmp_path / "hist.json"
        store.write_text("not json", encoding="utf-8")
        with patch("sase.history.file_references._HISTORY_FILE", store):
            assert load_file_references() == []

    def test_load_filters_non_string_entries(self, tmp_path: Path) -> None:
        store = tmp_path / "hist.json"
        store.write_text(
            json.dumps({"paths": ["/a", 42, None, "/b"]}), encoding="utf-8"
        )
        with patch("sase.history.file_references._HISTORY_FILE", store):
            assert load_file_references() == ["/a", "/b"]

    def test_ordering_preserved_across_multiple_calls(self, tmp_path: Path) -> None:
        store = tmp_path / "hist.json"
        with patch("sase.history.file_references._HISTORY_FILE", store):
            record_file_references(["/1"])
            record_file_references(["/2"])
            record_file_references(["/3"])
            assert load_file_references() == ["/3", "/2", "/1"]
