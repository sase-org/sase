"""Tests for the ConfirmRevertAgentModal and RevertPreview presentation."""

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import Button, Static

from sase.ace.revert_agent import (
    BulkRevertPreview,
    RepoRevertPlan,
    RevertCommit,
    RevertPreview,
    RevertTarget,
)
from sase.ace.tui.modals import ConfirmRevertAgentModal


class _TestApp(App[None]):
    ENABLE_COMMAND_PALETTE = False

    def compose(self) -> ComposeResult:
        yield from ()


def _commit(sha: str, subject: str, paths: tuple[str, ...] = ()) -> RevertCommit:
    return RevertCommit(
        sha=sha,
        full_sha=sha * 5,
        subject=subject,
        agent_tag="foo",
        changed_paths=paths,
    )


def _target(name: str) -> RevertTarget:
    return RevertTarget(
        agent_name=name,
        display_name=name,
        workspace_dir="/ws",
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
            _commit("aaa", "one", ("sdd/plans/a.md", "src/x.py")),
            _commit("bbb", "two", ("sdd/plans/a.md", "sdd/plans/b.md")),
        ),
    )
    assert preview.sdd_paths == ("sdd/plans/a.md", "sdd/plans/b.md")


def test_modal_commit_lines_truncate() -> None:
    commits = tuple(_commit(f"c{i:02d}", f"subject {i}") for i in range(13))
    preview = RevertPreview("foo", "agent", "/ws", commits)
    modal = ConfirmRevertAgentModal(preview)

    lines = modal._commit_lines().plain.splitlines()
    # 10 shown rows + 1 "and N more" line.
    assert len(lines) == 11
    assert lines[0] == "c00  subject 0"
    assert lines[-1] == "... and 3 more"


def test_modal_repo_commit_lines_and_blocked_summary() -> None:
    primary_commit = _commit("aaa", "primary")
    linked_commit = _commit("bbb", "linked")
    blocked_commit = _commit("ccc", "blocked")
    preview = RevertPreview(
        "foo",
        "agent",
        "/ws",
        (primary_commit, linked_commit),
        repos=(
            RepoRevertPlan("primary", "/ws", True, (primary_commit,)),
            RepoRevertPlan("sase-core", "/linked", False, (linked_commit,)),
            RepoRevertPlan(
                "sase-github",
                "/dirty",
                False,
                (blocked_commit,),
                blocked_reason="Workspace has uncommitted changes",
            ),
        ),
    )
    modal = ConfirmRevertAgentModal(preview)

    repo_lines = modal._repo_commit_lines().plain
    assert "primary primary" in repo_lines
    assert "sase-core linked" in repo_lines
    assert "1 commit(s)" in repo_lines
    assert "aaa  primary" in repo_lines
    assert "bbb  linked" in repo_lines
    blocked = modal._blocked_summary().plain
    assert "sase-github linked  BLOCKED" in blocked
    assert "1 commit(s) matched" in blocked
    assert "uncommitted" in blocked


def test_modal_sdd_summary_none_and_some() -> None:
    empty = ConfirmRevertAgentModal(RevertPreview("foo", "agent", "/ws", ()))
    assert empty._sdd_summary().plain == "SDD provenance: (none)"

    preview = RevertPreview(
        "foo",
        "agent",
        "/ws",
        (_commit("aaa", "one", ("sdd/plans/a.md",)),),
    )
    modal = ConfirmRevertAgentModal(preview)
    assert modal._sdd_summary().plain == "SDD provenance: sdd/plans/a.md"


def test_modal_sdd_summary_truncates_paths() -> None:
    paths = tuple(f"sdd/plans/{index}.md" for index in range(8))
    preview = RevertPreview(
        "foo",
        "agent",
        "/ws",
        (_commit("aaa", "one", paths),),
    )
    modal = ConfirmRevertAgentModal(preview)

    summary = modal._sdd_summary().plain
    assert "sdd/plans/0.md" in summary
    assert "sdd/plans/5.md" in summary
    assert "sdd/plans/6.md" not in summary
    assert "+2 more" in summary


def test_modal_bindings_cover_confirm_and_cancel() -> None:
    keys = {
        b.key if isinstance(b, Binding) else b[0]
        for b in ConfirmRevertAgentModal.BINDINGS
    }
    assert {"y", "n", "q", "escape"} <= keys
    assert {"j", "k", "down", "up"} <= keys


async def test_modal_composes_cards_and_focuses_cancel() -> None:
    primary_commit = _commit("aaa", "primary")
    linked_commit = _commit("bbb", "linked")
    blocked_commit = _commit("ccc", "blocked")
    preview = RevertPreview(
        "foo",
        "agent",
        "/ws",
        (primary_commit, linked_commit),
        repos=(
            RepoRevertPlan("primary", "/ws", True, (primary_commit,)),
            RepoRevertPlan("sase-core", "/linked", False, (linked_commit,)),
            RepoRevertPlan(
                "sase-github",
                "/dirty",
                False,
                (blocked_commit,),
                blocked_reason="Workspace has uncommitted changes",
            ),
        ),
    )

    async with _TestApp().run_test() as pilot:
        modal = ConfirmRevertAgentModal(preview)
        pilot.app.push_screen(modal)
        await pilot.pause()

        assert modal.query_one("#cancel-btn", Button).has_focus
        repo_cards = modal.query(".revert-confirm-repo-card").nodes
        blocked_cards = modal.query(".revert-confirm-blocked-card").nodes
        assert len(repo_cards) == 2
        assert len(blocked_cards) == 1
        assert all(isinstance(card, Static) for card in repo_cards + blocked_cards)


# ---------------------------------------------------------------------------
# Bulk preview rendering
# ---------------------------------------------------------------------------


def test_bulk_preview_ok_and_counts() -> None:
    preview = BulkRevertPreview(
        workspace_dir="/ws",
        targets=(_target("foo"), _target("bar")),
        commits=(_commit("aaa", "one"), _commit("bbb", "two")),
        matched_target_names=("foo", "bar"),
    )
    assert preview.ok
    assert preview.commit_count == 2
    assert preview.target_count == 2


def test_modal_detects_bulk_preview() -> None:
    single = ConfirmRevertAgentModal(RevertPreview("foo", "agent", "/ws", ()))
    bulk = ConfirmRevertAgentModal(
        BulkRevertPreview(
            workspace_dir="/ws",
            targets=(_target("foo"),),
            commits=(_commit("aaa", "one"),),
            matched_target_names=("foo",),
        )
    )
    assert single._is_bulk is False
    assert bulk._is_bulk is True


def test_modal_bulk_commit_lines_and_skipped_summary() -> None:
    commits = tuple(_commit(f"c{i:02d}", f"subject {i}") for i in range(13))
    preview = BulkRevertPreview(
        workspace_dir="/ws",
        targets=(_target("foo"), _target("bar"), _target("baz")),
        commits=commits,
        matched_target_names=("foo", "bar"),
        skipped_target_names=("baz",),
    )
    modal = ConfirmRevertAgentModal(preview)

    lines = modal._commit_lines().plain.splitlines()
    # 10 shown rows + 1 "and N more" line, shared with the single-agent path.
    assert len(lines) == 11
    assert lines[-1] == "... and 3 more"
    assert modal._skipped_summary().plain == "Skipped (no commits): baz"


def test_modal_bulk_skipped_summary_none() -> None:
    preview = BulkRevertPreview(
        workspace_dir="/ws",
        targets=(_target("foo"),),
        commits=(_commit("aaa", "one"),),
        matched_target_names=("foo",),
    )
    modal = ConfirmRevertAgentModal(preview)
    assert modal._skipped_summary().plain == "Skipped (no commits): (none)"


def test_modal_bulk_skipped_summary_truncates_names() -> None:
    preview = BulkRevertPreview(
        workspace_dir="/ws",
        targets=(_target("foo"),),
        commits=(_commit("aaa", "one"),),
        matched_target_names=("foo",),
        skipped_target_names=tuple(f"skip-{index}" for index in range(8)),
    )
    modal = ConfirmRevertAgentModal(preview)

    summary = modal._skipped_summary().plain
    assert "skip-0" in summary
    assert "skip-5" in summary
    assert "skip-6" not in summary
    assert "+2 more" in summary
