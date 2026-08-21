"""Tests for the VCS repository completion menu in the prompt widget."""

from __future__ import annotations

import threading
from unittest.mock import patch

from textual.widgets import Static

from sase.ace.testing import wait_for
from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar
from sase.ace.tui.widgets.prompt_text_area import PromptTextArea
from sase.ace.tui.widgets.vcs_repo_completion import (
    VCS_REPO_COMPLETION_KIND,
    VcsRepoCompletionPlaceholder,
    vcs_repo_completion_candidates,
)
from sase.workspace_provider import VcsRepoEntry
from sase.xprompt.vcs_repo_completion import VcsRepoFetchResult

from ._completion_helpers import CompletionTestApp

_WORKFLOW_NAMES_PATH = "sase.workspace_provider.get_workflow_names"
_PEEK_PATH = "sase.ace.tui.widgets._file_completion_open.peek_cached_repo_candidates"
_FETCH_PATH = "sase.ace.tui.widgets._file_completion_workers.fetch_repo_candidates"


def _entry(
    name: str,
    *,
    description: str = "",
    visibility: str = "",
    is_fork: bool = False,
    is_archived: bool = False,
    pushed_at: str | None = None,
) -> VcsRepoEntry:
    return VcsRepoEntry(
        name=name,
        ref=f"bbugyi200/{name}",
        description=description,
        visibility=visibility,
        is_fork=is_fork,
        is_archived=is_archived,
        pushed_at=pushed_at,
    )


_RESULT = VcsRepoFetchResult(
    status="ok",
    provider_display="GitHub",
    entries=(
        _entry(
            "sase",
            description="Structured agentic software engineering",
            pushed_at="2026-07-01T00:00:00Z",
        ),
        _entry(
            "sase-core",
            description="Shared Rust core backend",
            visibility="private",
            is_fork=True,
            is_archived=True,
            pushed_at="2026-06-01T00:00:00Z",
        ),
        _entry("dotfiles", description="Home config"),
    ),
)


def test_candidates_filter_and_rank_repos() -> None:
    candidates, used_placeholder = vcs_repo_completion_candidates(
        _RESULT,
        "sase",
        "bbugyi200",
    )

    assert used_placeholder is False
    assert [candidate.name for candidate in candidates] == ["sase", "sase-core"]
    assert all(isinstance(candidate.metadata, VcsRepoEntry) for candidate in candidates)


def test_candidates_return_error_placeholder() -> None:
    result = VcsRepoFetchResult(
        status="error",
        error_kind="auth",
        message="repo listing failed - run `gh auth login`",
        provider_display="GitHub",
    )

    candidates, used_placeholder = vcs_repo_completion_candidates(
        result,
        "",
        "bbugyi200",
    )

    assert used_placeholder is True
    assert len(candidates) == 1
    assert isinstance(candidates[0].metadata, VcsRepoCompletionPlaceholder)
    assert candidates[0].metadata.kind == "error"


async def test_slash_auto_opens_cached_repo_menu() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        bar = app.query_one(PromptInputBar)
        ta = app.query_one(PromptTextArea)
        with (
            patch(_WORKFLOW_NAMES_PATH, return_value={"gh"}),
            patch(_PEEK_PATH, return_value=_RESULT),
        ):
            for key in "#gh:bbugyi200/":
                await pilot.press(key)

        assert ta.text == "#gh:bbugyi200/"
        assert ta._file_completion_active is True
        assert ta._completion_kind == VCS_REPO_COMPLETION_KIND
        panel = bar.query_one("#prompt-completion", Static)
        assert panel.border_title == "GitHub · bbugyi200/"
        rendered = panel.render().plain
        assert "sase" in rendered
        assert "Structured agentic software engineering" in rendered
        assert "[private]" in rendered
        assert "[fork]" in rendered
        assert "[archived]" in rendered


async def test_typing_narrows_cached_repo_menu() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        with (
            patch(_WORKFLOW_NAMES_PATH, return_value={"gh"}),
            patch(_PEEK_PATH, return_value=_RESULT),
        ):
            for key in "#gh:bbugyi200/":
                await pilot.press(key)
            assert [candidate.name for candidate in ta._file_completion_candidates] == [
                "sase",
                "sase-core",
                "dotfiles",
            ]
            await pilot.press("c")

        assert ta.text == "#gh:bbugyi200/c"
        assert [candidate.name for candidate in ta._file_completion_candidates] == [
            "sase-core"
        ]


async def test_backspace_past_slash_dismisses_cached_repo_menu() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        with (
            patch(_WORKFLOW_NAMES_PATH, return_value={"gh"}),
            patch(_PEEK_PATH, return_value=_RESULT),
        ):
            for key in "#gh:bbugyi200/sa":
                await pilot.press(key)

            assert ta._file_completion_active is True
            await pilot.press("backspace")
            await pilot.press("backspace")
            assert ta._file_completion_active is True
            await pilot.press("backspace")

        assert ta.text == "#gh:bbugyi200"
        assert ta._file_completion_active is False


async def test_accept_repo_candidate_applies_canonical_colon_transform() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("Fix #gh:bbugyi200/sa now")
        ta.cursor_location = (0, len("Fix #gh:bbugyi200/sa"))
        with (
            patch(_WORKFLOW_NAMES_PATH, return_value={"gh"}),
            patch(_PEEK_PATH, return_value=_RESULT),
        ):
            assert ta._try_vcs_repo_completion() is True
            await pilot.press("ctrl+l")

        assert ta.text == "Fix #gh:bbugyi200/sase now"
        assert ta._file_completion_active is False


async def test_accept_repo_candidate_applies_canonical_paren_transform() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("#gh(bbugyi200/sa")
        ta.cursor_location = (0, len("#gh(bbugyi200/sa"))
        with (
            patch(_WORKFLOW_NAMES_PATH, return_value={"gh"}),
            patch(_PEEK_PATH, return_value=_RESULT),
        ):
            assert ta._try_vcs_repo_completion() is True
            await pilot.press("ctrl+l")

        assert ta.text == "#gh(bbugyi200/sase)"
        assert ta._file_completion_active is False


async def test_ctrl_t_opens_existing_repo_ref() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("Review #gh:bbugyi200/s")
        ta.cursor_location = (0, len("Review #gh:bbugyi200/s"))
        with (
            patch(_WORKFLOW_NAMES_PATH, return_value={"gh"}),
            patch(_PEEK_PATH, return_value=_RESULT),
        ):
            await pilot.press("ctrl+t")

        assert ta._file_completion_active is True
        assert ta._completion_kind == VCS_REPO_COMPLETION_KIND
        assert [candidate.name for candidate in ta._file_completion_candidates] == [
            "sase",
            "sase-core",
            "dotfiles",
        ]


async def test_cache_miss_shows_loading_then_worker_result() -> None:
    release = threading.Event()
    started = threading.Event()

    def fetch(_workflow: str, _namespace: str) -> VcsRepoFetchResult:
        started.set()
        release.wait()
        return _RESULT

    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        with (
            patch(_WORKFLOW_NAMES_PATH, return_value={"gh"}),
            patch(_PEEK_PATH, return_value=None),
            patch(_FETCH_PATH, side_effect=fetch),
        ):
            try:
                for key in "#gh:bbugyi200/":
                    await pilot.press(key)
                await wait_for(pilot, started.is_set)
                await wait_for(
                    pilot,
                    lambda: (
                        ta._file_completion_active
                        and ta._file_completion_candidates
                        and ta._file_completion_candidates[0].display.startswith(
                            "fetching "
                        )
                    ),
                )
                release.set()
                await wait_for(
                    pilot, lambda: ta._file_completion_candidates[0].name == "sase"
                )
            finally:
                release.set()

        assert [candidate.name for candidate in ta._file_completion_candidates][:2] == [
            "sase",
            "sase-core",
        ]


async def test_worker_result_dropped_when_menu_closed_before_fetch_finishes() -> None:
    release = threading.Event()
    started = threading.Event()

    def fetch(_workflow: str, _namespace: str) -> VcsRepoFetchResult:
        started.set()
        release.wait()
        return _RESULT

    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        with (
            patch(_WORKFLOW_NAMES_PATH, return_value={"gh"}),
            patch(_PEEK_PATH, return_value=None),
            patch(_FETCH_PATH, side_effect=fetch),
        ):
            try:
                for key in "#gh:bbugyi200/":
                    await pilot.press(key)
                await wait_for(pilot, started.is_set)
                await wait_for(
                    pilot,
                    lambda: (
                        ta._file_completion_active
                        and ta._file_completion_candidates
                        and ta._file_completion_candidates[0].display.startswith(
                            "fetching "
                        )
                    ),
                )
                await pilot.press("space")
                await wait_for(pilot, lambda: not ta._file_completion_active)
                release.set()
                await wait_for(
                    pilot,
                    lambda: all(not worker.is_running for worker in app.workers),
                )
            finally:
                release.set()

        assert ta.text == "#gh:bbugyi200/ "
        assert ta._file_completion_active is False
