"""Tests for the ConfirmRevertAgentModal and RevertPreview presentation."""

from __future__ import annotations

from textual.binding import Binding

from sase.ace.revert_agent import RevertCommit, RevertPreview
from sase.ace.tui.modals import ConfirmRevertAgentModal


def _commit(sha: str, subject: str, paths: tuple[str, ...] = ()) -> RevertCommit:
    return RevertCommit(
        sha=sha,
        full_sha=sha * 5,
        subject=subject,
        agent_tag="foo",
        changed_paths=paths,
    )


def test_preview_ok_and_counts() -> None:
    preview = RevertPreview(
        agent_name="foo",
        scope="agent",
        workspace_dir="/ws",
        commits=(_commit("aaa", "one"), _commit("bbb", "two")),
    )
    assert preview.ok
    assert preview.commit_count == 2


def test_preview_not_ok_when_error_or_empty() -> None:
    assert not RevertPreview("foo", "agent", "/ws", (), error="boom").ok
    assert not RevertPreview("foo", "agent", "/ws", ()).ok


def test_preview_sdd_paths_dedup_in_order() -> None:
    preview = RevertPreview(
        agent_name="foo",
        scope="family",
        workspace_dir="/ws",
        commits=(
            _commit("aaa", "one", ("sdd/tales/a.md", "src/x.py")),
            _commit("bbb", "two", ("sdd/tales/a.md", "sdd/epics/b.md")),
        ),
    )
    assert preview.sdd_paths == ("sdd/tales/a.md", "sdd/epics/b.md")


def test_modal_commit_lines_truncate() -> None:
    commits = tuple(_commit(f"c{i:02d}", f"subject {i}") for i in range(13))
    preview = RevertPreview("foo", "agent", "/ws", commits)
    modal = ConfirmRevertAgentModal(preview)

    lines = modal._commit_lines().splitlines()
    # 10 shown rows + 1 "and N more" line.
    assert len(lines) == 11
    assert lines[0] == "c00  subject 0"
    assert lines[-1] == "... and 3 more"


def test_modal_sdd_summary_none_and_some() -> None:
    empty = ConfirmRevertAgentModal(RevertPreview("foo", "agent", "/ws", ()))
    assert empty._sdd_summary() == "SDD files: (none)"

    preview = RevertPreview(
        "foo",
        "agent",
        "/ws",
        (_commit("aaa", "one", ("sdd/tales/a.md",)),),
    )
    modal = ConfirmRevertAgentModal(preview)
    assert modal._sdd_summary() == "SDD files: sdd/tales/a.md"


def test_modal_bindings_cover_confirm_and_cancel() -> None:
    keys = {
        b.key if isinstance(b, Binding) else b[0]
        for b in ConfirmRevertAgentModal.BINDINGS
    }
    assert {"y", "n", "q", "escape"} <= keys
