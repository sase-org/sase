"""Tests for root-store bead conflict resolver behavior."""

from __future__ import annotations

from pathlib import Path

from sase.bead.conflict_resolver import resolve_bead_conflicts
from sase.bead.project import BEADS_DIRNAME, BEADS_DIRNAME_ROOT, BeadProject
from sase.bead_pages.paths import bead_page_path

from .conflict_resolver_test_helpers import (
    _build_root_page_conflict,
    _build_root_store_and_page_conflict,
    _build_root_store_conflict,
    _build_stream_conflict,
    _git,
    _init_repo,
)


def test_root_store_event_stream_conflict_is_mergeable(tmp_path: Path) -> None:
    contested, _quiet = _build_stream_conflict(
        tmp_path,
        beads_dirname=BEADS_DIRNAME_ROOT,
    )

    result = resolve_bead_conflicts(tmp_path, beads_dir=tmp_path)

    assert result.ok is True, result.message
    assert contested in result.resolved_files
    assert "events/manifest.json" in result.resolved_files
    assert "issues.jsonl" in result.resolved_files


def test_root_store_page_only_conflict_takes_upstream_without_store_merge(
    tmp_path: Path,
) -> None:
    page = _build_root_page_conflict(tmp_path)

    result = resolve_bead_conflicts(tmp_path, beads_dir=tmp_path)

    assert result.ok is True, result.message
    assert result.resolved_files == (page,)
    assert (tmp_path / page).read_text(encoding="utf-8") == "upstream\n"
    assert _git(tmp_path, "diff", "--name-only", "--diff-filter=U").stdout == ""
    assert _git(tmp_path, "diff", "--cached", "--name-only").stdout.split() == [page]


def test_root_store_page_conflict_accepts_upstream_deletion(
    tmp_path: Path,
) -> None:
    page = _build_root_page_conflict(tmp_path, upstream_deletes=True)

    result = resolve_bead_conflicts(tmp_path, beads_dir=tmp_path)

    assert result.ok is True, result.message
    assert result.resolved_files == (page,)
    assert not (tmp_path / page).exists()
    assert _git(tmp_path, "diff", "--name-only", "--diff-filter=U").stdout == ""
    assert _git(tmp_path, "diff", "--cached", "--name-status").stdout == (
        f"D\t{page}\n"
    )


def test_root_store_mixed_page_and_store_conflicts_resolve(
    tmp_path: Path,
) -> None:
    contested, page = _build_root_store_and_page_conflict(tmp_path)

    result = resolve_bead_conflicts(tmp_path, beads_dir=tmp_path)

    assert result.ok is True, result.message
    assert set(result.resolved_files) == {
        contested,
        "events/manifest.json",
        "issues.jsonl",
        page,
    }
    assert (tmp_path / page).read_text(encoding="utf-8") == "upstream\n"
    assert _git(tmp_path, "diff", "--name-only", "--diff-filter=U").stdout == ""
    merged = (tmp_path / contested).read_text(encoding="utf-8")
    assert "from local" in merged and "from upstream" in merged


def test_root_store_readme_conflict_is_not_a_bead_conflict(tmp_path: Path) -> None:
    _build_root_store_conflict(tmp_path, conflict_stream=False)

    result = resolve_bead_conflicts(tmp_path, beads_dir=tmp_path)

    assert result.ok is False
    assert result.message == "non-bead conflicts remain: README.md"


def test_root_store_mixed_conflicts_are_refused(tmp_path: Path) -> None:
    issue_id = _build_root_store_conflict(tmp_path, conflict_stream=True)

    result = resolve_bead_conflicts(tmp_path, beads_dir=tmp_path)

    assert result.ok is False
    assert result.message == "non-bead conflicts remain: README.md"
    assert f"events/streams/{issue_id}.jsonl" not in result.resolved_files


def test_prefixed_store_page_conflict_is_still_unsupported(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    with BeadProject.init(tmp_path, beads_dirname=BEADS_DIRNAME):
        pass
    page = f"{BEADS_DIRNAME}/{bead_page_path('sase-ai')}"
    page_path = tmp_path / page
    page_path.parent.mkdir(parents=True)
    page_path.write_text("base\n", encoding="utf-8")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-m", "base")

    _git(tmp_path, "checkout", "-b", "other")
    page_path.write_text("upstream\n", encoding="utf-8")
    _git(tmp_path, "commit", "-am", "other")
    _git(tmp_path, "checkout", "master")
    page_path.write_text("local\n", encoding="utf-8")
    _git(tmp_path, "commit", "-am", "local")
    _git(tmp_path, "merge", "other", check=False)

    result = resolve_bead_conflicts(tmp_path, beads_dir=tmp_path / BEADS_DIRNAME)

    assert result.ok is False
    assert result.message == f"unsupported bead conflicts: {page}"
