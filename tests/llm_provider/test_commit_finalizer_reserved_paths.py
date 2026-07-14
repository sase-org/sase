"""Commit-finalizer handling for SASE-managed repository metadata."""

from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

from sase.llm_provider import commit_finalizer_git, commit_finalizer_state
from sase.llm_provider.commit_finalizer_types import SiblingTarget


def _init_tracked_metadata_repo(path: Path) -> None:
    path.mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"], cwd=path, check=True
    )
    subprocess.run(["git", "config", "user.name", "Test"], cwd=path, check=True)
    metadata = [
        path / ".sase" / "state.json",
        path / "sase" / "repos" / "plans" / "plan.md",
    ]
    for item in metadata:
        item.parent.mkdir(parents=True, exist_ok=True)
        item.write_text("before\n", encoding="utf-8")
    subprocess.run(["git", "add", "-f", "."], cwd=path, check=True)
    subprocess.run(["git", "commit", "-qm", "initial"], cwd=path, check=True)
    for item in metadata:
        item.write_text("after\n", encoding="utf-8")


def test_changed_files_filter_only_root_scoped_reserved_paths() -> None:
    status = "\n".join(
        [
            "?? sase/repos/plans/plan.md",
            '?? "sase/repos/plans/quoted file.md"',
            "?? .sase/sdd/state.json",
            "R  src/old.py -> sase/repos/linked/core/old.py",
            "R  .sase/old.json -> src/restored.json",
            "?? sasefoo/kept.txt",
            "?? src/sase/repos/kept.txt",
            "?? nested/.sase/kept.txt",
            "R  src/before.py -> src/after.py",
        ]
    )

    assert commit_finalizer_git._changed_files_from_git_status(status) == [
        "sasefoo/kept.txt",
        "src/sase/repos/kept.txt",
        "nested/.sase/kept.txt",
        "src/before.py -> src/after.py",
    ]


def test_external_dirty_scan_ignores_metadata_and_reports_mixed_dirt(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "external"
    _init_tracked_metadata_repo(repo)
    records = {
        "gh:acme/widget": {
            "ref": "gh:acme/widget",
            "workspace_dir": str(repo),
        }
    }

    assert commit_finalizer_state._dirty_opened_external_repos(records) == []

    (repo / "dirty.txt").write_text("agent work\n", encoding="utf-8")
    dirty = commit_finalizer_state._dirty_opened_external_repos(records)

    assert len(dirty) == 1
    assert dirty[0].changed_files == ("dirty.txt",)


def test_linked_dirty_scan_ignores_metadata_and_reports_mixed_dirt(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "linked"
    _init_tracked_metadata_repo(repo)
    targets = [SiblingTarget(name="core", workspace_dir=str(repo))]

    assert commit_finalizer_state._dirty_configured_sibling_repos(targets) == []

    (repo / "src.py").write_text("agent work\n", encoding="utf-8")
    dirty = commit_finalizer_state._dirty_configured_sibling_repos(targets)

    assert len(dirty) == 1
    assert dirty[0].changed_files == ("src.py",)


@pytest.mark.parametrize(
    ("changed_files", "expected"),
    [
        ([".sase/state.json", "sase/repos/plans/plan.md"], []),
        ([".sase/state.json", "src/feature.py"], ["src/feature.py"]),
    ],
)
def test_main_commit_details_filter_reserved_metadata(
    changed_files: list[str],
    expected: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.llm_provider.commit_finalizer.build_commit_details",
        lambda _project_dir: (
            True,
            changed_files,
            "commit instruction",
            "unfiltered details",
        ),
    )

    has_changes, files, instruction, details = (
        commit_finalizer_state._build_commit_details("/repo")
    )

    assert has_changes is bool(expected)
    assert files == expected
    if expected:
        assert instruction == "commit instruction"
        assert ".sase/state.json" not in details
        assert "src/feature.py" in details
    else:
        assert instruction == ""
        assert details == ""
