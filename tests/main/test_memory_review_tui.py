"""Tests for the interactive memory proposal review app."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from textual.widgets import DataTable, Static

from sase.ace.tui.widgets.single_line_vim_text_area import SingleLineVimTextArea
from sase.memory.proposals import (
    ProposalAuthor,
    ProposalReviewer,
    approve_memory_proposal,
    create_memory_proposal,
    read_memory_proposals,
    reject_memory_proposal,
)
from sase.memory.review_tui import MemoryReviewTuiApp


def _create_proposal(
    tmp_path: Path,
    *,
    proposal_id: str,
    title: str,
    body: str,
    target: str,
) -> str:
    result = create_memory_proposal(
        title=title,
        body=body,
        evidence_values=["chat:abc"],
        target=target,
        author=ProposalAuthor("agent-a", "SASE_AGENT_NAME", None),
        cwd=tmp_path,
        proposal_id=proposal_id,
    )
    return result.state.proposal_id


def _setup_review_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    monkeypatch.delenv("SASE_AGENT_NAME", raising=False)
    monkeypatch.delenv("SASE_AGENT", raising=False)
    monkeypatch.delenv("SASE_ARTIFACTS_DIR", raising=False)


def _detail_plain(app: MemoryReviewTuiApp) -> str:
    detail = app.query_one("#memory-review-detail", Static)
    renderable = detail.content
    return getattr(renderable, "plain", str(renderable))


async def test_memory_review_tui_opens_with_pending_rows_and_preview(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _setup_review_state(tmp_path, monkeypatch)
    first_id = _create_proposal(
        tmp_path,
        proposal_id="mem-20260523-120000-11111111",
        title="First memory",
        body="First body\n",
        target="first.md",
    )
    _create_proposal(
        tmp_path,
        proposal_id="mem-20260523-120001-22222222",
        title="Second memory",
        body="Second body\n",
        target="second.md",
    )

    app = MemoryReviewTuiApp(cwd=tmp_path)
    async with app.run_test() as pilot:
        await pilot.pause()

        table = app.query_one("#memory-review-table", DataTable)
        assert table.row_count == 2
        assert app.selected_proposal_id == first_id
        assert "First memory" in _detail_plain(app)


async def test_memory_review_tui_navigation_updates_preview(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _setup_review_state(tmp_path, monkeypatch)
    _create_proposal(
        tmp_path,
        proposal_id="mem-20260523-120000-11111111",
        title="First memory",
        body="First body\n",
        target="first.md",
    )
    second_id = _create_proposal(
        tmp_path,
        proposal_id="mem-20260523-120001-22222222",
        title="Second memory",
        body="Second body\n",
        target="second.md",
    )

    app = MemoryReviewTuiApp(cwd=tmp_path)
    async with app.run_test() as pilot:
        await pilot.press("j")
        await pilot.pause()

        assert app.selected_proposal_id == second_id
        assert "Second memory" in _detail_plain(app)


async def test_memory_review_tui_honors_initial_proposal_selection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _setup_review_state(tmp_path, monkeypatch)
    _create_proposal(
        tmp_path,
        proposal_id="mem-20260523-120000-11111111",
        title="First memory",
        body="First body\n",
        target="first.md",
    )
    second_id = _create_proposal(
        tmp_path,
        proposal_id="mem-20260523-120001-22222222",
        title="Second memory",
        body="Second body\n",
        target="second.md",
    )

    app = MemoryReviewTuiApp(initial_proposal_id=second_id, cwd=tmp_path)
    async with app.run_test() as pilot:
        await pilot.pause()

        assert app.selected_proposal_id == second_id
        assert "Second memory" in _detail_plain(app)


async def test_memory_review_tui_drill_down_opens_and_exits(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _setup_review_state(tmp_path, monkeypatch)
    _create_proposal(
        tmp_path,
        proposal_id="mem-20260523-120000-11111111",
        title="First memory",
        body="First body\n",
        target="first.md",
    )

    app = MemoryReviewTuiApp(cwd=tmp_path)
    async with app.run_test() as pilot:
        await pilot.press("d")
        await pilot.pause()
        assert app.view_mode == "detail"
        assert "Evidence" in _detail_plain(app)
        assert "Audit" in _detail_plain(app)

        await pilot.press("escape")
        await pilot.pause()
        assert app.view_mode == "list"


async def test_memory_review_tui_reject_modal_dispatches_domain_rejection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _setup_review_state(tmp_path, monkeypatch)
    proposal_id = _create_proposal(
        tmp_path,
        proposal_id="mem-20260523-120000-11111111",
        title="First memory",
        body="First body\n",
        target="first.md",
    )
    calls: list[tuple[str, str]] = []

    def reject_callback(proposal_ref: str, reason: str) -> Any:
        calls.append((proposal_ref, reason))
        return reject_memory_proposal(
            proposal_ref,
            reason=reason,
            reviewer=ProposalReviewer("reviewer", "host"),
            cwd=tmp_path,
        )

    app = MemoryReviewTuiApp(reject_callback=reject_callback, cwd=tmp_path)
    async with app.run_test() as pilot:
        await pilot.press("r")
        await pilot.pause()
        input_widget = app.screen.query_one(
            "#memory-review-input", SingleLineVimTextArea
        )
        input_widget.text = "Not durable"
        await pilot.press("enter")
        await pilot.pause()

    assert calls == [(proposal_id, "Not durable")]
    assert read_memory_proposals()[0].status == "rejected"


async def test_memory_review_tui_approve_dispatches_domain_approval(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _setup_review_state(tmp_path, monkeypatch)
    proposal_id = _create_proposal(
        tmp_path,
        proposal_id="mem-20260523-120000-11111111",
        title="First memory",
        body="First body\n",
        target="first.md",
    )
    calls: list[tuple[str, str | None, str | Path | None]] = []

    def approve_callback(
        proposal_ref: str,
        target: str | None,
        edited_file: str | Path | None,
    ) -> Any:
        calls.append((proposal_ref, target, edited_file))
        return approve_memory_proposal(
            proposal_ref,
            target=target,
            edited_file=edited_file,
            reviewer=ProposalReviewer("reviewer", "host"),
            cwd=tmp_path,
        )

    app = MemoryReviewTuiApp(approve_callback=approve_callback, cwd=tmp_path)
    async with app.run_test() as pilot:
        await pilot.press("a")
        await pilot.pause()

    assert calls == [(proposal_id, None, None)]
    assert (tmp_path / "sase" / "memory" / "first.md").exists()
    assert read_memory_proposals()[0].status == "approved"


async def test_memory_review_tui_target_edit_feeds_approval_target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _setup_review_state(tmp_path, monkeypatch)
    proposal_id = _create_proposal(
        tmp_path,
        proposal_id="mem-20260523-120000-11111111",
        title="First memory",
        body="First body\n",
        target="first.md",
    )
    calls: list[tuple[str, str | None, str | Path | None]] = []

    def approve_callback(
        proposal_ref: str,
        target: str | None,
        edited_file: str | Path | None,
    ) -> Any:
        calls.append((proposal_ref, target, edited_file))
        return approve_memory_proposal(
            proposal_ref,
            target=target,
            edited_file=edited_file,
            reviewer=ProposalReviewer("reviewer", "host"),
            cwd=tmp_path,
        )

    app = MemoryReviewTuiApp(approve_callback=approve_callback, cwd=tmp_path)
    async with app.run_test() as pilot:
        await pilot.press("t")
        await pilot.pause()
        input_widget = app.screen.query_one(
            "#memory-review-input", SingleLineVimTextArea
        )
        input_widget.text = "renamed.md"
        await pilot.press("enter")
        await pilot.pause()
        await pilot.press("a")
        await pilot.pause()

    assert calls == [(proposal_id, "renamed.md", None)]
    assert (tmp_path / "sase" / "memory" / "renamed.md").exists()
