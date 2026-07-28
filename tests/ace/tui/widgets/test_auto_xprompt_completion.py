"""Tests for automatic xprompt completion menu opening."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from textual.widgets import Static

from sase.ace.tui.widgets.prompt_completion import PromptCompletionSettings
from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar
from sase.ace.tui.widgets.prompt_text_area import PromptTextArea
from sase.ace.tui.widgets.vcs_project_completion import VCS_PROJECT_COMPLETION_KIND
from sase.ace.tui.widgets.xprompt_arg_assist import XPromptAssistEntry
from sase.xprompt.vcs_project_completion import VcsProjectEntry

from ._completion_helpers import (
    CatalogCompletionTestApp,
    CompletionTestApp,
    registered_project_xprompts,
)

_PROJECT_ENTRIES_PATH = (
    "sase.ace.tui.widgets.vcs_project_completion.build_vcs_project_completion_entries"
)
_XPROMPT_COLD_BUILD_PATH = (
    "sase.ace.tui.widgets.prompt_text_area.build_xprompt_assist_entries"
)


def _entry(
    name: str,
    *,
    prefix: str = "#",
    kind: str = "xprompt",
    is_skill: bool = False,
) -> XPromptAssistEntry:
    return XPromptAssistEntry(
        name=name,
        insertion=f"{prefix}{name}",
        reference_prefix=prefix,
        kind=kind,
        input_signature=None,
        inputs=(),
        content_preview=None,
        is_skill=is_skill,
    )


def _project(name: str) -> VcsProjectEntry:
    return VcsProjectEntry(
        name=name,
        vcs_prefix="gh",
        display_tag=f"#gh:{name}",
        provider_display="GitHub",
    )


def _seed_entries(
    ta: PromptTextArea,
    entries: list[XPromptAssistEntry],
    project: str | None = None,
) -> None:
    ta._xprompt_arg_assist_entries_by_project[project] = entries


async def test_hash_name_auto_opens_xprompt_menu_without_extending() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        bar = app.query_one(PromptInputBar)
        ta = app.query_one(PromptTextArea)
        _seed_entries(ta, [_entry("front"), _entry("frog"), _entry("send")])

        await pilot.press("#")
        assert ta.text == "#"
        assert ta._file_completion_active is False

        await pilot.press("f")

        assert ta.text == "#f"
        assert ta._file_completion_active is True
        assert ta._completion_kind == "xprompt"
        assert [c.insertion for c in ta._file_completion_candidates] == [
            "#frog",
            "#front",
        ]
        panel = bar.query_one("#prompt-completion", Static)
        assert panel.border_title == "xprompts"
        assert "#frog" in panel.render().plain


async def test_single_match_auto_opens_without_accepting() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        _seed_entries(ta, [_entry("fix")])

        await pilot.press("#")
        await pilot.press("f")

        assert ta.text == "#f"
        assert ta._file_completion_active is True
        assert [c.insertion for c in ta._file_completion_candidates] == ["#fix"]


async def test_xprompt_before_period_auto_opens_but_after_period_stays_quiet() -> None:
    app = CompletionTestApp()
    async with app.run_test():
        ta = app.query_one(PromptTextArea)
        _seed_entries(ta, [_entry("screenshot")])

        ta.load_text("(see #s.")
        ta.cursor_location = (0, len("(see #s"))
        assert ta._try_auto_xprompt_completion() is True
        assert ta._completion_kind == "xprompt"
        assert [c.insertion for c in ta._file_completion_candidates] == ["#screenshot"]

        ta._clear_file_completion()
        ta.cursor_location = (0, len("(see #s."))
        assert ta._try_auto_xprompt_completion() is False
        assert ta._file_completion_active is False


async def test_standalone_marker_auto_opens_standalone_xprompts() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        _seed_entries(
            ta,
            [
                _entry("send"),
                _entry("split", prefix="#!", kind="standalone_workflow"),
                _entry("sync", prefix="#!", kind="standalone_workflow"),
            ],
        )

        await pilot.press("#")
        await pilot.press("!")

        assert ta.text == "#!"
        assert ta._file_completion_active is True
        assert [c.insertion for c in ta._file_completion_candidates] == [
            "#!split",
            "#!sync",
        ]


async def test_typing_narrows_deleting_widens_and_space_dismisses() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        _seed_entries(ta, [_entry("fix"), _entry("foo"), _entry("send")])

        await pilot.press("#")
        await pilot.press("f")
        assert [c.name for c in ta._file_completion_candidates] == ["fix", "foo"]

        await pilot.press("o")
        assert ta.text == "#fo"
        assert [c.name for c in ta._file_completion_candidates] == ["foo"]

        await pilot.press("backspace")
        assert ta.text == "#f"
        assert [c.name for c in ta._file_completion_candidates] == ["fix", "foo"]

        await pilot.press("space")
        assert ta.text == "#f "
        assert ta._file_completion_active is False


async def test_bare_hash_does_not_auto_open() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        _seed_entries(ta, [_entry("fix")])

        await pilot.press("#")

        assert ta.text == "#"
        assert ta._file_completion_active is False


async def test_no_matching_xprompt_does_not_show_placeholder() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        _seed_entries(ta, [_entry("fix")])

        await pilot.press("#")
        await pilot.press("z")

        assert ta.text == "#z"
        assert ta._file_completion_active is False
        assert ta._file_completion_candidates == []


async def test_hash_plus_does_not_route_to_project_completion() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        _seed_entries(ta, [_entry("plus")])

        with patch(_PROJECT_ENTRIES_PATH, return_value=[_project("sase")]):
            await pilot.press("#")
            await pilot.press("+")

        assert ta.text == "#+"
        assert ta._completion_kind != VCS_PROJECT_COMPLETION_KIND
        assert ta._file_completion_active is False


async def test_bof_plus_routes_to_project_completion() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        _seed_entries(ta, [_entry("plus")])

        with patch(_PROJECT_ENTRIES_PATH, return_value=[_project("sase")]):
            await pilot.press("+")

        assert ta.text == "+"
        assert ta._file_completion_active is True
        assert ta._completion_kind == VCS_PROJECT_COMPLETION_KIND
        assert [c.insertion for c in ta._file_completion_candidates] == ["#gh:sase"]


async def test_embedded_hash_token_does_not_auto_open() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        _seed_entries(ta, [_entry("bar")])
        ta.load_text("foo")
        ta.cursor_location = (0, 3)

        await pilot.press("#")
        await pilot.press("b")

        assert ta.text == "foo#b"
        assert ta._file_completion_active is False


async def test_slash_skill_token_auto_opens_skill_panel_when_warm() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        bar = app.query_one(PromptInputBar)
        ta = app.query_one(PromptTextArea)
        _seed_entries(
            ta,
            [
                _entry("sase_plan", is_skill=True),
                _entry("sase_review", is_skill=True),
                _entry("send"),  # non-skill xprompt is filtered out of /skills
            ],
        )

        await pilot.press("/")
        assert ta.text == "/"
        assert ta._file_completion_active is False

        await pilot.press("s")

        assert ta.text == "/s"
        assert ta._file_completion_active is True
        assert ta._completion_kind == "xprompt"
        assert [c.insertion for c in ta._file_completion_candidates] == [
            "/sase_plan",
            "/sase_review",
        ]
        panel = bar.query_one("#prompt-completion", Static)
        assert panel.border_title == "xprompts"
        assert "skill" in panel.render().plain


async def test_slash_skill_cold_catalog_defers_without_sync_build() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)

        with (
            patch.object(type(ta), "_warm_current_xprompt_assist_entries") as warm,
            patch(
                _XPROMPT_COLD_BUILD_PATH,
                side_effect=AssertionError("cold catalog build"),
            ),
        ):
            await pilot.press("/")
            await pilot.press("s")

            assert ta.text == "/s"
            assert ta._file_completion_active is False
            warm.assert_called_once()

            _seed_entries(ta, [_entry("sase_plan", is_skill=True)])
            await pilot.press("a")

        assert ta.text == "/sa"
        assert ta._file_completion_active is True
        assert ta._completion_kind == "xprompt"
        assert [c.insertion for c in ta._file_completion_candidates] == ["/sase_plan"]


async def test_auto_xprompt_menu_toggle_disables_slash_skill_auto_open() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        _seed_entries(
            ta,
            [
                _entry("sase_plan", is_skill=True),
                _entry("split", is_skill=True),
            ],
        )

        with patch.object(
            type(ta),
            "_prompt_completion_settings",
            return_value=PromptCompletionSettings(auto_xprompt_menu=False),
        ):
            await pilot.press("/")
            await pilot.press("s")

        assert ta.text == "/s"
        assert ta._file_completion_active is False

        await pilot.press("ctrl+t")

        assert ta._file_completion_active is True
        assert ta._completion_kind == "xprompt"
        assert [c.insertion for c in ta._file_completion_candidates] == [
            "/sase_plan",
            "/split",
        ]


async def test_cold_catalog_defers_without_sync_build_then_opens_when_warm() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)

        with (
            patch.object(type(ta), "_warm_current_xprompt_assist_entries") as warm,
            patch(
                _XPROMPT_COLD_BUILD_PATH,
                side_effect=AssertionError("cold catalog build"),
            ),
        ):
            await pilot.press("#")
            await pilot.press("f")

            assert ta.text == "#f"
            assert ta._file_completion_active is False
            warm.assert_called_once()

            _seed_entries(ta, [_entry("foo")])
            await pilot.press("o")

        assert ta.text == "#fo"
        assert ta._file_completion_active is True
        assert [c.insertion for c in ta._file_completion_candidates] == ["#foo"]


async def test_auto_xprompt_menu_toggle_disables_auto_open_only() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        _seed_entries(ta, [_entry("fix"), _entry("foo")])

        with patch.object(
            type(ta),
            "_prompt_completion_settings",
            return_value=PromptCompletionSettings(auto_xprompt_menu=False),
        ):
            await pilot.press("#")
            await pilot.press("f")

        assert ta.text == "#f"
        assert ta._file_completion_active is False

        await pilot.press("ctrl+t")

        assert ta._file_completion_active is True
        assert ta._completion_kind == "xprompt"
        assert [c.insertion for c in ta._file_completion_candidates] == [
            "#fix",
            "#foo",
        ]


async def test_vcs_tag_project_namespace_opens_project_xprompt_menu(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reported regression: ``#git:proj #proj/`` must offer project xprompts.

    The VCS tag names the project the user-facing way while the catalog knows
    it by its ProjectSpec directory key, so the menu stayed empty until both
    spellings were normalized to the canonical namespace.
    """
    app = CatalogCompletionTestApp()
    with registered_project_xprompts(
        tmp_path,
        monkeypatch,
        project_key="gh_org__proj",
        project_name="proj",
        xprompts={"reads": "Reads body", "sync": "Sync body"},
    ):
        async with app.run_test() as pilot:
            ta = app.query_one(PromptTextArea)
            ta.load_text("#git:proj #proj")
            ta.cursor_location = (0, len("#git:proj #proj"))

            await pilot.press("/")

            menu_text = ta.text
            menu_candidates = [c.insertion for c in ta._file_completion_candidates]
            menu_active = ta._file_completion_active
            menu_kind = ta._completion_kind

            # The directory-key spelling is not a real reference, so it must
            # not be offered either.
            ta.load_text("#git:proj #gh_org__proj")
            ta.cursor_location = (0, len("#git:proj #gh_org__proj"))

            await pilot.press("/")

            key_candidates = [c.insertion for c in ta._file_completion_candidates]

    assert menu_text == "#git:proj #proj/"
    assert menu_active is True
    assert menu_kind == "xprompt"
    assert menu_candidates == ["#proj/reads", "#proj/sync"]
    assert key_candidates == []
    assert app.requested_projects == ["proj"] * len(app.requested_projects)
    assert app.requested_projects


async def test_prompt_context_project_key_opens_same_project_xprompt_menu(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The prompt-context fallback carries a directory key and must normalize."""
    app = CatalogCompletionTestApp()
    with registered_project_xprompts(
        tmp_path,
        monkeypatch,
        project_key="gh_org__proj",
        project_name="proj",
        xprompts={"reads": "Reads body", "sync": "Sync body"},
    ):
        async with app.run_test() as pilot:
            ta = app.query_one(PromptTextArea)
            app._prompt_context = SimpleNamespace(
                project_name="gh_org__proj",
                is_home_mode=False,
            )
            ta.load_text("#proj")
            ta.cursor_location = (0, len("#proj"))

            await pilot.press("/")

    assert ta._file_completion_active is True
    assert [c.insertion for c in ta._file_completion_candidates] == [
        "#proj/reads",
        "#proj/sync",
    ]
    assert app.requested_projects == ["proj"] * len(app.requested_projects)
    assert app.requested_projects
    assert all(
        "gh_org__proj" not in candidate.insertion
        for candidate in ta._file_completion_candidates
    )
