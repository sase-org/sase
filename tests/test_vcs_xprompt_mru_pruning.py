"""Launchability pruning tests for sase.history.vcs_xprompt_mru.

Covers which persisted entries survive a load or a record: stale projects,
the implicit ``#git:home`` default, refs that resolve to nothing, and refs
whose prefix disagrees with the project's real VCS provider.
"""

import json
from pathlib import Path

import pytest

from sase.history.vcs_xprompt_mru import (
    _load_vcs_xprompt_mru,
    load_launchable_vcs_xprompt_mru,
    load_launchable_vcs_xprompt_mru_pairs,
    record_vcs_xprompt_usage,
)
from sase.workspace_provider import reset_workflow_metadata_caches
from sase.workspace_provider._hookspec import WorkflowMetadata
from tests._vcs_xprompt_mru_helpers import (
    patch_discovered_workflow_type_as_git,
    patched_mru_file,
    write_named_project,
    write_project,
)
from tests._workspace_provider_helpers import (
    _restore_xprompt_vcs_caches_on_teardown,
    git_metadata,
)
from tests.conftest import redirect_sase_home


class _FakePatch:
    def __init__(self, name: str) -> None:
        self.name = name


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


def test_load_launchable_filters_known_stale_projects(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = tmp_path / "vcs_xprompt_mru.json"
    fake.write_text(json.dumps({"entries": ["#gh:stale", "#gh:branch", "#gh:valid"]}))
    projects_dir = tmp_path / "projects"
    valid_workspace = tmp_path / "valid-workspace"
    valid_workspace.mkdir()
    write_project(projects_dir, "valid", valid_workspace)
    write_project(projects_dir, "stale", tmp_path / "missing-workspace")

    patch_discovered_workflow_type_as_git(monkeypatch)

    with patched_mru_file(fake):
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
    write_project(projects_dir, "home", home_workspace)

    patch_discovered_workflow_type_as_git(monkeypatch)

    with patched_mru_file(fake):
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
    write_project(projects_dir, "valid", valid_workspace)
    write_project(projects_dir, "project", tmp_path / "missing-workspace")

    patch_discovered_workflow_type_as_git(monkeypatch)

    with patched_mru_file(fake):
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
    with patched_mru_file(fake):
        record_vcs_xprompt_usage("#git:home")
        result = _load_vcs_xprompt_mru()

    assert result == ["#gh:sase"]
    assert json.loads(fake.read_text()) == {"entries": ["#gh:sase"]}


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
    write_named_project(projects_dir, "gh_sase-org__sase", "sase", sase_ws)
    write_named_project(projects_dir, "otherproj", "otherproj", other_ws)
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
    patch_discovered_workflow_type_as_git(monkeypatch)
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
    write_named_project(projects_dir, "gh_sase-org__sase", "sase", sase_ws)
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
    patch_discovered_workflow_type_as_git(monkeypatch)
    monkeypatch.setattr(
        "sase.workspace_provider.detect_workflow_type",
        lambda _project_file: "gh",
    )

    record_vcs_xprompt_usage("#git:gh_sase-org__sase")

    assert _load_vcs_xprompt_mru() == ["#gh:gh_sase-org__sase"]


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
    write_project(projects_dir, "valid", valid_workspace)
    write_project(projects_dir, "stale-one", tmp_path / "missing-workspace-one")
    write_project(projects_dir, "stale-two", tmp_path / "missing-workspace-two")

    patch_discovered_workflow_type_as_git(monkeypatch)
    save_calls: list[list[str]] = []
    monkeypatch.setattr(
        "sase.history.vcs_xprompt_mru._save_vcs_xprompt_mru",
        lambda entries: save_calls.append(list(entries)),
    )

    with patched_mru_file(fake):
        result = load_launchable_vcs_xprompt_mru_pairs(projects_dir)

    assert result == [("#gh:valid", "#gh:valid")]
    assert len(save_calls) == 1
    assert save_calls[0] == ["#gh:valid"]
