"""Pilot tests for automatic Jinja2 menu opening while typing."""

from __future__ import annotations

from sase.ace.tui.widgets.prompt_completion import PromptCompletionSettings
from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar
from sase.ace.tui.widgets.prompt_text_area import PromptTextArea
from sase.macro import jinja_inspect

from ._completion_helpers import CompletionTestApp


class NoAutoJinjaApp(CompletionTestApp):
    """Completion harness with the Jinja auto-menu switched off."""

    def get_prompt_completion_settings(self) -> PromptCompletionSettings:
        return PromptCompletionSettings(auto_jinja_menu=False)


def _candidate_names(ta: PromptTextArea) -> list[str]:
    return [candidate.name for candidate in ta._file_completion_candidates]


async def test_double_brace_auto_pair_opens_jinja_menu() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)

        await pilot.press("{")
        assert ta._file_completion_active is False

        await pilot.press("{")

        assert ta.text == "{{  }}"
        assert ta._file_completion_active is True
        assert ta._completion_kind == "jinja"
        assert len(ta._file_completion_candidates) > 0


async def test_statement_pair_opens_jinja_menu() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)

        await pilot.press("{")
        await pilot.press("%")

        assert ta.text == "{%  %}"
        assert ta._file_completion_active is True
        assert ta._completion_kind == "jinja"


async def test_comment_pair_never_auto_opens() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)

        await pilot.press("{")
        await pilot.press("#")

        assert ta.text == "{#  #}"
        assert ta._file_completion_active is False


async def test_setting_off_no_auto_open_but_ctrl_t_still_works() -> None:
    app = NoAutoJinjaApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)

        await pilot.press("{")
        await pilot.press("{")

        assert ta.text == "{{  }}"
        assert ta._file_completion_active is False

        await pilot.press("ctrl+t")

        assert ta._file_completion_active is True
        assert ta._completion_kind == "jinja"


async def test_typing_identifier_narrows_live_to_patch_name() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)

        await pilot.press("{", "{", "p", "a")

        assert ta.text == "{{ pa }}"
        assert ta._file_completion_active is True
        assert ta._completion_kind == "jinja"
        names = _candidate_names(ta)
        assert names[0] == "patch_name"


async def test_pipe_inside_tag_inserts_literally_and_opens_filters() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("{{ a")
        ta.cursor_location = (0, len("{{ a"))

        await pilot.press("|")

        # No alternation `` | `` normalization inside a Jinja tag.
        assert ta.text == "{{ a|"
        assert ta._file_completion_active is True
        assert ta._completion_kind == "jinja"
        assert "join" in _candidate_names(ta)


async def test_dot_after_namespace_opens_members() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("{{ wait")
        ta.cursor_location = (0, len("{{ wait"))

        await pilot.press(".")

        assert ta.text == "{{ wait."
        assert ta._file_completion_active is True
        assert ta._completion_kind == "jinja"
        assert "chats" in _candidate_names(ta)


async def test_alternation_separator_outside_tags_is_unchanged() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("%{foo}")
        ta.cursor_location = (0, len("%{foo"))

        await pilot.press("|")

        assert ta.text == "%{foo | }"
        assert ta._completion_kind != "jinja"


async def test_open_menu_suppresses_empty_tag_diagnostics_flash() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        bar = app.query_one(PromptInputBar)
        ta = app.query_one(PromptTextArea)

        await pilot.press("{", "{")

        # The menu opens synchronously, before the 90 ms diagnostics
        # debounce can fire on the momentarily empty ``{{  }}``.
        assert ta._file_completion_active is True
        assert ta._completion_kind == "jinja"
        assert bar._completion_panel_kind == "completion"

        diagnostics = jinja_inspect.diagnose("{{  }}")
        assert diagnostics.has_jinja is True
        assert diagnostics.ok is False

        bar.show_jinja_diagnostics(diagnostics)
        assert bar._completion_panel_kind == "completion"


async def test_none_slot_claims_cursor_without_menu() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("{% set ")
        ta.cursor_location = (0, len("{% set "))

        await pilot.press("x")

        # A new-name position is in-tag (claimed) but offers nothing, so no
        # lower-priority surface may pop a menu either.
        assert ta.text == "{% set x"
        assert ta._file_completion_active is False


async def test_setting_off_still_claims_in_tag_cursor() -> None:
    app = NoAutoJinjaApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("{{ x ")
        ta.cursor_location = (0, len("{{ x "))

        await pilot.press("%")
        await pilot.press("m")
        await pilot.press("o")

        # With `auto_jinja_menu` off no Jinja menu opens, but the in-tag
        # cursor still claims the auto path so the directive menu never
        # opens inside the tag.
        assert ta._file_completion_active is False
        assert ta._completion_kind != "directive"
