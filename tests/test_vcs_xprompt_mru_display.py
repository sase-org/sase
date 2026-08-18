"""Display-name tests for sase.history.vcs_xprompt_mru.

Covers the split between the canonical directory key stored on disk and the
configured ``PROJECT_NAME`` shown to users: humanization, alias-aware
pruning and recording, and the pairs accessor that exposes both halves.
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
from tests._vcs_xprompt_mru_helpers import (
    patch_discovered_workflow_type_as_git,
    patched_mru_file,
    write_named_project,
)
from tests.conftest import redirect_sase_home


@pytest.fixture
def _reset_display_name_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    """Clear the module-level, mtime-keyed display-name cache before a test."""
    import sase.project_display_names as pdn

    monkeypatch.setattr(pdn, "_PROJECT_DISPLAY_NAME_CACHE", None)


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
    write_named_project(projects_dir, "gh_acme__widgets", "widgets", widgets_ws)
    write_named_project(
        projects_dir, "gh_acme__stale", "stale", tmp_path / "missing-ws"
    )

    patch_discovered_workflow_type_as_git(monkeypatch)

    with patched_mru_file(fake):
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
    write_named_project(projects_dir, "gh_acme__widgets", "widgets", widgets_ws)

    patch_discovered_workflow_type_as_git(monkeypatch)

    with patched_mru_file(fake):
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
    write_named_project(projects_dir, "proj_widgets", "widgets", workspace)
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
    patch_discovered_workflow_type_as_git(monkeypatch)

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
    write_named_project(projects_dir, "gh_acme__widgets", "widgets", workspace)
    mru_file = sase_home / "vcs_xprompt_mru.json"
    mru_file.write_text(json.dumps({"entries": ["#gh:gh_acme__widgets", "#gh:other"]}))

    patch_discovered_workflow_type_as_git(monkeypatch)

    record_vcs_xprompt_usage("#gh:widgets")

    assert _load_vcs_xprompt_mru() == ["#gh:gh_acme__widgets", "#gh:other"]


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
    write_named_project(projects_dir, "gh_acme__widgets", "widgets", widgets_ws)

    patch_discovered_workflow_type_as_git(monkeypatch)

    with patched_mru_file(fake):
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
    write_named_project(projects_dir, "gh_acme__widgets", "widgets", widgets_ws)

    patch_discovered_workflow_type_as_git(monkeypatch)

    with patched_mru_file(fake):
        pairs = load_launchable_vcs_xprompt_mru_pairs(projects_dir)
        displays = load_launchable_vcs_xprompt_mru(projects_dir)

    assert [display for _, display in pairs] == displays
    assert displays == ["#gh:widgets", "#gh:other"]
