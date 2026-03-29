"""Tests for the branch_map persistence module."""

import json

from sase.core.branch_map import (
    _branch_map_path,
    read_branch_map,
    remove_branch_alias,
    write_branch_alias,
)


def test_read_empty(tmp_path, monkeypatch):
    """read_branch_map returns {} when file does not exist."""
    monkeypatch.setattr("sase.core.branch_map.Path.home", lambda: tmp_path)
    assert read_branch_map("proj") == {}


def test_write_and_read(tmp_path, monkeypatch):
    """write_branch_alias creates the file and read_branch_map reads it."""
    monkeypatch.setattr("sase.core.branch_map.Path.home", lambda: tmp_path)
    write_branch_alias("proj", "sase_feat", "sase_feat_1")
    assert read_branch_map("proj") == {"sase_feat": "sase_feat_1"}


def test_write_multiple(tmp_path, monkeypatch):
    """Multiple aliases coexist in the same file."""
    monkeypatch.setattr("sase.core.branch_map.Path.home", lambda: tmp_path)
    write_branch_alias("proj", "sase_feat", "sase_feat_1")
    write_branch_alias("proj", "sase_other", "sase_other_2")
    data = read_branch_map("proj")
    assert data == {"sase_feat": "sase_feat_1", "sase_other": "sase_other_2"}


def test_write_overwrites(tmp_path, monkeypatch):
    """Writing the same key overwrites the old value."""
    monkeypatch.setattr("sase.core.branch_map.Path.home", lambda: tmp_path)
    write_branch_alias("proj", "sase_feat", "sase_feat_1")
    write_branch_alias("proj", "sase_feat", "sase_feat_3")
    assert read_branch_map("proj") == {"sase_feat": "sase_feat_3"}


def test_remove_existing(tmp_path, monkeypatch):
    """remove_branch_alias removes the entry, keeps others."""
    monkeypatch.setattr("sase.core.branch_map.Path.home", lambda: tmp_path)
    write_branch_alias("proj", "a", "branch_a")
    write_branch_alias("proj", "b", "branch_b")
    remove_branch_alias("proj", "a")
    assert read_branch_map("proj") == {"b": "branch_b"}


def test_remove_last_deletes_file(tmp_path, monkeypatch):
    """Removing the last alias deletes the file entirely."""
    monkeypatch.setattr("sase.core.branch_map.Path.home", lambda: tmp_path)
    write_branch_alias("proj", "a", "branch_a")
    remove_branch_alias("proj", "a")

    path = tmp_path / ".sase" / "projects" / "proj" / "branch_map.json"
    assert not path.exists()


def test_remove_nonexistent_key(tmp_path, monkeypatch):
    """Removing a key that doesn't exist is a no-op."""
    monkeypatch.setattr("sase.core.branch_map.Path.home", lambda: tmp_path)
    write_branch_alias("proj", "a", "branch_a")
    remove_branch_alias("proj", "missing")
    assert read_branch_map("proj") == {"a": "branch_a"}


def test_remove_nonexistent_file(tmp_path, monkeypatch):
    """Removing from a project with no branch_map is a no-op."""
    monkeypatch.setattr("sase.core.branch_map.Path.home", lambda: tmp_path)
    remove_branch_alias("proj", "anything")  # should not raise
