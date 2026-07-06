"""Run, edit, select, and copy coverage for ``sase prompt``."""

from __future__ import annotations

import argparse
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sase.prompt.cli_copy import handle_prompt_copy
from sase.prompt.cli_run import (
    handle_prompt_edit,
    handle_prompt_run,
    handle_prompt_select,
)
from sase.prompt.cli_show import handle_prompt_show

from ._helpers import _entry, _prompt_id, _run_ns, _seed, _select_ns


def test_run_dispatches_exact_prompt_through_launch_query(history_file: Path) -> None:
    text = "refactor the parser module to be cleaner"
    _seed(_entry(text, "260603_000000"))

    with patch("sase.main.query_handler.launch_query") as mock_launch:
        handle_prompt_run(_run_ns(_prompt_id(text)))

    # Replay routes through the same dispatch path as `sase run "<prompt>"`.
    mock_launch.assert_called_once_with(text)


def test_run_prefix_replaces_vcs_tags_before_dispatch(history_file: Path) -> None:
    text = "#gh:sase fix the flaky launcher test"
    _seed(_entry(text, "260603_000000"))

    rewritten = "#gh:bob-cli fix the flaky launcher test"
    with (
        patch(
            "sase.xprompt.replace_vcs_workflow_tags", return_value=rewritten
        ) as mock_replace,
        patch("sase.main.query_handler.launch_query") as mock_launch,
    ):
        handle_prompt_run(_run_ns(_prompt_id(text), prefix="#gh:bob-cli"))

    # The replay path and the `sase run "#vcs:ref ."` compatibility path share
    # one replacement function, so they cannot drift.
    mock_replace.assert_called_once_with(text, "#gh:bob-cli")
    mock_launch.assert_called_once_with(rewritten)


def test_run_edit_launches_edited_content(history_file: Path) -> None:
    text = "original prompt body to edit"
    _seed(_entry(text, "260603_000000"))

    edited = "edited prompt body to launch"
    with (
        patch(
            "sase.main.query_handler._editor.edit_prompt_text", return_value=edited
        ) as mock_edit,
        patch("sase.main.query_handler.launch_query") as mock_launch,
    ):
        handle_prompt_run(_run_ns(_prompt_id(text), edit=True))

    mock_edit.assert_called_once_with(text)
    mock_launch.assert_called_once_with(edited)


def test_run_edit_empty_content_aborts(
    history_file: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    text = "prompt that the user will clear in the editor"
    _seed(_entry(text, "260603_000000"))

    with (
        patch("sase.main.query_handler._editor.edit_prompt_text", return_value=None),
        patch("sase.main.query_handler.launch_query") as mock_launch,
        pytest.raises(SystemExit) as exc_info,
    ):
        handle_prompt_run(_run_ns(_prompt_id(text), edit=True))

    assert exc_info.value.code == 1
    mock_launch.assert_not_called()
    assert "Aborted" in capsys.readouterr().err


def test_run_unknown_selector_exits_two(
    history_file: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _seed(_entry("some stored prompt here", "260603_000000"))

    with pytest.raises(SystemExit) as exc_info:
        handle_prompt_run(_run_ns("ph_ffffffffffff"))

    assert exc_info.value.code == 2
    assert "No prompt matches selector" in capsys.readouterr().err


def test_edit_is_edit_before_launch_wrapper(history_file: Path) -> None:
    text = "wrapper prompt that always opens the editor"
    _seed(_entry(text, "260603_000000"))

    edited = "edited wrapper prompt"
    with (
        patch(
            "sase.main.query_handler._editor.edit_prompt_text", return_value=edited
        ) as mock_edit,
        patch("sase.main.query_handler.launch_query") as mock_launch,
    ):
        handle_prompt_edit(argparse.Namespace(id=_prompt_id(text), prefix=None))

    mock_edit.assert_called_once_with(text)
    mock_launch.assert_called_once_with(edited)


def test_select_filters_candidates_and_launches(history_file: Path) -> None:
    launched = "launched prompt to pick"
    cancelled = "cancelled prompt to hide"
    _seed(
        _entry(launched, "260603_000000"),
        _entry(cancelled, "260605_000000", cancelled=True),
    )

    fzf_result = MagicMock(returncode=0, stdout=f"{_prompt_id(launched)}  x\n")
    with (
        patch("sase.prompt.cli_run.shutil.which", return_value="/usr/bin/fzf"),
        patch(
            "sase.prompt.cli_run.subprocess.run", return_value=fzf_result
        ) as mock_fzf,
        patch("sase.main.query_handler.launch_query") as mock_launch,
    ):
        handle_prompt_select(_select_ns())

    mock_launch.assert_called_once_with(launched)
    # Default candidates exclude cancelled prompts before reaching fzf.
    fzf_input = mock_fzf.call_args.kwargs["input"]
    assert _prompt_id(launched) in fzf_input
    assert _prompt_id(cancelled) not in fzf_input


def test_select_no_fzf_installed_exits_nonzero(
    history_file: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _seed(_entry("a launched prompt", "260603_000000"))

    with (
        patch("sase.prompt.cli_run.shutil.which", return_value=None),
        patch("sase.main.query_handler.launch_query") as mock_launch,
        pytest.raises(SystemExit) as exc_info,
    ):
        handle_prompt_select(_select_ns())

    assert exc_info.value.code == 1
    mock_launch.assert_not_called()
    err = capsys.readouterr().err
    assert "sase prompt list" in err
    assert "sase prompt run" in err


def test_select_cancelled_picker_exits_nonzero(
    history_file: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _seed(_entry("a launched prompt", "260603_000000"))

    fzf_result = MagicMock(returncode=130, stdout="")
    with (
        patch("sase.prompt.cli_run.shutil.which", return_value="/usr/bin/fzf"),
        patch("sase.prompt.cli_run.subprocess.run", return_value=fzf_result),
        patch("sase.main.query_handler.launch_query") as mock_launch,
        pytest.raises(SystemExit) as exc_info,
    ):
        handle_prompt_select(_select_ns())

    assert exc_info.value.code == 1
    mock_launch.assert_not_called()
    assert "No prompt selected" in capsys.readouterr().err


def test_select_no_candidates_exits_nonzero(
    history_file: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _seed(_entry("only a cancelled prompt", "260603_000000", cancelled=True))

    with (
        patch("sase.main.query_handler.launch_query") as mock_launch,
        pytest.raises(SystemExit) as exc_info,
    ):
        handle_prompt_select(_select_ns())

    assert exc_info.value.code == 1
    mock_launch.assert_not_called()
    assert "No matching prompts" in capsys.readouterr().err


def test_copy_copies_exact_text(
    history_file: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    text = "exact text to copy to the clipboard"
    _seed(_entry(text, "260603_000000"))

    with patch(
        "sase.prompt.cli_copy.copy_to_system_clipboard", return_value=True
    ) as mock_copy:
        handle_prompt_copy(argparse.Namespace(id=_prompt_id(text)))

    mock_copy.assert_called_once_with(text)
    assert _prompt_id(text) in capsys.readouterr().out


def test_show_markdown_humanizes_vcs_refs_but_raw_stays_exact(
    history_file: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("sase.project_aliases._vcs_workflow_names", lambda: {"gh"})
    monkeypatch.setattr(
        "sase.project_display_names._project_display_name_map_cached",
        lambda _projects_root=None: {"gh_acme__widgets": "widgets"},
    )
    text = "#gh:gh_acme__widgets fix the parser"
    _seed(_entry(text, "260603_000000"))

    handle_prompt_show(argparse.Namespace(id=_prompt_id(text), format="markdown"))
    markdown = capsys.readouterr().out
    handle_prompt_show(argparse.Namespace(id=_prompt_id(text), format="raw"))
    raw = capsys.readouterr().out

    assert "#gh:widgets" in markdown
    assert "gh_acme__widgets" not in markdown
    assert raw == text


def test_copy_humanizes_vcs_refs(
    history_file: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("sase.project_aliases._vcs_workflow_names", lambda: {"gh"})
    monkeypatch.setattr(
        "sase.project_display_names._project_display_name_map_cached",
        lambda _projects_root=None: {"gh_acme__widgets": "widgets"},
    )
    text = "#gh:gh_acme__widgets fix the parser"
    _seed(_entry(text, "260603_000000"))

    with patch(
        "sase.prompt.cli_copy.copy_to_system_clipboard", return_value=True
    ) as mock_copy:
        handle_prompt_copy(argparse.Namespace(id=_prompt_id(text)))

    mock_copy.assert_called_once_with("#gh:widgets fix the parser")


def test_copy_no_clipboard_exits_nonzero_with_suggestion(
    history_file: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    text = "text that cannot reach a clipboard"
    _seed(_entry(text, "260603_000000"))

    with (
        patch("sase.prompt.cli_copy.copy_to_system_clipboard", return_value=False),
        pytest.raises(SystemExit) as exc_info,
    ):
        handle_prompt_copy(argparse.Namespace(id=_prompt_id(text)))

    assert exc_info.value.code == 1
    err = capsys.readouterr().err
    assert "show" in err
    assert "-f raw" in err


def test_copy_unknown_selector_exits_two(
    history_file: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _seed(_entry("a stored prompt", "260603_000000"))

    with pytest.raises(SystemExit) as exc_info:
        handle_prompt_copy(argparse.Namespace(id="ph_ffffffffffff"))

    assert exc_info.value.code == 2
    assert "No prompt matches selector" in capsys.readouterr().err
