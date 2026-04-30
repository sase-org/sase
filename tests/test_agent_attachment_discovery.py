"""Tests for agent attachment source discovery."""

from pathlib import Path

from sase.axe.image_attachments import collect_agent_markdown_paths


def test_collect_agent_markdown_paths_from_working_tree(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    (tmp_path / "existing.txt").write_text("base\n")
    (tmp_path / "changed.md").write_text("old\n")
    _run(tmp_path, "git", "add", ".")
    _run(tmp_path, "git", "commit", "-m", "base")

    (tmp_path / "changed.md").write_text("new\n")
    (tmp_path / "notes.markdown").write_text("# Notes\n")
    (tmp_path / "ignored.txt").write_text("ignore\n")

    assert collect_agent_markdown_paths(str(tmp_path)) == [
        str((tmp_path / "changed.md").resolve()),
        str((tmp_path / "notes.markdown").resolve()),
    ]


def test_collect_agent_markdown_paths_keeps_untracked_after_tracked(
    tmp_path: Path,
) -> None:
    _init_repo(tmp_path)
    (tmp_path / "tracked.md").write_text("base\n")
    _run(tmp_path, "git", "add", ".")
    _run(tmp_path, "git", "commit", "-m", "base")

    (tmp_path / "tracked.md").write_text("changed\n")
    (tmp_path / "untracked.md").write_text("new\n")

    assert collect_agent_markdown_paths(str(tmp_path)) == [
        str((tmp_path / "tracked.md").resolve()),
        str((tmp_path / "untracked.md").resolve()),
    ]


def test_collect_agent_markdown_paths_from_diff_file_when_tree_clean(
    tmp_path: Path,
) -> None:
    source = tmp_path / "research" / "result.md"
    source.parent.mkdir()
    source.write_text("# Result\n")
    diff_path = tmp_path / "commit.diff"
    diff_path.write_text(
        "diff --git a/research/result.md b/research/result.md\n"
        "new file mode 100644\n"
        "--- /dev/null\n"
        "+++ b/research/result.md\n"
    )

    assert collect_agent_markdown_paths(str(tmp_path), diff_path=str(diff_path)) == [
        str(source.resolve())
    ]


def test_collect_agent_markdown_paths_from_head_commit(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    (tmp_path / "base.txt").write_text("base\n")
    _run(tmp_path, "git", "add", ".")
    _run(tmp_path, "git", "commit", "-m", "base")

    markdown = tmp_path / "committed.markdown"
    markdown.write_text("# Committed\n")
    _run(tmp_path, "git", "add", ".")
    _run(tmp_path, "git", "commit", "-m", "add markdown")

    assert collect_agent_markdown_paths(str(tmp_path), include_head_commit=True) == [
        str(markdown.resolve())
    ]


def test_collect_agent_markdown_paths_from_rename(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    (tmp_path / "old.md").write_text("# Old\n")
    _run(tmp_path, "git", "add", ".")
    _run(tmp_path, "git", "commit", "-m", "base")

    (tmp_path / "docs").mkdir()
    _run(tmp_path, "git", "mv", "old.md", "docs/new.md")

    assert collect_agent_markdown_paths(str(tmp_path)) == [
        str((tmp_path / "docs" / "new.md").resolve())
    ]


def test_collect_agent_markdown_paths_ignores_deleted_missing_and_non_markdown(
    tmp_path: Path,
) -> None:
    _init_repo(tmp_path)
    (tmp_path / "deleted.md").write_text("# Deleted\n")
    (tmp_path / "notes.txt").write_text("base\n")
    _run(tmp_path, "git", "add", ".")
    _run(tmp_path, "git", "commit", "-m", "base")

    (tmp_path / "deleted.md").unlink()
    (tmp_path / "notes.txt").write_text("changed\n")
    (tmp_path / "missing.md").write_text("# Missing\n")
    diff_path = tmp_path / "proposal.diff"
    diff_path.write_text(
        "diff --git a/missing.md b/missing.md\n"
        "new file mode 100644\n"
        "--- /dev/null\n"
        "+++ b/missing.md\n"
    )
    (tmp_path / "missing.md").unlink()

    assert collect_agent_markdown_paths(str(tmp_path), diff_path=str(diff_path)) == []


def test_collect_agent_markdown_paths_excludes_artifacts_dir(
    tmp_path: Path,
) -> None:
    _init_repo(tmp_path)
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()
    artifact = artifacts_dir / "response.md"
    artifact.write_text("# Response\n")
    source = tmp_path / "source.md"
    source.write_text("# Source\n")

    assert collect_agent_markdown_paths(
        str(tmp_path), artifacts_dir=str(artifacts_dir)
    ) == [str(source.resolve())]


def test_collect_agent_markdown_paths_dedupes_against_existing_and_sources(
    tmp_path: Path,
) -> None:
    _init_repo(tmp_path)
    tracked = tmp_path / "tracked.md"
    skipped = tmp_path / "skipped.md"
    tracked.write_text("base\n")
    skipped.write_text("base\n")
    _run(tmp_path, "git", "add", ".")
    _run(tmp_path, "git", "commit", "-m", "base")

    tracked.write_text("changed\n")
    skipped.write_text("changed\n")
    untracked = tmp_path / "untracked.md"
    untracked.write_text("new\n")
    diff_path = tmp_path / "commit.diff"
    diff_path.write_text(
        "diff --git a/tracked.md b/tracked.md\n"
        "--- a/tracked.md\n"
        "+++ b/tracked.md\n"
        "diff --git a/untracked.md b/untracked.md\n"
        "--- /dev/null\n"
        "+++ b/untracked.md\n"
    )

    assert collect_agent_markdown_paths(
        str(tmp_path),
        diff_path=str(diff_path),
        existing_files=[str(skipped)],
    ) == [
        str(tracked.resolve()),
        str(untracked.resolve()),
    ]


def _init_repo(cwd: Path) -> None:
    _run(cwd, "git", "init")
    _run(cwd, "git", "config", "user.email", "test@example.com")
    _run(cwd, "git", "config", "user.name", "Test User")


def _run(cwd: Path, *args: str) -> None:
    import subprocess

    subprocess.run(args, cwd=cwd, check=True, capture_output=True, text=True)
