"""Tests for the saved_tag_names module."""

import json
from pathlib import Path
from unittest.mock import patch

from sase.ace.saved_tag_names import delete_tag, load_saved_tags, save_tag

# --- load_saved_tags tests ---


def test_load_saved_tags_invalid_json(tmp_path: Path) -> None:
    """Return empty dict on invalid JSON."""
    fake_file = tmp_path / "saved_tag_names.json"
    fake_file.write_text("not json")
    with patch("sase.ace.saved_tag_names._SAVED_TAG_NAMES_FILE", fake_file):
        assert load_saved_tags() == {}


def test_load_saved_tags_non_dict_non_list(tmp_path: Path) -> None:
    """Return empty dict when JSON is neither dict nor list."""
    fake_file = tmp_path / "saved_tag_names.json"
    fake_file.write_text(json.dumps(42))
    with patch("sase.ace.saved_tag_names._SAVED_TAG_NAMES_FILE", fake_file):
        assert load_saved_tags() == {}


# --- load_saved_tags returns keys usable as tag name list ---


def test_load_saved_tags_keys_from_legacy_list(tmp_path: Path) -> None:
    """Return tag names from legacy list format."""
    fake_file = tmp_path / "saved_tag_names.json"
    fake_file.write_text(json.dumps(["BUG", "FEATURE"]))
    with patch("sase.ace.saved_tag_names._SAVED_TAG_NAMES_FILE", fake_file):
        assert list(load_saved_tags().keys()) == ["BUG", "FEATURE"]


# --- save_tag tests ---


def test_save_tag_uppercases(tmp_path: Path) -> None:
    """Ensure saved tag names are uppercased."""
    fake_file = tmp_path / "saved_tag_names.json"
    with patch("sase.ace.saved_tag_names._SAVED_TAG_NAMES_FILE", fake_file):
        save_tag("My_Tag")
        data = json.loads(fake_file.read_text())
        assert data == {"MY_TAG": ""}


# --- delete_tag tests ---


def test_delete_tag_existing(tmp_path: Path) -> None:
    """Delete one tag, other tags remain."""
    fake_file = tmp_path / "saved_tag_names.json"
    fake_file.write_text(json.dumps({"BUG": "12345", "FEATURE": "v2"}))
    with patch("sase.ace.saved_tag_names._SAVED_TAG_NAMES_FILE", fake_file):
        result = delete_tag("BUG")
        assert result is True
        data = json.loads(fake_file.read_text())
        assert data == {"FEATURE": "v2"}


def test_delete_tag_no_file(tmp_path: Path) -> None:
    """Return True when file doesn't exist."""
    fake_file = tmp_path / "saved_tag_names.json"
    with patch("sase.ace.saved_tag_names._SAVED_TAG_NAMES_FILE", fake_file):
        result = delete_tag("BUG")
        assert result is True
