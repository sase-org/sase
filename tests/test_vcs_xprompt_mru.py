"""Tests for sase.history.vcs_xprompt_mru — MRU tracking for VCS xprompt prefixes."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.history.vcs_xprompt_mru import (
    _MAX_ENTRIES,
    load_launchable_vcs_xprompt_mru,
    load_vcs_xprompt_mru,
    record_vcs_xprompt_usage,
)
from tests.conftest import redirect_sase_home


def _write_project(
    projects_dir: Path, project_name: str, workspace_dir: Path | None
) -> None:
    project_dir = projects_dir / project_name
    project_dir.mkdir(parents=True)
    project_file = project_dir / f"{project_name}.gp"
    if workspace_dir is None:
        project_file.write_text("", encoding="utf-8")
        return
    project_file.write_text(
        f"WORKSPACE_DIR: {workspace_dir}\nNAME: {project_name}_change\n",
        encoding="utf-8",
    )


def test_load_empty_when_file_missing(tmp_path: Path) -> None:
    """Returns empty list when MRU file doesn't exist."""
    fake = tmp_path / "vcs_xprompt_mru.json"
    with patch.object(
        __import__("sase.history.vcs_xprompt_mru", fromlist=["_MRU_FILE"]),
        "_MRU_FILE",
        fake,
    ):
        assert load_vcs_xprompt_mru() == []


def test_load_returns_entries(tmp_path: Path) -> None:
    """Loads entries from a valid JSON file."""
    fake = tmp_path / "vcs_xprompt_mru.json"
    fake.write_text(json.dumps({"entries": ["#gh:sase", "#gh:other"]}))
    with patch.object(
        __import__("sase.history.vcs_xprompt_mru", fromlist=["_MRU_FILE"]),
        "_MRU_FILE",
        fake,
    ):
        assert load_vcs_xprompt_mru() == ["#gh:sase", "#gh:other"]


def test_load_filters_non_strings(tmp_path: Path) -> None:
    """Non-string entries are filtered out."""
    fake = tmp_path / "vcs_xprompt_mru.json"
    fake.write_text(json.dumps({"entries": ["#gh:sase", 42, None, "#gh:b"]}))
    with patch.object(
        __import__("sase.history.vcs_xprompt_mru", fromlist=["_MRU_FILE"]),
        "_MRU_FILE",
        fake,
    ):
        assert load_vcs_xprompt_mru() == ["#gh:sase", "#gh:b"]


def test_load_caps_at_max(tmp_path: Path) -> None:
    """Only first _MAX_ENTRIES are returned."""
    fake = tmp_path / "vcs_xprompt_mru.json"
    entries = [f"#gh:proj{i}" for i in range(_MAX_ENTRIES + 5)]
    fake.write_text(json.dumps({"entries": entries}))
    with patch.object(
        __import__("sase.history.vcs_xprompt_mru", fromlist=["_MRU_FILE"]),
        "_MRU_FILE",
        fake,
    ):
        result = load_vcs_xprompt_mru()
        assert len(result) == _MAX_ENTRIES


def test_load_handles_corrupt_json(tmp_path: Path) -> None:
    """Returns empty list for corrupt JSON."""
    fake = tmp_path / "vcs_xprompt_mru.json"
    fake.write_text("not json")
    with patch.object(
        __import__("sase.history.vcs_xprompt_mru", fromlist=["_MRU_FILE"]),
        "_MRU_FILE",
        fake,
    ):
        assert load_vcs_xprompt_mru() == []


def test_record_adds_new_prefix(tmp_path: Path) -> None:
    """New prefix is added to front of list."""
    fake = tmp_path / "vcs_xprompt_mru.json"
    fake.write_text(json.dumps({"entries": ["#gh:old"]}))
    with patch.object(
        __import__("sase.history.vcs_xprompt_mru", fromlist=["_MRU_FILE"]),
        "_MRU_FILE",
        fake,
    ):
        record_vcs_xprompt_usage("#gh:new")
        result = load_vcs_xprompt_mru()
        assert result == ["#gh:new", "#gh:old"]


def test_record_moves_existing_to_front(tmp_path: Path) -> None:
    """Existing prefix is moved to front (not duplicated)."""
    fake = tmp_path / "vcs_xprompt_mru.json"
    fake.write_text(json.dumps({"entries": ["#gh:a", "#gh:b", "#gh:c"]}))
    with patch.object(
        __import__("sase.history.vcs_xprompt_mru", fromlist=["_MRU_FILE"]),
        "_MRU_FILE",
        fake,
    ):
        record_vcs_xprompt_usage("#gh:c")
        result = load_vcs_xprompt_mru()
        assert result == ["#gh:c", "#gh:a", "#gh:b"]


def test_record_caps_at_max(tmp_path: Path) -> None:
    """List is capped at _MAX_ENTRIES after recording."""
    fake = tmp_path / "vcs_xprompt_mru.json"
    entries = [f"#gh:proj{i}" for i in range(_MAX_ENTRIES)]
    fake.write_text(json.dumps({"entries": entries}))
    with patch.object(
        __import__("sase.history.vcs_xprompt_mru", fromlist=["_MRU_FILE"]),
        "_MRU_FILE",
        fake,
    ):
        record_vcs_xprompt_usage("#gh:brand_new")
        result = load_vcs_xprompt_mru()
        assert len(result) == _MAX_ENTRIES
        assert result[0] == "#gh:brand_new"
        # Last entry was evicted
        assert f"#gh:proj{_MAX_ENTRIES - 1}" not in result


def test_record_creates_file_if_missing(tmp_path: Path) -> None:
    """Creates the MRU file (and parent dirs) when it doesn't exist."""
    fake = tmp_path / "subdir" / "vcs_xprompt_mru.json"
    with patch.object(
        __import__("sase.history.vcs_xprompt_mru", fromlist=["_MRU_FILE"]),
        "_MRU_FILE",
        fake,
    ):
        record_vcs_xprompt_usage("#gh:first")
        assert fake.exists()
        result = load_vcs_xprompt_mru()
        assert result == ["#gh:first"]


def test_record_uses_redirected_sase_home_without_mru_file_patch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Default MRU writes follow the suite's ``~/.sase`` redirection."""
    sase_home = redirect_sase_home(monkeypatch, tmp_path / "sase_home")
    isolated_mru = sase_home / "vcs_xprompt_mru.json"
    real_home_mru = Path.home() / ".sase" / "vcs_xprompt_mru.json"

    record_vcs_xprompt_usage(f"#cd:{tmp_path}")

    assert isolated_mru.exists()
    assert load_vcs_xprompt_mru() == [f"#cd:{tmp_path}"]
    assert isolated_mru != real_home_mru


def test_load_launchable_filters_known_stale_projects(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = tmp_path / "vcs_xprompt_mru.json"
    fake.write_text(json.dumps({"entries": ["#gh:stale", "#gh:branch", "#gh:valid"]}))
    projects_dir = tmp_path / "projects"
    valid_workspace = tmp_path / "valid-workspace"
    valid_workspace.mkdir()
    _write_project(projects_dir, "valid", valid_workspace)
    _write_project(projects_dir, "stale", tmp_path / "missing-workspace")

    monkeypatch.setattr(
        "sase.ace.tui.modals.project_discovery.detect_workflow_type",
        lambda _project_file: "git",
    )

    with patch.object(
        __import__("sase.history.vcs_xprompt_mru", fromlist=["_MRU_FILE"]),
        "_MRU_FILE",
        fake,
    ):
        result = load_launchable_vcs_xprompt_mru(projects_dir)

    assert result == ["#gh:branch", "#gh:valid"]
    assert json.loads(fake.read_text()) == {"entries": ["#gh:branch", "#gh:valid"]}


def test_record_prunes_known_stale_project_prefix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = tmp_path / "vcs_xprompt_mru.json"
    fake.write_text(json.dumps({"entries": ["#gh:project", "#gh:valid"]}))
    sase_home = redirect_sase_home(monkeypatch, tmp_path / ".sase")
    projects_dir = sase_home / "projects"
    valid_workspace = tmp_path / "valid-workspace"
    valid_workspace.mkdir()
    _write_project(projects_dir, "valid", valid_workspace)
    _write_project(projects_dir, "project", tmp_path / "missing-workspace")

    monkeypatch.setattr(
        "sase.ace.tui.modals.project_discovery.detect_workflow_type",
        lambda _project_file: "git",
    )

    with (
        patch.object(
            __import__("sase.history.vcs_xprompt_mru", fromlist=["_MRU_FILE"]),
            "_MRU_FILE",
            fake,
        ),
    ):
        record_vcs_xprompt_usage("#gh:project")
        result = load_vcs_xprompt_mru()

    assert result == ["#gh:valid"]
    assert json.loads(fake.read_text()) == {"entries": ["#gh:valid"]}
