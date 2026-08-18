"""Tests for sase.history.vcs_xprompt_mru — MRU tracking for VCS xprompt prefixes."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.history.vcs_xprompt_mru import (
    _MAX_ENTRIES,
    load_launchable_vcs_xprompt_mru,
    load_launchable_vcs_xprompt_mru_pairs,
    _load_vcs_xprompt_mru,
    record_vcs_xprompt_usage,
)
from sase.workspace_provider import reset_workflow_metadata_caches
from sase.workspace_provider._hookspec import WorkflowMetadata
from tests._workspace_provider_helpers import (
    _restore_xprompt_vcs_caches_on_teardown,
    git_metadata,
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


def _write_named_project(
    projects_dir: Path,
    directory_key: str,
    project_name: str,
    workspace_dir: Path,
) -> None:
    """Write a real ProjectSpec whose ``PROJECT_NAME`` differs from its dir key."""
    project_dir = projects_dir / directory_key
    project_dir.mkdir(parents=True)
    (project_dir / f"{directory_key}.sase").write_text(
        f"PROJECT_NAME: {project_name}\nWORKSPACE_DIR: {workspace_dir}\n"
        f"NAME: {directory_key}_change\n",
        encoding="utf-8",
    )


def _git_and_gh_metadata() -> tuple[WorkflowMetadata, ...]:
    return git_metadata() + (
        WorkflowMetadata(
            workflow_type="gh",
            ref_pattern=r"(?:^|(?<=\s))#gh(?:[_:]([a-zA-Z0-9_./-]+)|\(([^)]+)\))",
            display_name="GitHub",
            pre_allocated_env_prefix="SASE_GH",
        ),
    )


def _patch_git_and_gh_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    import sase.workspace_provider as workspace_provider
    import sase.workspace_provider._registry as registry

    monkeypatch.setattr(registry, "get_all_workflow_metadata", _git_and_gh_metadata)
    monkeypatch.setattr(
        workspace_provider, "get_all_workflow_metadata", _git_and_gh_metadata
    )
    reset_workflow_metadata_caches()
    _restore_xprompt_vcs_caches_on_teardown(monkeypatch)


@pytest.fixture
def _reset_display_name_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    """Clear the module-level, mtime-keyed display-name cache before a test."""
    import sase.project_display_names as pdn

    monkeypatch.setattr(pdn, "_PROJECT_DISPLAY_NAME_CACHE", None)


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

    record_vcs_xprompt_usage("#gh:first")

    assert isolated_mru.exists()
    assert _load_vcs_xprompt_mru() == ["#gh:first"]
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


class _FakePatch:
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
        "sase.ace.patch.cache.find_all_patches_cached",
        lambda *a, **k: [_FakePatch("somecs")],
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

    monkeypatch.setattr("sase.ace.patch.cache.find_all_patches_cached", _boom)

    result = load_launchable_vcs_xprompt_mru()

    assert result == ["#git:sase", "#git:gone"]
    assert json.loads(mru_file.read_text()) == {"entries": ["#git:sase", "#git:gone"]}


@pytest.mark.usefixtures("_reset_display_name_cache")
def test_load_launchable_humanizes_project_name_and_keeps_disk_canonical(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A canonical on-disk entry is returned humanized; disk stays canonical.

    The stale sibling forces a prune write-back, proving the persisted MRU is
    re-written in canonical (directory-key) form even as the returned list is
    humanized to the configured ``PROJECT_NAME``.
    """
    fake = tmp_path / "vcs_xprompt_mru.json"
    fake.write_text(
        json.dumps({"entries": ["#gh:gh_acme__widgets", "#gh:gh_acme__stale"]})
    )
    projects_dir = tmp_path / "projects"
    widgets_ws = tmp_path / "widgets-ws"
    widgets_ws.mkdir()
    _write_named_project(projects_dir, "gh_acme__widgets", "widgets", widgets_ws)
    _write_named_project(
        projects_dir, "gh_acme__stale", "stale", tmp_path / "missing-ws"
    )

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

    assert result == ["#gh:widgets"]
    assert json.loads(fake.read_text()) == {"entries": ["#gh:gh_acme__widgets"]}


@pytest.mark.usefixtures("_reset_display_name_cache")
def test_load_launchable_dedupes_humanized_duplicates_in_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Canonical and display-form entries for one project collapse to one, in order."""
    fake = tmp_path / "vcs_xprompt_mru.json"
    fake.write_text(
        json.dumps({"entries": ["#gh:gh_acme__widgets", "#gh:widgets", "#gh:other"]})
    )
    projects_dir = tmp_path / "projects"
    widgets_ws = tmp_path / "widgets-ws"
    widgets_ws.mkdir()
    _write_named_project(projects_dir, "gh_acme__widgets", "widgets", widgets_ws)

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

    assert result == ["#gh:widgets", "#gh:other"]


@pytest.mark.usefixtures("_reset_display_name_cache")
def test_load_launchable_keeps_alias_form_entry_via_alias_aware_pruning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A display-form ``#git:widgets`` is judged by its canonical project.

    Without alias-aware pruning the ref resolves to neither a known project key
    nor a ChangeSpec name and would be wrongly pruned as gone.
    """
    sase_home = redirect_sase_home(monkeypatch, tmp_path / ".sase")
    projects_dir = sase_home / "projects"
    workspace = tmp_path / "ws"
    workspace.mkdir()
    _write_named_project(projects_dir, "proj_widgets", "widgets", workspace)
    mru_file = sase_home / "vcs_xprompt_mru.json"
    mru_file.write_text(json.dumps({"entries": ["#git:widgets"]}))

    monkeypatch.setattr(
        "sase.xprompt.loader.get_known_project_workspaces",
        lambda *a, **k: {"proj_widgets": workspace},
    )
    monkeypatch.setattr(
        "sase.ace.changespec.cache.find_all_changespecs_cached",
        lambda *a, **k: [],
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals.project_discovery.detect_workflow_type",
        lambda _project_file: "git",
    )

    result = load_launchable_vcs_xprompt_mru()

    assert result == ["#git:widgets"]
    assert json.loads(mru_file.read_text()) == {"entries": ["#git:widgets"]}


def test_record_canonicalizes_alias_form_and_dedupes_against_canonical(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Recording ``#gh:widgets`` stores the canonical key and collapses dupes."""
    sase_home = redirect_sase_home(monkeypatch, tmp_path / ".sase")
    projects_dir = sase_home / "projects"
    workspace = tmp_path / "ws"
    workspace.mkdir()
    _write_named_project(projects_dir, "gh_acme__widgets", "widgets", workspace)
    mru_file = sase_home / "vcs_xprompt_mru.json"
    mru_file.write_text(json.dumps({"entries": ["#gh:gh_acme__widgets", "#gh:other"]}))

    monkeypatch.setattr(
        "sase.ace.tui.modals.project_discovery.detect_workflow_type",
        lambda _project_file: "git",
    )

    record_vcs_xprompt_usage("#gh:widgets")

    assert _load_vcs_xprompt_mru() == ["#gh:gh_acme__widgets", "#gh:other"]


def test_load_launchable_prunes_provider_mismatched_prefix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A stale ``#git:`` entry for a project whose real provider is GitHub
    is pruned, while ``#gh:`` for the same project and an unrelated
    ``#git:`` entry for a genuine bare-git project both survive.

    Regression test for bare_git_project_clobber: a ``#git:`` ref cycled
    from the MRU must never again silently re-point ``resolve_git_ref`` at
    a real GitHub project.
    """
    _patch_git_and_gh_metadata(monkeypatch)
    sase_home = redirect_sase_home(monkeypatch, tmp_path / ".sase")
    projects_dir = sase_home / "projects"
    sase_ws = tmp_path / "sase-ws"
    sase_ws.mkdir()
    other_ws = tmp_path / "other-ws"
    other_ws.mkdir()
    _write_named_project(projects_dir, "gh_sase-org__sase", "sase", sase_ws)
    _write_named_project(projects_dir, "otherproj", "otherproj", other_ws)
    mru_file = sase_home / "vcs_xprompt_mru.json"
    mru_file.write_text(
        json.dumps(
            {
                "entries": [
                    "#git:gh_sase-org__sase",
                    "#gh:gh_sase-org__sase",
                    "#git:otherproj",
                ]
            }
        )
    )

    monkeypatch.setattr(
        "sase.xprompt.loader.get_known_project_workspaces",
        lambda *a, **k: {"gh_sase-org__sase": sase_ws, "otherproj": other_ws},
    )
    monkeypatch.setattr(
        "sase.ace.patch.cache.find_all_patches_cached",
        lambda *a, **k: [],
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals.project_discovery.detect_workflow_type",
        lambda _project_file: "git",
    )
    monkeypatch.setattr(
        "sase.workspace_provider.detect_workflow_type",
        lambda project_file: "gh" if "gh_sase-org__sase" in project_file else "git",
    )

    result = load_launchable_vcs_xprompt_mru()

    assert result == ["#gh:sase", "#git:otherproj"]
    assert json.loads(mru_file.read_text()) == {
        "entries": ["#gh:gh_sase-org__sase", "#git:otherproj"]
    }


def test_record_prunes_provider_mismatched_prefix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Recording a provider-mismatched ``#git:`` prefix drops it instead of
    writing it back to disk."""
    _patch_git_and_gh_metadata(monkeypatch)
    sase_home = redirect_sase_home(monkeypatch, tmp_path / ".sase")
    projects_dir = sase_home / "projects"
    sase_ws = tmp_path / "sase-ws"
    sase_ws.mkdir()
    _write_named_project(projects_dir, "gh_sase-org__sase", "sase", sase_ws)
    mru_file = sase_home / "vcs_xprompt_mru.json"
    mru_file.write_text(json.dumps({"entries": ["#gh:gh_sase-org__sase"]}))

    monkeypatch.setattr(
        "sase.xprompt.loader.get_known_project_workspaces",
        lambda *a, **k: {"gh_sase-org__sase": sase_ws},
    )
    monkeypatch.setattr(
        "sase.ace.patch.cache.find_all_patches_cached",
        lambda *a, **k: [],
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals.project_discovery.detect_workflow_type",
        lambda _project_file: "git",
    )
    monkeypatch.setattr(
        "sase.workspace_provider.detect_workflow_type",
        lambda _project_file: "gh",
    )

    record_vcs_xprompt_usage("#git:gh_sase-org__sase")

    assert _load_vcs_xprompt_mru() == ["#gh:gh_sase-org__sase"]


def test_record_then_record_moves_mru_head_to_most_recently_recorded(
    tmp_path: Path,
) -> None:
    """Recording ref A then ref B leaves B at the MRU head, not A.

    Regression test for the headline ``<ctrl+space>`` defect, reduced to its
    store effect: whichever ref is recorded *last* is what every reader
    (``<ctrl+p>``, ``<ctrl+g>``, ``<ctrl+space>``) sees first.
    """
    fake = tmp_path / "vcs_xprompt_mru.json"
    with patch.object(
        __import__("sase.history.vcs_xprompt_mru", fromlist=["_MRU_FILE"]),
        "_MRU_FILE",
        fake,
    ):
        record_vcs_xprompt_usage("#gh:projA")
        record_vcs_xprompt_usage("#gh:projB")
        result = _load_vcs_xprompt_mru()

    assert result[0] == "#gh:projB"
    assert result == ["#gh:projB", "#gh:projA"]


@pytest.mark.usefixtures("_reset_display_name_cache")
def test_load_launchable_pairs_returns_canonical_and_display_halves(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Pairs expose the on-disk key alongside the configured display name."""
    fake = tmp_path / "vcs_xprompt_mru.json"
    fake.write_text(json.dumps({"entries": ["#gh:gh_acme__widgets"]}))
    projects_dir = tmp_path / "projects"
    widgets_ws = tmp_path / "widgets-ws"
    widgets_ws.mkdir()
    _write_named_project(projects_dir, "gh_acme__widgets", "widgets", widgets_ws)

    monkeypatch.setattr(
        "sase.ace.tui.modals.project_discovery.detect_workflow_type",
        lambda _project_file: "git",
    )

    with patch.object(
        __import__("sase.history.vcs_xprompt_mru", fromlist=["_MRU_FILE"]),
        "_MRU_FILE",
        fake,
    ):
        result = load_launchable_vcs_xprompt_mru_pairs(projects_dir)

    assert result == [("#gh:gh_acme__widgets", "#gh:widgets")]


@pytest.mark.usefixtures("_reset_display_name_cache")
def test_load_launchable_pairs_agrees_with_display_only_accessor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The pairs accessor and the display-only accessor never disagree.

    Both are built from the same dedupe step, so the display halves of the
    pairs must exactly match (order and length) what
    :func:`load_launchable_vcs_xprompt_mru` returns.
    """
    fake = tmp_path / "vcs_xprompt_mru.json"
    fake.write_text(
        json.dumps({"entries": ["#gh:gh_acme__widgets", "#gh:widgets", "#gh:other"]})
    )
    projects_dir = tmp_path / "projects"
    widgets_ws = tmp_path / "widgets-ws"
    widgets_ws.mkdir()
    _write_named_project(projects_dir, "gh_acme__widgets", "widgets", widgets_ws)

    monkeypatch.setattr(
        "sase.ace.tui.modals.project_discovery.detect_workflow_type",
        lambda _project_file: "git",
    )

    with patch.object(
        __import__("sase.history.vcs_xprompt_mru", fromlist=["_MRU_FILE"]),
        "_MRU_FILE",
        fake,
    ):
        pairs = load_launchable_vcs_xprompt_mru_pairs(projects_dir)
        displays = load_launchable_vcs_xprompt_mru(projects_dir)

    assert [display for _, display in pairs] == displays
    assert displays == ["#gh:widgets", "#gh:other"]


def test_load_launchable_pairs_performs_at_most_one_pruning_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One call prunes and saves at most once, even though multiple entries
    are dropped."""
    fake = tmp_path / "vcs_xprompt_mru.json"
    fake.write_text(
        json.dumps({"entries": ["#gh:stale-one", "#gh:stale-two", "#gh:valid"]})
    )
    projects_dir = tmp_path / "projects"
    valid_workspace = tmp_path / "valid-workspace"
    valid_workspace.mkdir()
    _write_project(projects_dir, "valid", valid_workspace)
    _write_project(projects_dir, "stale-one", tmp_path / "missing-workspace-one")
    _write_project(projects_dir, "stale-two", tmp_path / "missing-workspace-two")

    monkeypatch.setattr(
        "sase.ace.tui.modals.project_discovery.detect_workflow_type",
        lambda _project_file: "git",
    )
    save_calls: list[list[str]] = []
    monkeypatch.setattr(
        "sase.history.vcs_xprompt_mru._save_vcs_xprompt_mru",
        lambda entries: save_calls.append(list(entries)),
    )

    with patch.object(
        __import__("sase.history.vcs_xprompt_mru", fromlist=["_MRU_FILE"]),
        "_MRU_FILE",
        fake,
    ):
        result = load_launchable_vcs_xprompt_mru_pairs(projects_dir)

    assert result == [("#gh:valid", "#gh:valid")]
    assert len(save_calls) == 1
    assert save_calls[0] == ["#gh:valid"]
