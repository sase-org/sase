"""Tests for sase.history.vcs_xprompt_mru — MRU tracking for VCS xprompt prefixes."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.history.vcs_xprompt_mru import (
    _MAX_ENTRIES,
    load_launchable_vcs_xprompt_mru,
    _load_vcs_xprompt_mru,
    record_vcs_xprompt_usage,
)
from tests.conftest import redirect_sase_home


def _write_project(
    projects_dir: Path, project_name: str, workspace_dir: Path | None
) -> None:
    project_dir = projects_dir / project_name
    project_dir.mkdir(parents=True)
    project_file = project_dir / f"{project_name}.sase"
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
        assert _load_vcs_xprompt_mru() == []


def test_load_returns_entries(tmp_path: Path) -> None:
    """Loads entries from a valid JSON file."""
    fake = tmp_path / "vcs_xprompt_mru.json"
    fake.write_text(json.dumps({"entries": ["#gh:sase", "#gh:other"]}))
    with patch.object(
        __import__("sase.history.vcs_xprompt_mru", fromlist=["_MRU_FILE"]),
        "_MRU_FILE",
        fake,
    ):
        assert _load_vcs_xprompt_mru() == ["#gh:sase", "#gh:other"]


def test_load_filters_non_strings(tmp_path: Path) -> None:
    """Non-string entries are filtered out."""
    fake = tmp_path / "vcs_xprompt_mru.json"
    fake.write_text(json.dumps({"entries": ["#gh:sase", 42, None, "#gh:b"]}))
    with patch.object(
        __import__("sase.history.vcs_xprompt_mru", fromlist=["_MRU_FILE"]),
        "_MRU_FILE",
        fake,
    ):
        assert _load_vcs_xprompt_mru() == ["#gh:sase", "#gh:b"]


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
        result = _load_vcs_xprompt_mru()
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
        assert _load_vcs_xprompt_mru() == []


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
        result = _load_vcs_xprompt_mru()
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
        result = _load_vcs_xprompt_mru()
        assert result == ["#gh:c", "#gh:a", "#gh:b"]


def test_record_moves_existing_prefix_to_launchable_mru_front(tmp_path: Path) -> None:
    fake = tmp_path / "vcs_xprompt_mru.json"
    fake.write_text(json.dumps({"entries": ["#gh:a", "#gh:b", "#gh:c"]}))
    projects_dir = tmp_path / "projects"

    with patch.object(
        __import__("sase.history.vcs_xprompt_mru", fromlist=["_MRU_FILE"]),
        "_MRU_FILE",
        fake,
    ):
        record_vcs_xprompt_usage("#gh:c")
        result = load_launchable_vcs_xprompt_mru(projects_dir)

    assert result[0] == "#gh:c"
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
        result = _load_vcs_xprompt_mru()
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
        result = _load_vcs_xprompt_mru()
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
    assert _load_vcs_xprompt_mru() == [f"#cd:{tmp_path}"]
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


def test_load_launchable_keeps_launchable_home_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = tmp_path / "vcs_xprompt_mru.json"
    fake.write_text(json.dumps({"entries": ["#gh:home"]}))
    projects_dir = tmp_path / "projects"
    home_workspace = tmp_path / "home-workspace"
    home_workspace.mkdir()
    _write_project(projects_dir, "home", home_workspace)

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

    assert result == ["#gh:home"]
    assert json.loads(fake.read_text()) == {"entries": ["#gh:home"]}


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
        result = _load_vcs_xprompt_mru()

    assert result == ["#gh:valid"]
    assert json.loads(fake.read_text()) == {"entries": ["#gh:valid"]}


def test_load_launchable_prunes_default_git_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The implicit default ``#git:home`` is never a cyclable candidate and is
    pruned out of the persisted MRU on load."""
    sase_home = redirect_sase_home(monkeypatch, tmp_path / ".sase")
    workspace = tmp_path / "ws"
    workspace.mkdir()
    mru_file = sase_home / "vcs_xprompt_mru.json"
    mru_file.write_text(json.dumps({"entries": ["#git:foo", "#git:home", "#git:bar"]}))

    monkeypatch.setattr(
        "sase.xprompt.loader.get_known_project_workspaces",
        lambda *a, **k: {"foo": workspace, "bar": workspace},
    )
    monkeypatch.setattr(
        "sase.ace.changespec.cache.find_all_changespecs_cached",
        lambda *a, **k: [],
    )

    result = load_launchable_vcs_xprompt_mru()

    assert result == ["#git:foo", "#git:bar"]
    assert json.loads(mru_file.read_text()) == {"entries": ["#git:foo", "#git:bar"]}


def test_record_does_not_persist_default_git_home(tmp_path: Path) -> None:
    """Recording the implicit default does not add it to the MRU; an existing
    default entry is dropped instead."""
    fake = tmp_path / "vcs_xprompt_mru.json"
    fake.write_text(json.dumps({"entries": ["#gh:sase", "#git:home"]}))
    with patch.object(
        __import__("sase.history.vcs_xprompt_mru", fromlist=["_MRU_FILE"]),
        "_MRU_FILE",
        fake,
    ):
        record_vcs_xprompt_usage("#git:home")
        result = _load_vcs_xprompt_mru()

    assert result == ["#gh:sase"]
    assert json.loads(fake.read_text()) == {"entries": ["#gh:sase"]}


class _FakeChangeSpec:
    def __init__(self, name: str) -> None:
        self.name = name


def test_load_launchable_drops_refs_that_no_longer_resolve(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A ref that maps to neither a known project nor an active ChangeSpec is
    dropped from the cyclable set; project/changespec refs are retained."""
    sase_home = redirect_sase_home(monkeypatch, tmp_path / ".sase")
    workspace = tmp_path / "sase-ws"
    workspace.mkdir()
    mru_file = sase_home / "vcs_xprompt_mru.json"
    mru_file.write_text(
        json.dumps({"entries": ["#git:sase", "#git:somecs", "#git:gone"]})
    )

    monkeypatch.setattr(
        "sase.xprompt.loader.get_known_project_workspaces",
        lambda *a, **k: {"sase": workspace},
    )
    monkeypatch.setattr(
        "sase.ace.changespec.cache.find_all_changespecs_cached",
        lambda *a, **k: [_FakeChangeSpec("somecs")],
    )

    result = load_launchable_vcs_xprompt_mru()

    assert result == ["#git:sase", "#git:somecs"]
    assert json.loads(mru_file.read_text()) == {"entries": ["#git:sase", "#git:somecs"]}


def test_load_launchable_keeps_entries_when_resolution_index_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A transient failure building the resolvability snapshot keeps every
    entry rather than nuking the MRU."""
    sase_home = redirect_sase_home(monkeypatch, tmp_path / ".sase")
    mru_file = sase_home / "vcs_xprompt_mru.json"
    mru_file.write_text(json.dumps({"entries": ["#git:sase", "#git:gone"]}))

    def _boom(*_a: object, **_k: object) -> list[object]:
        raise RuntimeError("transient resolution failure")

    monkeypatch.setattr("sase.ace.changespec.cache.find_all_changespecs_cached", _boom)

    result = load_launchable_vcs_xprompt_mru()

    assert result == ["#git:sase", "#git:gone"]
    assert json.loads(mru_file.read_text()) == {"entries": ["#git:sase", "#git:gone"]}
