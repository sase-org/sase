"""Unit coverage for the bead add-note modal attachment UX."""

from __future__ import annotations

from pathlib import Path

from textual.app import App, ComposeResult

from sase.ace.tui.modals.bead_note_modal import (
    AUDIENCE_MODES,
    BeadNoteModal,
    BeadNoteResult,
    _attachment_trigger_at,
    _complete_attachment_prefix,
    _format_pasted_path_for_note,
    _longest_common_prefix,
)


def test_trigger_detects_plain_and_quoted_paths() -> None:
    assert _attachment_trigger_at("see @./shots/lo") == (4, "./shots/lo", False)
    assert _attachment_trigger_at('see @"my sh') == (4, "my sh", True)
    assert _attachment_trigger_at("@") == (0, "", False)


def test_trigger_ignores_escapes_reuse_and_citations() -> None:
    assert _attachment_trigger_at("literal @@./x") is None
    assert _attachment_trigger_at("reuse @attachment:login.png") is None
    assert _attachment_trigger_at("cite @research:plan.md") is None
    assert _attachment_trigger_at("mail me@host") is None
    assert _attachment_trigger_at("@large") == (0, "large", False)


def test_trigger_requires_boundary() -> None:
    assert _attachment_trigger_at("word@./x.png") is None
    assert _attachment_trigger_at("(@./x.png") == (1, "./x.png", False)


def test_completion_lists_files_and_dirs(tmp_path: Path) -> None:
    (tmp_path / "login.png").write_bytes(b"x")
    (tmp_path / "logs").mkdir()
    (tmp_path / "notes.md").write_text("hi")

    candidates = _complete_attachment_prefix("./lo", tmp_path)

    assert "login.png" in candidates
    assert "logs/" in candidates
    assert "notes.md" not in candidates


def test_completion_empty_query_lists_cwd(tmp_path: Path) -> None:
    (tmp_path / "a.log").write_text("a")

    assert "a.log" in _complete_attachment_prefix("", tmp_path)


def test_completion_missing_dir_is_empty(tmp_path: Path) -> None:
    assert _complete_attachment_prefix("./nope/", tmp_path) == []


def test_longest_common_prefix() -> None:
    assert _longest_common_prefix([]) == ""
    assert _longest_common_prefix(["login.png", "logout.png"]) == "log"
    assert _longest_common_prefix(["a"]) == "a"


def test_paste_single_existing_file_becomes_quoted_ref(tmp_path: Path) -> None:
    target = tmp_path / "crash.log"
    target.write_text("boom")

    assert _format_pasted_path_for_note(str(target), tmp_path) == f'@"{target}"'


def test_paste_ignores_prose_and_missing_files(tmp_path: Path) -> None:
    assert _format_pasted_path_for_note("just some words", tmp_path) is None
    assert _format_pasted_path_for_note(str(tmp_path / "gone.log"), tmp_path) is None
    assert _format_pasted_path_for_note("line one\nline two", tmp_path) is None


class _TestApp(App[None]):
    ENABLE_COMMAND_PALETTE = False

    def compose(self) -> ComposeResult:
        yield from ()


async def test_modal_shows_inline_error_and_keeps_text() -> None:
    dismissed: list[BeadNoteResult | None] = []
    async with _TestApp().run_test(size=(100, 40)) as pilot:
        modal = BeadNoteModal(
            "sase-1ck.8",
            initial_value="see @./missing.png",
            error="Error: 1 attachment problem\n  @./missing.png: file not found",
        )
        pilot.app.push_screen(modal, callback=dismissed.append)
        await pilot.pause()

        error = modal.query_one("#bead-note-error")
        assert error.display

        modal.action_save()
        await pilot.pause()

        assert len(dismissed) == 1
        result = dismissed[0]
        assert isinstance(result, BeadNoteResult)
        assert result.text == "see @./missing.png"
        assert result.audience_requested == "auto"


def test_audience_toggle_cycles_auto_private_public() -> None:
    modal = BeadNoteModal("sase-1d5.7")
    assert modal.audience_requested == "auto"
    assert modal.toggle_audience() == "private"
    assert modal.toggle_audience() == "public"
    assert modal.toggle_audience() == "auto"
    assert AUDIENCE_MODES == ("auto", "private", "public")


def test_audience_toggle_hidden_is_noop() -> None:
    modal = BeadNoteModal("sase-1d5.7", show_audience_toggle=False)
    assert modal.toggle_audience() == "auto"
    assert modal.audience_requested == "auto"


def test_invalid_audience_requested_defaults_to_auto() -> None:
    assert BeadNoteResult("hi", "everyone").audience_requested == "auto"
    assert BeadNoteModal(
        "sase-1d5.7", audience_requested="wide"
    ).audience_requested == ("auto")


async def test_modal_save_carries_toggled_audience() -> None:
    dismissed: list[BeadNoteResult | None] = []
    async with _TestApp().run_test(size=(100, 40)) as pilot:
        modal = BeadNoteModal("sase-1d5.7", initial_value="note text")
        pilot.app.push_screen(modal, callback=dismissed.append)
        await pilot.pause()

        modal.toggle_audience()
        modal.action_save()
        await pilot.pause()

        assert len(dismissed) == 1
        result = dismissed[0]
        assert isinstance(result, BeadNoteResult)
        assert result.text == "note text"
        assert result.audience_requested == "private"


async def test_modal_hides_audience_row_when_flag_off() -> None:
    async with _TestApp().run_test(size=(100, 40)) as pilot:
        modal = BeadNoteModal("sase-1d5.7", show_audience_toggle=False)
        pilot.app.push_screen(modal)
        await pilot.pause()

        audience = modal.query_one("#bead-note-audience")
        assert not audience.display
        assert "toggles audience" not in modal._hint_text()
        assert modal._audience_text() == ""


def test_toggle_note_audience_key_has_default() -> None:
    from sase.ace.tui.keymaps import load_builtin_app_defaults, load_keymap_registry

    assert load_builtin_app_defaults()["beads_toggle_note_audience"] == "ctrl+t"
    assert load_keymap_registry({}).app.beads_toggle_note_audience == "ctrl+t"
