"""Tests for agent attachment source discovery."""

import socket
from pathlib import Path

from sase.axe.image_attachments import DiffScan, ExtraRepoScan
from sase.axe.image_attachments import collect_agent_image_paths
from sase.axe.image_attachments import collect_agent_markdown_paths
from sase.axe.image_attachments import collect_agent_video_paths
from sase.sdd.files import is_sdd_internal_path


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
    source = tmp_path / "sdd" / "research" / "result.md"
    source.parent.mkdir(parents=True)
    source.write_text("# Result\n")
    diff_path = tmp_path / "commit.diff"
    diff_path.write_text(
        "diff --git a/sdd/research/result.md b/sdd/research/result.md\n"
        "new file mode 100644\n"
        "--- /dev/null\n"
        "+++ b/sdd/research/result.md\n"
    )

    assert collect_agent_markdown_paths(str(tmp_path), diff_path=str(diff_path)) == [
        str(source.resolve())
    ]


def test_collect_agent_paths_resolve_diff_scan_against_nested_repo(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _init_repo(workspace)
    (workspace / ".gitignore").write_text("sase/repos/research/\n")
    _run(workspace, "git", "add", ".")
    _run(workspace, "git", "commit", "-m", "base")

    research_repo = workspace / "sase" / "repos" / "research"
    research_repo.mkdir(parents=True)
    _init_repo(research_repo)
    markdown = research_repo / "202607" / "report.md"
    image = research_repo / "202607" / "diagram.png"
    markdown.parent.mkdir()
    markdown.write_text("# Report\n")
    image.write_bytes(b"png")
    _run(research_repo, "git", "add", ".")
    _run(research_repo, "git", "commit", "-m", "add report")

    diff_path = tmp_path / "research.diff"
    diff_path.write_text(
        "diff --git a/202607/report.md b/202607/report.md\n"
        "new file mode 100644\n"
        "--- /dev/null\n"
        "+++ b/202607/report.md\n"
        "diff --git a/202607/diagram.png b/202607/diagram.png\n"
        "new file mode 100644\n"
        "--- /dev/null\n"
        "+++ b/202607/diagram.png\n"
    )
    scan = DiffScan(str(diff_path), str(research_repo))

    assert collect_agent_markdown_paths(str(workspace), diff_scans=[scan]) == [
        str(markdown.resolve())
    ]
    assert collect_agent_image_paths(str(workspace), diff_scans=[scan]) == [
        str(image.resolve())
    ]


def test_collect_agent_markdown_paths_from_multiple_diff_scans(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _init_repo(workspace)
    first = workspace / "docs" / "first.md"
    first.parent.mkdir()
    first.write_text("# First\n")
    _run(workspace, "git", "add", ".")
    _run(workspace, "git", "commit", "-m", "add first")

    second_repo = tmp_path / "second"
    second_repo.mkdir()
    _init_repo(second_repo)
    second = second_repo / "notes" / "second.md"
    second.parent.mkdir()
    second.write_text("# Second\n")
    _run(second_repo, "git", "add", ".")
    _run(second_repo, "git", "commit", "-m", "add second")

    first_diff = tmp_path / "first.diff"
    first_diff.write_text(
        "diff --git a/docs/first.md b/docs/first.md\n"
        "new file mode 100644\n"
        "--- /dev/null\n"
        "+++ b/docs/first.md\n"
    )
    second_diff = tmp_path / "second.diff"
    second_diff.write_text(
        "diff --git a/notes/second.md b/notes/second.md\n"
        "new file mode 100644\n"
        "--- /dev/null\n"
        "+++ b/notes/second.md\n"
    )

    assert collect_agent_markdown_paths(
        str(workspace),
        diff_scans=[
            DiffScan(str(first_diff), str(workspace)),
            DiffScan(str(second_diff), str(second_repo)),
        ],
    ) == [str(first.resolve()), str(second.resolve())]


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


def test_collect_agent_paths_from_extra_repo_base_range_and_untracked(
    tmp_path: Path,
) -> None:
    primary = tmp_path / "workspace"
    primary.mkdir()
    _init_repo(primary)
    (primary / "base.txt").write_text("base\n")
    _run(primary, "git", "add", ".")
    _run(primary, "git", "commit", "-m", "base")

    extra = tmp_path / "sdd"
    extra.mkdir()
    _init_repo(extra)
    (extra / "research").mkdir()
    (extra / "images").mkdir()
    (extra / "research" / "before.md").write_text("# Before\n")
    (extra / "images" / "before.png").write_bytes(b"before")
    _run(extra, "git", "add", ".")
    _run(extra, "git", "commit", "-m", "before base")
    base_sha = _run(extra, "git", "rev-parse", "HEAD")

    committed_md = extra / "research" / "after.md"
    committed_image = extra / "images" / "after.png"
    untracked_md = extra / "research" / "untracked.md"
    untracked_image = extra / "images" / "untracked.webp"
    committed_md.write_text("# After\n")
    committed_image.write_bytes(b"after")
    _run(extra, "git", "add", ".")
    _run(
        extra,
        "git",
        "commit",
        "-m",
        "after base\n\nSASE_AGENT=agent",
    )
    untracked_md.write_text("# Untracked\n")
    untracked_image.write_bytes(b"untracked")

    scan = ExtraRepoScan(
        str(extra),
        base_sha,
        agent_name="agent",
        include_working_tree=True,
    )
    assert collect_agent_markdown_paths(str(primary), extra_repo_scans=()) == []
    assert collect_agent_markdown_paths(
        str(primary),
        extra_repo_scans=[scan],
    ) == [
        str(committed_md.resolve()),
        str(untracked_md.resolve()),
    ]
    assert collect_agent_image_paths(str(primary), extra_repo_scans=[scan]) == [
        str(committed_image.resolve()),
        str(untracked_image.resolve()),
    ]


def test_extra_repo_commit_paths_require_matching_agent_and_machine_tags(
    tmp_path: Path,
) -> None:
    primary = tmp_path / "workspace"
    primary.mkdir()
    _init_repo(primary)

    extra = tmp_path / "sdd"
    extra.mkdir()
    _init_repo(extra)
    (extra / "base.txt").write_text("base\n")
    _run(extra, "git", "add", ".")
    _run(extra, "git", "commit", "-m", "base")
    base_sha = _run(extra, "git", "rev-parse", "HEAD")

    expected: list[str] = []
    for filename, agent_tag in (
        ("own.md", "agent"),
        ("hood.md", "agent.research"),
        ("family.md", "agent--plan-0"),
    ):
        path = extra / filename
        path.write_text(f"# {filename}\n")
        _run(extra, "git", "add", ".")
        _run(
            extra,
            "git",
            "commit",
            "-m",
            f"add {filename}\n\nSASE_AGENT={agent_tag}",
        )
        expected.append(str(path.resolve()))

    foreign = extra / "foreign.md"
    foreign.write_text("# Foreign\n")
    _run(extra, "git", "add", ".")
    _run(
        extra,
        "git",
        "commit",
        "-m",
        "foreign\n\nSASE_AGENT=other-agent",
    )

    untagged = extra / "untagged.md"
    untagged.write_text("# Untagged\n")
    _run(extra, "git", "add", ".")
    _run(extra, "git", "commit", "-m", "untagged")

    other_machine = extra / "other-machine.md"
    other_machine.write_text("# Other machine\n")
    _run(extra, "git", "add", ".")
    _run(
        extra,
        "git",
        "commit",
        "-m",
        (
            "other machine\n\nSASE_AGENT=agent\n"
            f"SASE_MACHINE={socket.gethostname()}-other"
        ),
    )

    assert (
        collect_agent_markdown_paths(
            str(primary),
            extra_repo_scans=[ExtraRepoScan(str(extra), base_sha, agent_name="agent")],
        )
        == expected
    )


def test_extra_repo_working_tree_paths_are_opt_in(tmp_path: Path) -> None:
    primary = tmp_path / "workspace"
    primary.mkdir()
    _init_repo(primary)

    extra = tmp_path / "sdd"
    extra.mkdir()
    _init_repo(extra)
    tracked = extra / "tracked.md"
    tracked.write_text("base\n")
    _run(extra, "git", "add", ".")
    _run(extra, "git", "commit", "-m", "base")
    base_sha = _run(extra, "git", "rev-parse", "HEAD")

    tracked.write_text("changed\n")
    untracked = extra / "untracked.md"
    untracked.write_text("new\n")

    assert (
        collect_agent_markdown_paths(
            str(primary),
            extra_repo_scans=[ExtraRepoScan(str(extra), base_sha, agent_name="agent")],
        )
        == []
    )
    assert collect_agent_markdown_paths(
        str(primary),
        extra_repo_scans=[
            ExtraRepoScan(
                str(extra),
                base_sha,
                agent_name="agent",
                include_working_tree=True,
            )
        ],
    ) == [str(tracked.resolve()), str(untracked.resolve())]


def test_extra_repo_scan_can_exclude_sdd_internal_paths(tmp_path: Path) -> None:
    primary = tmp_path / "workspace"
    primary.mkdir()
    _init_repo(primary)

    extra = tmp_path / "sdd"
    extra.mkdir()
    _init_repo(extra)
    (extra / "base.txt").write_text("base\n")
    _run(extra, "git", "add", ".")
    _run(extra, "git", "commit", "-m", "base")
    base_sha = _run(extra, "git", "rev-parse", "HEAD")

    paths = {
        "plans/202607/foo.md": "# Plan\n",
        "plans/202607/prompts/foo.md": "# Prompt\n",
        "prompts/202607/legacy.md": "# Legacy prompt\n",
        "specs/202607/legacy.md": "# Legacy spec\n",
        "beads/issue.md": "# Bead\n",
        "README.md": "# SDD\n",
        "plans/README.md": "# Plans\n",
        "research/README.md": "# Research\n",
        "sdd/README.md": "# Nested SDD\n",
        "research/202607/result.md": "# Research result\n",
        "notes/custom.md": "# Custom document\n",
    }
    for rel_path, content in paths.items():
        path = extra / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    _run(extra, "git", "add", ".")
    _run(
        extra,
        "git",
        "commit",
        "-m",
        "add SDD files\n\nSASE_AGENT=agent",
    )

    unfiltered_scan = ExtraRepoScan(str(extra), base_sha, agent_name="agent")
    unfiltered = collect_agent_markdown_paths(
        str(primary), extra_repo_scans=[unfiltered_scan]
    )
    assert set(unfiltered) == {str((extra / rel_path).resolve()) for rel_path in paths}

    filtered_scan = ExtraRepoScan(
        str(extra),
        base_sha,
        agent_name="agent",
        exclude=is_sdd_internal_path,
    )
    assert collect_agent_markdown_paths(
        str(primary), extra_repo_scans=[filtered_scan]
    ) == [
        str((extra / "notes/custom.md").resolve()),
        str((extra / "plans/202607/foo.md").resolve()),
        str((extra / "research/202607/result.md").resolve()),
    ]


def test_collect_agent_video_paths_from_working_tree(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    (tmp_path / "existing.txt").write_text("base\n")
    (tmp_path / "changed.mp4").write_bytes(b"old")
    _run(tmp_path, "git", "add", ".")
    _run(tmp_path, "git", "commit", "-m", "base")

    (tmp_path / "changed.mp4").write_bytes(b"new")
    (tmp_path / "clip.webm").write_bytes(b"webm")
    (tmp_path / "ignored.txt").write_text("ignore\n")

    assert collect_agent_video_paths(str(tmp_path)) == [
        str((tmp_path / "changed.mp4").resolve()),
        str((tmp_path / "clip.webm").resolve()),
    ]


def test_collect_agent_video_paths_from_diff_file_when_tree_clean(
    tmp_path: Path,
) -> None:
    video = tmp_path / "renders" / "result.mov"
    video.parent.mkdir()
    video.write_bytes(b"mov")
    diff_path = tmp_path / "commit.diff"
    diff_path.write_text(
        "diff --git a/renders/result.mov b/renders/result.mov\n"
        "new file mode 100644\n"
        "--- /dev/null\n"
        "+++ b/renders/result.mov\n"
    )

    assert collect_agent_video_paths(str(tmp_path), diff_path=str(diff_path)) == [
        str(video.resolve())
    ]


def test_collect_agent_video_paths_from_head_commit(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    (tmp_path / "base.txt").write_text("base\n")
    _run(tmp_path, "git", "add", ".")
    _run(tmp_path, "git", "commit", "-m", "base")

    video = tmp_path / "committed.m4v"
    video.write_bytes(b"m4v")
    _run(tmp_path, "git", "add", ".")
    _run(tmp_path, "git", "commit", "-m", "add video")

    assert collect_agent_video_paths(str(tmp_path), include_head_commit=True) == [
        str(video.resolve())
    ]


def test_collect_agent_video_paths_ignores_deleted_missing_and_unsupported(
    tmp_path: Path,
) -> None:
    _init_repo(tmp_path)
    (tmp_path / "deleted.mp4").write_bytes(b"mp4")
    (tmp_path / "notes.txt").write_text("base\n")
    _run(tmp_path, "git", "add", ".")
    _run(tmp_path, "git", "commit", "-m", "base")

    (tmp_path / "deleted.mp4").unlink()
    (tmp_path / "notes.txt").write_text("changed\n")
    (tmp_path / "missing.webm").write_bytes(b"webm")
    diff_path = tmp_path / "proposal.diff"
    diff_path.write_text(
        "diff --git a/missing.webm b/missing.webm\n"
        "new file mode 100644\n"
        "--- /dev/null\n"
        "+++ b/missing.webm\n"
    )
    (tmp_path / "missing.webm").unlink()

    assert collect_agent_video_paths(str(tmp_path), diff_path=str(diff_path)) == []


def test_collect_agent_video_paths_dedupes_against_existing_and_sources(
    tmp_path: Path,
) -> None:
    _init_repo(tmp_path)
    tracked = tmp_path / "tracked.mp4"
    skipped = tmp_path / "skipped.mp4"
    tracked.write_bytes(b"base")
    skipped.write_bytes(b"base")
    _run(tmp_path, "git", "add", ".")
    _run(tmp_path, "git", "commit", "-m", "base")

    tracked.write_bytes(b"changed")
    skipped.write_bytes(b"changed")
    untracked = tmp_path / "untracked.mov"
    untracked.write_bytes(b"new")
    diff_path = tmp_path / "commit.diff"
    diff_path.write_text(
        "diff --git a/tracked.mp4 b/tracked.mp4\n"
        "--- a/tracked.mp4\n"
        "+++ b/tracked.mp4\n"
        "diff --git a/untracked.mov b/untracked.mov\n"
        "--- /dev/null\n"
        "+++ b/untracked.mov\n"
    )

    assert collect_agent_video_paths(
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


def _run(cwd: Path, *args: str) -> str:
    import subprocess

    result = subprocess.run(args, cwd=cwd, check=True, capture_output=True, text=True)
    return result.stdout.strip()
