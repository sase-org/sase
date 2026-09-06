"""Tests for bead event stream conflict resolution behavior."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from sase.bead import conflict_resolver_git
from sase.bead._stream_integrity import prepare_event_streams_for_commit
from sase.bead.conflict_resolver import resolve_bead_conflicts
from sase.bead.model import IssueType
from sase.bead.project import BEADS_DIRNAME, BeadProject
from sase.core import bead_mutation_facade

from .conflict_resolver_test_helpers import (
    _assert_config_roundtrips_save_config,
    _build_stream_conflict,
    _git,
    _init_repo,
)


def test_resolution_leaves_untouched_streams_alone(tmp_path: Path) -> None:
    contested, quiet = _build_stream_conflict(tmp_path, bystanders=3)
    streams = tmp_path / BEADS_DIRNAME / "events" / "streams"
    quiet_paths = [streams / f"{stream_id}.jsonl" for stream_id in quiet]
    quiet_mtimes = {path: path.stat().st_mtime_ns for path in quiet_paths}

    result = resolve_bead_conflicts(tmp_path, beads_dir=tmp_path / BEADS_DIRNAME)

    assert result.ok is True, result.message
    assert set(result.resolved_files) == {
        contested,
        f"{BEADS_DIRNAME}/events/manifest.json",
        f"{BEADS_DIRNAME}/issues.jsonl",
    }
    assert {path: path.stat().st_mtime_ns for path in quiet_paths} == quiet_mtimes
    staged = _git(tmp_path, "diff", "--cached", "--name-only").stdout.split()
    assert not [path for path in staged if any(name in path for name in quiet)]
    merged = (tmp_path / contested).read_text(encoding="utf-8")
    assert "from local" in merged and "from other" in merged


def test_duplicate_top_level_creations_report_typed_relocation(
    tmp_path: Path,
) -> None:
    _init_repo(tmp_path)
    (tmp_path / ".gitignore").write_text("beads/beads.db*\n", encoding="utf-8")
    with BeadProject.init(tmp_path, beads_dirname=BEADS_DIRNAME):
        pass
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-m", "seed empty bead store")

    _git(tmp_path, "checkout", "-b", "other")
    upstream, _ = bead_mutation_facade.create(
        tmp_path / BEADS_DIRNAME,
        title="Upstream wins",
        issue_type=IssueType.PLAN,
        now="2026-08-20T00:00:00Z",
    )
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-m", f"other creates {upstream.id}")

    _git(tmp_path, "checkout", "master")
    local, _ = bead_mutation_facade.create(
        tmp_path / BEADS_DIRNAME,
        title="Local relocates",
        issue_type=IssueType.PLAN,
        now="2026-08-20T00:00:01Z",
    )
    assert local.id == upstream.id
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-m", f"local creates {local.id}")
    _git(tmp_path, "merge", "other", check=False)

    result = resolve_bead_conflicts(tmp_path, beads_dir=tmp_path / BEADS_DIRNAME)

    assert result.ok is True, result.message
    assert len(result.bead_relocations) == 1
    relocation = result.bead_relocations[0]
    assert relocation.old_id == local.id
    assert relocation.new_id == f"{local.id.rsplit('-', 1)[0]}-2"
    assert relocation.kind == "top_level_duplicate"
    assert f"{relocation.old_id} -> {relocation.new_id}" in result.message
    relocated_stream = (
        tmp_path / BEADS_DIRNAME / "events" / "streams" / f"{relocation.new_id}.jsonl"
    ).read_text(encoding="utf-8")
    assert f'"issue_id":"{relocation.old_id}"' not in relocated_stream
    assert f'"issue_id":"{relocation.new_id}"' in relocated_stream
    with BeadProject(tmp_path, beads_dirname=BEADS_DIRNAME) as project:
        assert project.show(upstream.id).title == "Upstream wins"
        assert project.show(relocation.new_id).title == "Local relocates"


def test_unequal_mint_counts_merge_config_json_and_relocate_duplicate(
    tmp_path: Path,
) -> None:
    _init_repo(tmp_path)
    (tmp_path / ".gitignore").write_text("beads/beads.db*\n", encoding="utf-8")
    with BeadProject.init(tmp_path, beads_dirname=BEADS_DIRNAME):
        pass
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-m", "seed empty bead store")

    _git(tmp_path, "checkout", "-b", "other")
    upstream_ids: list[str] = []
    for index, title in enumerate(
        ("Upstream first", "Upstream second", "Upstream third")
    ):
        issue, _ = bead_mutation_facade.create(
            tmp_path / BEADS_DIRNAME,
            title=title,
            issue_type=IssueType.PLAN,
            now=f"2026-08-20T00:00:0{index}Z",
        )
        upstream_ids.append(issue.id)
    upstream_counter = json.loads(
        (tmp_path / BEADS_DIRNAME / "config.json").read_text(encoding="utf-8")
    )["next_counter"]
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-m", "other mints three")

    _git(tmp_path, "checkout", "master")
    local, _ = bead_mutation_facade.create(
        tmp_path / BEADS_DIRNAME,
        title="Local relocates",
        issue_type=IssueType.PLAN,
        now="2026-08-20T00:00:10Z",
    )
    assert local.id == upstream_ids[0]
    local_counter = json.loads(
        (tmp_path / BEADS_DIRNAME / "config.json").read_text(encoding="utf-8")
    )["next_counter"]
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-m", f"local creates {local.id}")
    _git(tmp_path, "merge", "other", check=False)

    conflicted = _git(tmp_path, "diff", "--name-only", "--diff-filter=U").stdout.split()
    config_relpath = f"{BEADS_DIRNAME}/config.json"
    assert config_relpath in conflicted

    result = resolve_bead_conflicts(tmp_path, beads_dir=tmp_path / BEADS_DIRNAME)

    assert result.ok is True, result.message
    assert result.resolved_files.count(config_relpath) == 1
    assert len(result.bead_relocations) == 1
    relocation = result.bead_relocations[0]
    assert relocation.old_id == local.id
    assert relocation.new_id not in upstream_ids
    relocated_counter = int(relocation.new_id.rsplit("-", 1)[1], 36)
    merged = json.loads(
        (tmp_path / BEADS_DIRNAME / "config.json").read_text(encoding="utf-8")
    )
    assert merged["next_counter"] >= local_counter
    assert merged["next_counter"] >= upstream_counter
    assert merged["next_counter"] > relocated_counter
    _assert_config_roundtrips_save_config(tmp_path / BEADS_DIRNAME, tmp_path)
    with BeadProject(tmp_path, beads_dirname=BEADS_DIRNAME) as project:
        assert project.show(upstream_ids[0]).title == "Upstream first"
        assert project.show(upstream_ids[1]).title == "Upstream second"
        assert project.show(upstream_ids[2]).title == "Upstream third"
        assert project.show(relocation.new_id).title == "Local relocates"


def test_resolution_preserves_non_ascii_bytes_in_untouched_streams(
    tmp_path: Path,
) -> None:
    """The Rust writer emits unescaped UTF-8; escaping it here churns every file."""
    _contested, quiet = _build_stream_conflict(
        tmp_path, bystanders=2, bystander_label="Quiét — ünicode"
    )
    streams = tmp_path / BEADS_DIRNAME / "events" / "streams"
    quiet_paths = [streams / f"{stream_id}.jsonl" for stream_id in quiet]
    quiet_bytes = {path: path.read_bytes() for path in quiet_paths}
    assert all(b"Qui\xc3\xa9t" in data for data in quiet_bytes.values())
    # Written by the Rust store writer, and the merge changes no manifest field.
    manifest_path = tmp_path / BEADS_DIRNAME / "events" / "manifest.json"
    manifest_bytes = manifest_path.read_bytes()

    result = resolve_bead_conflicts(tmp_path, beads_dir=tmp_path / BEADS_DIRNAME)

    assert result.ok is True, result.message
    assert {path: path.read_bytes() for path in quiet_paths} == quiet_bytes
    assert manifest_path.read_bytes() == manifest_bytes
    staged = _git(tmp_path, "diff", "--cached", "--name-only").stdout.split()
    assert not [path for path in staged if any(name in path for name in quiet)]
    issues = (tmp_path / BEADS_DIRNAME / "issues.jsonl").read_bytes()
    assert b"Qui\xc3\xa9t" in issues
    assert b"\\u" not in issues


@pytest.mark.parametrize(
    ("legacy_notes", "expected_legacy_note_texts"),
    [
        ("", []),
        ("a pre-existing legacy note", ["a pre-existing legacy note"]),
    ],
)
def test_resolution_preserves_legacy_notes_event_bytes_in_conflicted_stream(
    tmp_path: Path,
    legacy_notes: str,
    expected_legacy_note_texts: list[str],
) -> None:
    contested, _quiet = _build_stream_conflict(
        tmp_path,
        legacy_notes=legacy_notes,
    )
    legacy_line = _git(tmp_path, "show", f":2:{contested}").stdout.splitlines()[0]
    assert f'"notes":{json.dumps(legacy_notes)}' in legacy_line

    result = resolve_bead_conflicts(tmp_path, beads_dir=tmp_path / BEADS_DIRNAME)

    assert result.ok is True, result.message
    resolved = (tmp_path / contested).read_text(encoding="utf-8")
    assert resolved.startswith(f"{legacy_line}\n")
    assert "from local" in resolved and "from other" in resolved
    assert prepare_event_streams_for_commit(tmp_path, [contested]).restored_paths == ()
    with BeadProject(tmp_path, beads_dirname=BEADS_DIRNAME) as project:
        issue = project.show(Path(contested).stem)
    assert [note.text for note in issue.notes] == [
        *expected_legacy_note_texts,
        "from other",
    ]


def test_failed_stage_read_does_not_silently_drop_one_side(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unreadable conflict stage is an error, not an empty stream."""
    contested, _quiet = _build_stream_conflict(tmp_path)
    real_run_git = conflict_resolver_git._run_git

    def fail_stage_read(cwd: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
        if args[:1] == ["show"]:
            return subprocess.CompletedProcess(
                ["git", *args], 128, stdout="", stderr="fatal: injected show failure"
            )
        return real_run_git(cwd, args)

    monkeypatch.setattr(conflict_resolver_git, "_run_git", fail_stage_read)

    result = resolve_bead_conflicts(tmp_path, beads_dir=tmp_path / BEADS_DIRNAME)

    assert result.ok is False
    assert f"could not read stage 1 of {contested}" in result.message
