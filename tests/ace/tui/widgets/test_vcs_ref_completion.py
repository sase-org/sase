"""Tests for the VCS ref-root completion menu in the prompt widget."""

from __future__ import annotations

from typing import Literal
from unittest.mock import patch

from textual.widgets import Static

from sase.ace.tui.agent_completion import AgentCompletionCandidate
from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar
from sase.ace.tui.widgets.prompt_text_area import PromptTextArea
from sase.ace.tui.widgets.vcs_ref_completion import (
    VCS_REF_COMPLETION_KIND,
    build_no_known_refs_placeholder,
    vcs_ref_completion_candidates,
)
from sase.ace.tui.widgets.vcs_repo_completion import VCS_REPO_COMPLETION_KIND
from sase.ace.tui.widgets.xprompt_arg_assist import (
    XPromptAssistEntry,
    XPromptInputHint,
)
from sase.workspace_provider import VcsNamespaceEntry, VcsRepoEntry
from sase.xprompt.vcs_project_completion import VcsProjectEntry
from sase.xprompt.vcs_repo_completion import VcsRepoFetchResult

from ._completion_helpers import CompletionTestApp

_WORKFLOW_NAMES_PATH = "sase.workspace_provider.get_workflow_names"
_REF_ENTRIES_PATH = "sase.ace.tui.widgets.vcs_ref_completion.build_vcs_ref_candidates"
_REF_DISPLAY_PATH = "sase.ace.tui.widgets.vcs_ref_completion.get_display_name"
_PEEK_REPO_PATH = (
    "sase.ace.tui.widgets._file_completion_open.peek_cached_repo_candidates"
)


def _entry(
    name: str,
    *,
    vcs: str = "gh",
    provider: str = "GitHub",
    description: str = "",
    aliases: tuple[str, ...] = (),
    kind: Literal["project", "patch"] = "project",
    project: str | None = None,
    status: str = "",
) -> VcsProjectEntry:
    return VcsProjectEntry(
        name=name,
        vcs_prefix=vcs,
        display_tag=f"#{vcs}:{name}",
        provider_display=provider,
        description=description,
        aliases=aliases,
        kind=kind,
        project=project or name,
        status=status,
    )


_REF_SOURCE = [
    _entry("sase", description="Structured agentic software engineering"),
    _entry(
        "ship-completion",
        kind="patch",
        project="sase",
        status="Ready",
    ),
    VcsNamespaceEntry("sase-org", description="2 active projects"),
]

_REPO_RESULT = VcsRepoFetchResult(
    status="ok",
    provider_display="GitHub",
    entries=(
        VcsRepoEntry(
            name="sase",
            ref="sase-org/sase",
            description="Structured agentic software engineering",
        ),
    ),
)


def _select(ta: PromptTextArea, name: str) -> None:
    index = next(
        i for i, c in enumerate(ta._file_completion_candidates) if c.name == name
    )
    ta._file_completion_index = index


def _xprompt_entry(name: str) -> XPromptAssistEntry:
    return XPromptAssistEntry(
        name=name,
        insertion=f"#{name}",
        reference_prefix="#",
        kind="xprompt",
        input_signature=None,
        inputs=(
            XPromptInputHint(
                name="agent",
                type="agent",
                required=True,
                default_display=None,
                position=0,
            ),
        ),
        content_preview=None,
    )


def _agent(name: str) -> AgentCompletionCandidate:
    return AgentCompletionCandidate(name=name, label=name, status="RUNNING")


def test_candidates_filter_projects_prs_and_namespaces() -> None:
    candidates, source_empty, has_namespaces = vcs_ref_completion_candidates(
        "gh",
        "sa",
        entries=_REF_SOURCE,
    )

    assert source_empty is False
    assert has_namespaces is True
    assert [candidate.name for candidate in candidates] == ["sase", "sase-org"]


def test_placeholder_is_non_selectable() -> None:
    placeholder = build_no_known_refs_placeholder()
    assert placeholder.metadata is None
    assert "no known projects" in placeholder.display


async def test_colon_auto_opens_ref_menu() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        bar = app.query_one(PromptInputBar)
        ta = app.query_one(PromptTextArea)
        with (
            patch(_WORKFLOW_NAMES_PATH, return_value={"gh"}),
            patch(_REF_ENTRIES_PATH, return_value=_REF_SOURCE),
            patch(_REF_DISPLAY_PATH, return_value="GitHub"),
        ):
            for key in "#gh:":
                await pilot.press(key)

        assert ta.text == "#gh:"
        assert ta._file_completion_active is True
        assert ta._completion_kind == VCS_REF_COMPLETION_KIND
        panel = bar.query_one("#prompt-completion", Static)
        assert panel.border_title == "GitHub · projects & PRs & orgs"
        rendered = panel.render().plain
        assert "[P] sase" in rendered
        assert "Structured agentic software engineering" in rendered
        assert "[PR] ship-completion" in rendered
        assert "Ready" in rendered
        assert "[ORG] sase-org/" in rendered
        assert "2 active projects" in rendered


async def test_paren_auto_pair_opens_ref_menu() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        with (
            patch(_WORKFLOW_NAMES_PATH, return_value={"gh"}),
            patch(_REF_ENTRIES_PATH, return_value=_REF_SOURCE),
        ):
            for key in "#gh(":
                await pilot.press(key)

        assert ta.text == "#gh()"
        assert ta.cursor_location == (0, len("#gh("))
        assert ta._file_completion_active is True
        assert ta._completion_kind == VCS_REF_COMPLETION_KIND


async def test_typing_filters_ref_menu() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        with (
            patch(_WORKFLOW_NAMES_PATH, return_value={"gh"}),
            patch(_REF_ENTRIES_PATH, return_value=_REF_SOURCE),
        ):
            for key in "#gh:":
                await pilot.press(key)
            assert [c.name for c in ta._file_completion_candidates] == [
                "sase",
                "ship-completion",
                "sase-org",
            ]
            await pilot.press("s")
            await pilot.press("a")

        assert ta.text == "#gh:sa"
        assert [c.name for c in ta._file_completion_candidates] == [
            "sase",
            "sase-org",
        ]


async def test_auto_open_empty_source_stays_silent() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        with (
            patch(_WORKFLOW_NAMES_PATH, return_value={"gh"}),
            patch(_REF_ENTRIES_PATH, return_value=[]),
        ):
            for key in "#gh:":
                await pilot.press(key)

        assert ta.text == "#gh:"
        assert ta._file_completion_active is False


async def test_ctrl_t_empty_source_shows_placeholder() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        bar = app.query_one(PromptInputBar)
        ta = app.query_one(PromptTextArea)
        ta.load_text("#gh:")
        ta.cursor_location = (0, len("#gh:"))
        with (
            patch(_WORKFLOW_NAMES_PATH, return_value={"gh"}),
            patch(_REF_ENTRIES_PATH, return_value=[]),
        ):
            await pilot.press("ctrl+t")

        assert ta._file_completion_active is True
        assert ta._completion_kind == VCS_REF_COMPLETION_KIND
        assert ta._file_completion_candidates[0].metadata is None
        panel = bar.query_one("#prompt-completion", Static)
        assert "no known projects, PRs, or organizations" in panel.render().plain


async def test_accept_project_applies_token_local_colon_transform() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("Fix #gh:sa now")
        ta.cursor_location = (0, len("Fix #gh:sa"))
        with (
            patch(_WORKFLOW_NAMES_PATH, return_value={"gh"}),
            patch(_REF_ENTRIES_PATH, return_value=_REF_SOURCE),
        ):
            assert ta._try_vcs_ref_completion() is True
            _select(ta, "sase")
            await pilot.press("ctrl+l")

        assert ta.text == "Fix #gh:sase now"
        assert ta.cursor_location == (0, len("Fix #gh:sase"))
        assert ta._file_completion_active is False


async def test_accept_project_applies_token_local_paren_transform() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("#gh(sa)")
        ta.cursor_location = (0, len("#gh(sa"))
        with (
            patch(_WORKFLOW_NAMES_PATH, return_value={"gh"}),
            patch(_REF_ENTRIES_PATH, return_value=_REF_SOURCE),
        ):
            assert ta._try_vcs_ref_completion() is True
            _select(ta, "sase")
            await pilot.press("ctrl+l")

        assert ta.text == "#gh(sase)"
        assert ta.cursor_location == (0, len("#gh(sase)"))
        assert ta._file_completion_active is False


async def test_accept_patch_applies_terminal_colon_transform() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("#gh:ship")
        ta.cursor_location = (0, len("#gh:ship"))
        with (
            patch(_WORKFLOW_NAMES_PATH, return_value={"gh"}),
            patch(_REF_ENTRIES_PATH, return_value=_REF_SOURCE),
        ):
            assert ta._try_vcs_ref_completion() is True
            _select(ta, "ship-completion")
            await pilot.press("ctrl+l")

        assert ta.text == "#gh:ship-completion "
        assert ta.cursor_location == (0, len("#gh:ship-completion "))
        assert ta._file_completion_active is False


async def test_accept_namespace_chains_to_repo_menu() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("#gh:")
        ta.cursor_location = (0, len("#gh:"))
        with (
            patch(_WORKFLOW_NAMES_PATH, return_value={"gh"}),
            patch(_REF_ENTRIES_PATH, return_value=_REF_SOURCE),
            patch(_PEEK_REPO_PATH, return_value=_REPO_RESULT),
        ):
            assert ta._try_vcs_ref_completion() is True
            _select(ta, "sase-org")
            await pilot.press("ctrl+l")

        assert ta.text == "#gh:sase-org/"
        assert ta.cursor_location == (0, len("#gh:sase-org/"))
        assert ta._file_completion_active is True
        assert ta._completion_kind == VCS_REPO_COMPLETION_KIND
        assert [candidate.name for candidate in ta._file_completion_candidates] == [
            "sase"
        ]


async def test_negative_ref_start_dismisses_ref_menu() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        with (
            patch(_WORKFLOW_NAMES_PATH, return_value={"gh"}),
            patch(_REF_ENTRIES_PATH, return_value=_REF_SOURCE),
        ):
            for key in "#gh:":
                await pilot.press(key)
            assert ta._file_completion_active is True
            await pilot.press("~")

        assert ta.text == "#gh:~"
        assert ta._file_completion_active is False


async def test_typed_slash_hands_off_from_ref_menu_to_repo_menu() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        with (
            patch(_WORKFLOW_NAMES_PATH, return_value={"gh"}),
            patch(_REF_ENTRIES_PATH, return_value=_REF_SOURCE),
            patch(_PEEK_REPO_PATH, return_value=_REPO_RESULT),
        ):
            for key in "#gh:sase-org":
                await pilot.press(key)
            assert ta._file_completion_active is True
            assert ta._completion_kind == VCS_REF_COMPLETION_KIND

            await pilot.press("/")

        assert ta.text == "#gh:sase-org/"
        assert ta._file_completion_active is True
        assert ta._completion_kind == VCS_REPO_COMPLETION_KIND
        assert [candidate.name for candidate in ta._file_completion_candidates] == [
            "sase"
        ]


async def test_owner_slash_routes_to_repo_menu_not_ref_menu() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        with (
            patch(_WORKFLOW_NAMES_PATH, return_value={"gh"}),
            patch(_REF_ENTRIES_PATH, return_value=_REF_SOURCE),
            patch(_PEEK_REPO_PATH, return_value=_REPO_RESULT),
        ):
            for key in "#gh:sase-org/":
                await pilot.press(key)

        assert ta._file_completion_active is True
        assert ta._completion_kind == VCS_REPO_COMPLETION_KIND
        assert [candidate.name for candidate in ta._file_completion_candidates] == [
            "sase"
        ]


async def test_non_vcs_colon_keeps_xprompt_argument_behavior() -> None:
    app = CompletionTestApp()
    app.visible_agent_completion_candidates = lambda: [  # type: ignore[attr-defined]
        _agent("coder")
    ]
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta._xprompt_arg_assist_entries_by_project[None] = [_xprompt_entry("foo")]
        with (
            patch(_WORKFLOW_NAMES_PATH, return_value={"gh"}),
            patch(_REF_ENTRIES_PATH, return_value=_REF_SOURCE),
        ):
            for key in "#foo:":
                await pilot.press(key)

        assert ta.text == "#foo:"
        assert ta._file_completion_active is True
        assert ta._completion_kind == "xprompt_arg_agent"
        assert [
            candidate.insertion for candidate in ta._file_completion_candidates
        ] == ["coder"]
