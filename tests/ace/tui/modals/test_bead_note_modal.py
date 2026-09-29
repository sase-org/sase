"""Unit coverage for the bead add-note modal attachment UX."""

from __future__ import annotations

from pathlib import Path

from textual.app import App, ComposeResult

from sase.ace.tui.modals.bead_note_modal import (
    BeadNoteModal,
    attachment_trigger_at,
    complete_attachment_prefix,
    format_pasted_path_for_note,
    longest_common_prefix,
)


def test_trigger_detects_plain_and_quoted_paths() -> None:
    assert attachment_trigger_at("see @./shots/lo") == (4, "./shots/lo", False)
    assert attachment_trigger_at('see @"my sh') == (4, "my sh", True)
    assert attachment_trigger_at("@") == (0, "", False)


def test_trigger_ignores_escapes_reuse_and_citations() -> None:
    assert attachment_trigger_at("literal @@./x") is None
    assert attachment_trigger_at("reuse @attachment:login.png") is None
    assert attachment_trigger_at("cite @research:plan.md") is None
    assert attachment_trigger_at("mail me@host") is None
    assert attachment_trigger_at("@large") == (0, "large", False)


def test_trigger_requires_boundary() -> None:
    assert attachment_trigger_at("word@./x.png") is None
    assert attachment_trigger_at("(@./x.png") == (1, "./x.png", False)


def test_completion_lists_files_and_dirs(tmp_path: Path) -> None:
    (tmp_path / "login.png").write_bytes(b"x")
    (tmp_path / "logs").mkdir()
    (tmp_path / "notes.md").write_text("hi")

    candidates = complete_attachment_prefix("./lo", tmp_path)

    assert "login.png" in candidates
    assert "logs/" in candidates
    assert "notes.md" not in candidates


def test_completion_empty_query_lists_cwd(tmp_path: Path) -> None:
    (tmp_path / "a.log").write_text("a")

    assert "a.log" in complete_attachment_prefix("", tmp_path)


def test_completion_missing_dir_is_empty(tmp_path: Path) -> None:
    assert complete_attachment_prefix("./nope/", tmp_path) == []


def test_longest_common_prefix() -> None:
    assert longest_common_prefix([]) == ""
    assert longest_common_prefix(["login.png", "logout.png"]) == "log"
    assert longest_common_prefix(["a"]) == "a"


def test_paste_single_existing_file_becomes_quoted_ref(tmp_path: Path) -> None:
    target = tmp_path / "crash.log"
    target.write_text("boom")

    assert format_pasted_path_for_note(str(target), tmp_path) == f'@"{target}"'


def test_paste_ignores_prose_and_missing_files(tmp_path: Path) -> None:
    assert format_pasted_path_for_note("just some words", tmp_path) is None
    assert format_pasted_path_for_note(str(tmp_path / "gone.log"), tmp_path) is None
    assert format_pasted_path_for_note("line one\nline two", tmp_path) is None


class _TestApp(App[None]):
    ENABLE_COMMAND_PALETTE = False

    def compose(self) -> ComposeResult:
        yield from ()


async def test_modal_shows_inline_error_and_keeps_text() -> None:
    dismissed: list[str | None] = []
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

        assert dismissed == ["see @./missing.png"]
