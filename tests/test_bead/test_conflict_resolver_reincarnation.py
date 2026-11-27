"""Regression coverage for published create/remove/create stream history."""

from __future__ import annotations

from pathlib import Path
import subprocess

from sase.bead.config import load_config, save_config
from sase.bead.model import IssueType
from sase.bead.project import BeadProject
from sase.sdd._semantic_conflict_resolver import resolve_semantic_conflicts

from .sync_conflict_regression_helpers import _clone, _commit, _git
from .sync_test_helpers import init_git_repo


def _seed_empty_remote(tmp_path: Path) -> tuple[Path, Path, Path]:
    remote = tmp_path / "reincarnation.git"
    subprocess.run(
        ["git", "init", "--bare", "--initial-branch=main", str(remote)],
        check=True,
        capture_output=True,
        text=True,
    )
    seed = tmp_path / "reincarnation-seed"
    seed.mkdir()
    init_git_repo(seed)
    _git(seed, "branch", "-M", "main")
    (seed / ".gitignore").write_text("beads/beads.db*\n", encoding="utf-8")
    with BeadProject.init(seed, beads_dirname="beads"):
        pass
    _commit(seed, "seed empty bead store")
    _git(seed, "remote", "add", "origin", str(remote))
    _git(seed, "push", "-u", "origin", "main")

    local = tmp_path / "reincarnation-local"
    upstream = tmp_path / "reincarnation-upstream"
    _clone(remote, local)
    _clone(remote, upstream)
    return remote, local, upstream


def test_resolves_rebase_with_published_create_remove_create_history(
    tmp_path: Path,
) -> None:
    _remote, local, upstream = _seed_empty_remote(tmp_path)

    with BeadProject(local, beads_dirname="beads") as project:
        local_epic = project.create("Local epic", IssueType.PLAN)
        local_phase = project.create(
            "Local phase", IssueType.PHASE, parent_id=local_epic.id
        )
    _commit(local, "local creates colliding epic graph", "beads")

    with BeadProject(upstream, beads_dirname="beads") as project:
        first_epic = project.create("Published first epic", IssueType.PLAN)
        project.create(
            "Published first phase", IssueType.PHASE, parent_id=first_epic.id
        )
        project.remove(first_epic.id)

    assert first_epic.id == local_epic.id
    config = load_config(upstream / "beads")
    config["next_counter"] = 1
    save_config(upstream / "beads", config)
    with BeadProject(upstream, beads_dirname="beads") as project:
        recreated_epic = project.create("Published latest epic", IssueType.PLAN)
        recreated_phase = project.create(
            "Published latest phase", IssueType.PHASE, parent_id=recreated_epic.id
        )
    assert recreated_epic.id == first_epic.id
    assert recreated_phase.id == local_phase.id
    _commit(upstream, "upstream recreates published epic", "beads")
    _git(upstream, "push")

    _git(local, "fetch", "origin")
    rebase = _git(local, "rebase", "origin/main", check=False)
    assert rebase.returncode != 0
    assert _git(local, "diff", "--name-only", "--diff-filter=U").stdout.strip()

    resolution = resolve_semantic_conflicts(local, beads_dir=local / "beads")

    assert resolution.ok, resolution.message
    assert f"relocated duplicate beads: {local_epic.id} -> " in resolution.message
    assert _git(local, "diff", "--name-only", "--diff-filter=U").stdout == ""

    relocated_id = next(
        relocation.new_id
        for relocation in resolution.bead_relocations
        if relocation.old_id == local_epic.id
    )
    with BeadProject(local, beads_dirname="beads") as project:
        issues = {issue.id: issue for issue in project.list_issues()}
    assert issues[recreated_epic.id].title == "Published latest epic"
    assert issues[recreated_phase.id].title == "Published latest phase"
    assert issues[relocated_id].title == "Local epic"
    assert issues[f"{relocated_id}.1"].title == "Local phase"
