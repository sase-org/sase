"""Tests for saved queries functionality."""

from pathlib import Path
from unittest.mock import patch

from sase.ace.query_record import QueryRecord
from sase.ace.saved_queries import (
    KEY_ORDER,
    delete_query,
    find_slot_for_query,
    get_next_available_slot,
    load_saved_queries,
    save_query,
)


def test_key_order() -> None:
    """Test that key order is 0-9."""
    assert KEY_ORDER == ["0", "1", "2", "3", "4", "5", "6", "7", "8", "9"]


def test_delete_query(tmp_path: Path) -> None:
    """Test deleting a query from a slot."""
    test_file = tmp_path / "saved_queries.json"
    with patch("sase.ace.saved_queries._SAVED_QUERIES_FILE", test_file):
        assert save_query("patches", "1", '"test"', '"test"')
        assert save_query("patches", "2", '"test2"', '"test2"')
        assert delete_query("patches", "1")
        result = load_saved_queries("patches")
        assert result.keys() == {"2"}
        assert result["2"].canonical == '"test2"'


def test_delete_nonexistent_query(tmp_path: Path) -> None:
    """Test deleting from an empty slot returns True."""
    test_file = tmp_path / "saved_queries.json"
    with patch("sase.ace.saved_queries._SAVED_QUERIES_FILE", test_file):
        # Should return True even when slot doesn't exist
        assert delete_query("patches", "5")


def test_get_next_available_slot_partial() -> None:
    """Test getting next slot with some used."""
    result = get_next_available_slot(
        {"0": QueryRecord(source="a", canonical="a"), "1": QueryRecord("b", "b")}
    )
    assert result == "2"


def test_get_next_available_slot_full() -> None:
    """Test getting next slot when all full."""
    full = {slot: QueryRecord(source="q", canonical="q") for slot in KEY_ORDER}
    result = get_next_available_slot(full)
    assert result is None


def test_invalid_slot_rejected(tmp_path: Path) -> None:
    """Test that invalid slots are rejected."""
    test_file = tmp_path / "saved_queries.json"
    with patch("sase.ace.saved_queries._SAVED_QUERIES_FILE", test_file):
        result = save_query("patches", "X", '"test"', '"test"')
        assert result is False


def test_handles_corrupt_json(tmp_path: Path) -> None:
    """Test that corrupt JSON files are handled gracefully."""
    test_file = tmp_path / "saved_queries.json"
    test_file.write_text("not valid json {")
    with patch("sase.ace.saved_queries._SAVED_QUERIES_FILE", test_file):
        result = load_saved_queries("patches")
        assert result == {}


def test_load_last_query_no_file(tmp_path: Path) -> None:
    """Test loading returns None when no file exists."""
    with patch("sase.ace.saved_queries._LAST_QUERY_FILE", tmp_path / "nonexistent.txt"):
        from sase.ace.saved_queries import load_last_query

        result = load_last_query()
        assert result is None


def test_find_slot_for_query_found(tmp_path: Path) -> None:
    """Test finding an existing query returns its slot."""
    test_file = tmp_path / "saved_queries.json"
    with patch("sase.ace.saved_queries._SAVED_QUERIES_FILE", test_file):
        save_query("patches", "2", '"target"', '"target"')
        save_query("patches", "5", '"other"', '"other"')
        result = find_slot_for_query("patches", '"target"')
        assert result == "2"


def test_find_slot_for_query_not_found(tmp_path: Path) -> None:
    """Test that find_slot_for_query returns None when query is absent."""
    test_file = tmp_path / "saved_queries.json"
    with patch("sase.ace.saved_queries._SAVED_QUERIES_FILE", test_file):
        save_query("patches", "1", '"something"', '"something"')
        result = find_slot_for_query("patches", '"missing"')
        assert result is None


def test_save_query_moves_from_old_slot(tmp_path: Path) -> None:
    """Test that saving a query to a new slot removes it from the old slot."""
    test_file = tmp_path / "saved_queries.json"
    with patch("sase.ace.saved_queries._SAVED_QUERIES_FILE", test_file):
        save_query("patches", "2", '"moveme"', '"moveme"')
        save_query("patches", "5", '"moveme"', '"moveme"')
        result = load_saved_queries("patches")
        assert "2" not in result
        assert result["5"].canonical == '"moveme"'


def test_save_query_stamps_current_profile_digest(tmp_path: Path) -> None:
    """Saving on a built-in pane stamps the pane's current profile digest."""
    test_file = tmp_path / "saved_queries.json"
    with patch("sase.ace.saved_queries._SAVED_QUERIES_FILE", test_file):
        save_query("patches", "1", '"feature"', '"feature"')
        record = load_saved_queries("patches")["1"]
        assert record.profile_digest is not None
        assert record.is_stale("patches") is False


def test_save_query_is_namespaced_per_pane(tmp_path: Path) -> None:
    """Two panes keep independent slot maps."""
    test_file = tmp_path / "saved_queries.json"
    with patch("sase.ace.saved_queries._SAVED_QUERIES_FILE", test_file):
        save_query("patches", "1", '"patches-query"', '"patches-query"')
        save_query("stitches", "1", "author:me", "author:me")

        assert load_saved_queries("patches")["1"].canonical == '"patches-query"'
        assert load_saved_queries("stitches")["1"].canonical == "author:me"


def test_load_saved_queries_migrates_legacy_flat_file(tmp_path: Path) -> None:
    """A legacy flat file is lifted under the patches pane on first read."""
    import json

    test_file = tmp_path / "saved_queries.json"
    test_file.write_text(json.dumps({"1": "status:Ready", "2": '"alpha"'}))
    with patch("sase.ace.saved_queries._SAVED_QUERIES_FILE", test_file):
        result = load_saved_queries("patches")
        assert result["1"].source == "status:Ready"
        assert result["1"].canonical == "status:Ready"
        assert result["2"].canonical == '"alpha"'

        # The migration is persisted (write-then-read validated) so a
        # fresh read no longer needs to re-detect the legacy shape, and
        # other panes stay empty.
        assert load_saved_queries("stitches") == {}
        on_disk = json.loads(test_file.read_text())
        assert on_disk["patches"]["1"]["canonical"] == "status:Ready"
