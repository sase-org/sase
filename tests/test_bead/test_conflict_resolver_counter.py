"""Counter-floor tests for the bead conflict resolver (sase-1vt.2).

A rollback-and-retry after a bead-ID collision must never re-mint the ID the
resolver relocated to. Both clones bump ``config.json`` ``next_counter`` to
the same value, so ``config.json`` merges cleanly and the old code (which
only raised the counter when ``config.json`` itself conflicted) left the
counter pointing at the relocated ID.
"""

from __future__ import annotations

import json
from pathlib import Path

from sase.bead.config import load_config, save_config
from sase.bead.conflict_resolver import (
    _resolve_bead_conflicts_from_cwd as resolve_bead_conflicts,
)
from sase.bead.ids import issue_id_for_counter, max_counter_in_ids
from sase.bead.model import IssueType
from sase.bead.project import BeadProject

from .conflict_resolver_test_helpers import _git, _init_repo


def _stream_ids(repo: Path) -> set[str]:
    streams_dir = repo / "sdd/beads/events/streams"
    return {path.stem for path in streams_dir.glob("*.jsonl")}


def _build_duplicate_creation_conflict(repo: Path) -> tuple[str, str]:
    """Diverge two branches that mint the same top-level bead ID.

    Returns the duplicated ID minted on both sides. ``config.json`` is
    byte-identical on both sides (same ``next_counter`` bump), so it merges
    cleanly while the duplicated stream file conflicts.
    """
    _init_repo(repo)
    with BeadProject.init(repo) as project:
        project.create("Base", IssueType.PLAN)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "base")

    _git(repo, "checkout", "-b", "other")
    with BeadProject(repo) as project:
        other_bead = project.create("Other", IssueType.PLAN)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "other")

    _git(repo, "checkout", "master")
    with BeadProject(repo) as project:
        local_bead = project.create("Local", IssueType.PLAN)
    assert local_bead.id == other_bead.id
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "local")

    _git(repo, "merge", "other", check=False)
    return other_bead.id


def test_clean_config_merge_still_advances_counter_past_relocation(
    tmp_path: Path,
) -> None:
    duplicated_id = _build_duplicate_creation_conflict(tmp_path)

    result = resolve_bead_conflicts(tmp_path)

    assert result.ok is True, result.message
    assert len(result.bead_relocations) == 1
    relocation = result.bead_relocations[0]
    assert relocation.old_id == duplicated_id
    beads_dir = tmp_path / "sdd/beads"
    prefix = str(load_config(beads_dir).get("issue_prefix", "beads"))
    stream_counters = max_counter_in_ids(prefix, _stream_ids(tmp_path))
    config = json.loads((beads_dir / "config.json").read_text(encoding="utf-8"))
    assert config["next_counter"] == stream_counters + 1
    assert max_counter_in_ids(prefix, [relocation.new_id]) < config["next_counter"]
    assert "sdd/beads/config.json" in result.resolved_files
    assert _git(tmp_path, "diff", "--name-only", "--diff-filter=U").stdout == ""


def test_create_after_removing_relocated_bead_mints_fresh_id(tmp_path: Path) -> None:
    duplicated_id = _build_duplicate_creation_conflict(tmp_path)

    result = resolve_bead_conflicts(tmp_path)

    assert result.ok is True, result.message
    relocated_id = result.bead_relocations[0].new_id
    _git(tmp_path, "commit", "-am", "resolve collision")
    beads_dir = tmp_path / "sdd/beads"
    prefix = str(load_config(beads_dir).get("issue_prefix", "beads"))
    resolved_counter = load_config(beads_dir)["next_counter"]
    assert isinstance(resolved_counter, int)
    with BeadProject(tmp_path) as project:
        project.remove(relocated_id)
        follow_up = project.create(
            "Follow up", IssueType.TASK, task_type="bug", size="small"
        )
    assert follow_up.id != duplicated_id
    assert follow_up.id != relocated_id
    assert follow_up.id == issue_id_for_counter(prefix, resolved_counter)


def test_same_stream_conflict_without_relocation_leaves_high_counter_untouched(
    tmp_path: Path,
) -> None:
    _init_repo(tmp_path)
    with BeadProject.init(tmp_path) as project:
        contested = project.create("Contested", IssueType.PLAN).id
    beads_dir = tmp_path / "sdd/beads"
    config = load_config(beads_dir)
    config["next_counter"] = 10
    save_config(beads_dir, config)
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-m", "base")
    before = (beads_dir / "config.json").read_bytes()

    _git(tmp_path, "checkout", "-b", "other")
    with BeadProject(tmp_path) as project:
        project.update(contested, notes="from other")
    _git(tmp_path, "commit", "-am", "other")

    _git(tmp_path, "checkout", "master")
    with BeadProject(tmp_path) as project:
        project.update(contested, design="from local")
    _git(tmp_path, "commit", "-am", "local")

    _git(tmp_path, "merge", "other", check=False)

    result = resolve_bead_conflicts(tmp_path)

    assert result.ok is True, result.message
    assert result.bead_relocations == ()
    assert (beads_dir / "config.json").read_bytes() == before
    assert "sdd/beads/config.json" not in result.resolved_files
    with BeadProject(tmp_path) as project:
        follow_up = project.create(
            "Follow up", IssueType.TASK, task_type="bug", size="small"
        )
    prefix = str(load_config(beads_dir).get("issue_prefix", "beads"))
    assert follow_up.id == issue_id_for_counter(prefix, 10)
