"""Persistence regressions for suffix transforms using stale Patch snapshots."""

from dataclasses import replace
from pathlib import Path

from sase.ace.patch import (
    CommentEntry,
    HookEntry,
    HookStatusLine,
    parse_project_file,
)
from sase.ace.comments import transform_patch_comments_field
from sase.ace.hooks import (
    transform_patch_hooks_field,
    update_hook_status_line_suffix_type,
)
from sase.ace.scheduler.suffix_transforms import (
    strip_old_entry_error_markers,
    strip_terminal_status_markers,
)


def _write_project(project_file: Path, body: str) -> None:
    project_file.write_text(
        "## ChangeSpec\n"
        "NAME: terminal_change\n"
        "DESCRIPTION:\n"
        "  Terminal suffix cleanup regression\n"
        "STATUS: Submitted\n"
        f"{body}",
        encoding="utf-8",
    )


def test_hook_transform_writes_only_for_material_change(tmp_path: Path) -> None:
    project_file = tmp_path / "project.sase"
    _write_project(
        project_file,
        "HOOKS:\n  lint\n      | (1) [260720_120000] FAILED - (!: ZOMBIE)\n",
    )

    def strip_errors(hooks: list[HookEntry]) -> list[HookEntry]:
        return [
            replace(
                hook,
                status_lines=[
                    replace(status_line, suffix_type="plain")
                    if status_line.suffix_type == "error"
                    else status_line
                    for status_line in hook.status_lines or []
                ],
            )
            for hook in hooks
        ]

    assert transform_patch_hooks_field(
        str(project_file), "terminal_change", strip_errors
    )
    inode_after_change = project_file.stat().st_ino

    assert not transform_patch_hooks_field(
        str(project_file), "terminal_change", strip_errors
    )
    assert project_file.stat().st_ino == inode_after_change
    assert not transform_patch_hooks_field(
        str(project_file), "missing_change", strip_errors
    )


def test_targeted_hook_suffix_update_is_idempotent(tmp_path: Path) -> None:
    project_file = tmp_path / "project.sase"
    _write_project(
        project_file,
        "HOOKS:\n  lint\n      | (1) [260720_120000] FAILED - (!: ZOMBIE)\n",
    )

    assert update_hook_status_line_suffix_type(
        str(project_file), "terminal_change", "lint", "1", "plain"
    )
    inode_after_change = project_file.stat().st_ino

    assert not update_hook_status_line_suffix_type(
        str(project_file), "terminal_change", "lint", "1", "plain"
    )
    assert project_file.stat().st_ino == inode_after_change


def test_terminal_hook_cleanup_does_not_restore_old_entry_marker(
    tmp_path: Path,
) -> None:
    project_file = tmp_path / "project.sase"
    _write_project(
        project_file,
        "COMMITS:\n"
        "  (1) First commit\n"
        "  (2) Current commit\n"
        "HOOKS:\n"
        "  lint\n"
        "      | (1) [260720_120000] FAILED - (!: ZOMBIE)\n"
        "      | (2) [260720_130000] FAILED - (!: Hook Command Failed)\n",
    )
    stale_patch = parse_project_file(str(project_file))[0]

    concurrent_hook = HookEntry(
        command="current_hook",
        status_lines=[
            HookStatusLine(
                commit_entry_num="2",
                timestamp="260720_140000",
                status="PASSED",
                suffix="current data",
                suffix_type="plain",
            )
        ],
    )
    assert transform_patch_hooks_field(
        str(project_file),
        "terminal_change",
        lambda hooks: [*hooks, concurrent_hook],
    )

    old_entry_updates = strip_old_entry_error_markers(stale_patch)
    assert len(old_entry_updates) == 1
    assert "(1)" in old_entry_updates[0]

    terminal_updates = strip_terminal_status_markers(stale_patch)
    assert len(terminal_updates) == 1
    assert "(2)" in terminal_updates[0]

    current = parse_project_file(str(project_file))[0]
    lint = next(hook for hook in current.hooks or [] if hook.command == "lint")
    assert all(line.suffix_type != "error" for line in lint.status_lines or [])
    current_hook = next(
        hook for hook in current.hooks or [] if hook.command == "current_hook"
    )
    assert current_hook.status_lines
    assert current_hook.status_lines[0].suffix == "current data"

    inode_after_cleanup = project_file.stat().st_ino
    assert strip_terminal_status_markers(stale_patch) == []
    assert project_file.stat().st_ino == inode_after_cleanup


def test_terminal_running_hook_becomes_killed_agent(tmp_path: Path) -> None:
    project_file = tmp_path / "project.sase"
    _write_project(
        project_file,
        "HOOKS:\n"
        "  lint\n"
        "      | (1) [260720_120000] RUNNING "
        "- (@: fix_hook-12345-260720_120000)\n",
    )
    stale_patch = parse_project_file(str(project_file))[0]

    updates = strip_terminal_status_markers(stale_patch)

    assert len(updates) == 1
    current_line = parse_project_file(str(project_file))[0].hooks[0].status_lines[0]
    assert current_line.suffix_type == "killed_agent"
    assert current_line.suffix == "fix_hook-12345-260720_120000"


def test_terminal_comment_cleanup_preserves_concurrent_changes(
    tmp_path: Path,
) -> None:
    project_file = tmp_path / "project.sase"
    _write_project(
        project_file,
        "COMMENTS:\n  [alice] /alice.json - (!: ZOMBIE)\n  [bob] /bob-old.json - (2)\n",
    )
    stale_patch = parse_project_file(str(project_file))[0]

    concurrent_comment = CommentEntry(reviewer="carol", file_path="/carol.json")

    def mutate_unrelated_comment(
        comments: list[CommentEntry],
    ) -> list[CommentEntry]:
        return [
            replace(comment, file_path="/bob-current.json")
            if comment.reviewer == "bob"
            else comment
            for comment in comments
        ] + [concurrent_comment]

    assert transform_patch_comments_field(
        str(project_file),
        "terminal_change",
        mutate_unrelated_comment,
    )

    updates = strip_terminal_status_markers(stale_patch)
    assert updates == ["Cleared COMMENT [alice] suffix: ZOMBIE"]

    current_comments = parse_project_file(str(project_file))[0].comments or []
    comments_by_reviewer = {comment.reviewer: comment for comment in current_comments}
    assert comments_by_reviewer["alice"].suffix is None
    assert comments_by_reviewer["bob"].file_path == "/bob-current.json"
    assert comments_by_reviewer["bob"].suffix == "2"
    assert comments_by_reviewer["carol"] == concurrent_comment

    inode_after_cleanup = project_file.stat().st_ino
    assert strip_terminal_status_markers(stale_patch) == []
    assert project_file.stat().st_ino == inode_after_cleanup
