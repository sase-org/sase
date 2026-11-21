"""Low-level tree-scan and ID-extraction coverage.

Split from ``tests.test_artifact_protection_scan``; the original module
re-exports these tests so its import path keeps working.
"""

from __future__ import annotations

from pathlib import Path

__all__ = [
    "test_extract_artifact_ids_matches_expected_cases",
    "test_projects_tree_scan_finds_spec_and_prunes_shared_dirs",
    "test_projects_tree_walk_skips_artifacts_repos_and_git",
    "test_scan_root_does_not_descend_symlinked_dirs",
]


def test_projects_tree_walk_skips_artifacts_repos_and_git() -> None:
    from sase.core._sidecar_protection_label import PROJECTS_TREE_SKIP_DIRS

    assert PROJECTS_TREE_SKIP_DIRS == frozenset({".git", "artifacts", "repos"})


def test_projects_tree_scan_finds_spec_and_prunes_shared_dirs(
    tmp_path: Path,
) -> None:
    from sase.core.artifact_file_protection import _scan_root

    projects = tmp_path / "projects"
    projects.mkdir()
    kept = "default:111111111111111111111111"
    dropped_artifacts = "default:222222222222222222222222"
    dropped_repos = "default:333333333333333333333333"
    dropped_git = "default:444444444444444444444444"
    (projects / "proj.sase").write_text(f"id {kept}\n", encoding="utf-8")
    artifacts = projects / "artifacts"
    artifacts.mkdir()
    (artifacts / "other.sase").write_text(dropped_artifacts, encoding="utf-8")
    repos = projects / "repos"
    repos.mkdir()
    (repos / "other.sase").write_text(dropped_repos, encoding="utf-8")
    git = projects / ".git"
    git.mkdir()
    (git / "other.sase").write_text(dropped_git, encoding="utf-8")

    ids: set[str] = set()
    scanned: set[str] = set()
    unavailable: set[str] = set()
    _scan_root(
        projects,
        ids=ids,
        scanned=scanned,
        unavailable=unavailable,
        required=True,
        suffixes=frozenset({".sase"}),
        skip_dir_names=frozenset({".git", "artifacts", "repos"}),
    )

    assert ids == {kept}
    assert unavailable == set()


def test_scan_root_does_not_descend_symlinked_dirs(tmp_path: Path) -> None:
    import os

    from sase.core.artifact_file_protection import _scan_root

    root = tmp_path / "root"
    root.mkdir()
    kept = "default:aaaaaaaaaaaaaaaaaaaaaaaa"
    dropped = "explicit:bbbbbbbbbbbbbbbbbbbbbbbb"
    (root / "keep.sase").write_text(kept, encoding="utf-8")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "other.sase").write_text(dropped, encoding="utf-8")
    os.symlink(outside, root / "linked", target_is_directory=True)

    ids: set[str] = set()
    scanned: set[str] = set()
    unavailable: set[str] = set()
    _scan_root(
        root,
        ids=ids,
        scanned=scanned,
        unavailable=unavailable,
        required=True,
        suffixes=frozenset({".sase"}),
    )

    assert ids == {kept}


def test_extract_artifact_ids_matches_expected_cases() -> None:
    from sase.core.artifact_file_protection import _extract_artifact_ids

    kept_default = "default:111111111111111111111111"
    kept_explicit = "explicit:222222222222222222222222"
    assert _extract_artifact_ids(f"file:{kept_default}") == (kept_default,)
    assert _extract_artifact_ids(kept_explicit) == (kept_explicit,)
    assert set(_extract_artifact_ids(f"({kept_default}), and {kept_explicit}.")) == {
        kept_default,
        kept_explicit,
    }
    # Uppercase hex is not a candidate.
    assert _extract_artifact_ids("default:AAAAAAAAAAAAAAAAAAAAAAAA") == ()
    # No candidate tokens: prefilter returns empty without scanning.
    assert _extract_artifact_ids("nothing to protect here\n") == ()
