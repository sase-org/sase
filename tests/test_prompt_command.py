"""Tests for the ``sase prompt`` command group (Phases 1-2)."""

from __future__ import annotations

import argparse
import json
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sase.history.prompt import (
    PromptEntry,
    _load_prompt_history,
    _save_prompt_history,
    compute_prompt_id,
)
from sase.main.parser import create_parser
from sase.prompt.cli_copy import handle_prompt_copy
from sase.prompt.cli_export import handle_prompt_export, handle_prompt_save
from sase.prompt.cli_list import handle_prompt_list
from sase.prompt.cli_maintenance import (
    handle_prompt_delete,
    handle_prompt_doctor,
    handle_prompt_prune,
)
from sase.prompt.cli_run import (
    handle_prompt_edit,
    handle_prompt_run,
    handle_prompt_select,
)
from sase.prompt.cli_show import handle_prompt_show
from sase.prompt.cli_stats import handle_prompt_stats


@pytest.fixture
def history_file(tmp_path: Path) -> Iterator[Path]:
    """Point the prompt-history store at an isolated temp file."""
    test_file = tmp_path / "prompt_history.json"
    with patch("sase.history.prompt._PROMPT_HISTORY_FILE", test_file):
        yield test_file


def _seed(*entries: PromptEntry) -> None:
    _save_prompt_history(list(entries))


def _entry(
    text: str,
    last_used: str,
    *,
    cancelled: bool = False,
) -> PromptEntry:
    return PromptEntry(
        text=text,
        timestamp=last_used,
        last_used=last_used,
        cancelled=cancelled,
    )


def _prompt_subparsers() -> dict[str, argparse.ArgumentParser]:
    parser = create_parser()
    top = next(
        action
        for action in parser._actions
        if isinstance(action, argparse._SubParsersAction)
    )
    prompt_parser = top.choices["prompt"]
    prompt_sub = next(
        action
        for action in prompt_parser._actions
        if isinstance(action, argparse._SubParsersAction)
    )
    return dict(prompt_sub.choices)


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------


def test_list_json_has_stable_shape_and_excludes_cancelled(
    history_file: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _seed(
        _entry("launched prompt one", "260603_000000"),
        _entry("cancelled prompt two", "260605_000000", cancelled=True),
    )

    handle_prompt_list(
        argparse.Namespace(all=False, cancelled=False, query=None, limit=20, json=True)
    )

    payload = json.loads(capsys.readouterr().out)
    assert isinstance(payload, list)
    assert len(payload) == 1
    assert list(payload[0].keys()) == [
        "id",
        "timestamp",
        "last_used",
        "cancelled",
        "text_preview",
        "text_chars",
        "text_sha256",
    ]
    assert payload[0]["id"] == compute_prompt_id("launched prompt one")
    assert payload[0]["cancelled"] is False


def test_list_never_prints_full_long_prompt(
    history_file: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    long_text = "please " + "x" * 5000
    _seed(_entry(long_text, "260603_000000"))

    handle_prompt_list(
        argparse.Namespace(all=False, cancelled=False, query=None, limit=20, json=False)
    )

    out = capsys.readouterr().out
    assert "x" * 5000 not in out


# ---------------------------------------------------------------------------
# show
# ---------------------------------------------------------------------------


def test_show_raw_is_byte_exact(
    history_file: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    text = "refactor the parser module to be cleaner"
    _seed(_entry(text, "260603_000000"))

    handle_prompt_show(argparse.Namespace(id=compute_prompt_id(text), format="raw"))

    # Exact text, no added or stripped trailing newline.
    assert capsys.readouterr().out == text


def test_show_raw_preserves_existing_trailing_newline(
    history_file: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    text = "prompt with trailing newline\n"
    _seed(_entry(text, "260603_000000"))

    handle_prompt_show(argparse.Namespace(id=compute_prompt_id(text), format="raw"))

    assert capsys.readouterr().out == text


def test_show_markdown_has_metadata_header_and_body(
    history_file: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    text = "do the important thing"
    _seed(_entry(text, "260603_000000"))

    handle_prompt_show(
        argparse.Namespace(id=compute_prompt_id(text), format="markdown")
    )

    out = capsys.readouterr().out
    assert f"# Prompt {compute_prompt_id(text)}" in out
    assert "- cancelled: false" in out
    assert text in out


def test_show_json_includes_full_text(
    history_file: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    text = "do the important thing"
    _seed(_entry(text, "260603_000000"))

    handle_prompt_show(argparse.Namespace(id=compute_prompt_id(text), format="json"))

    payload = json.loads(capsys.readouterr().out)
    assert payload["text"] == text
    assert payload["id"] == compute_prompt_id(text)


def test_show_unknown_selector_exits_nonzero(
    history_file: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _seed(_entry("a stored prompt here", "260603_000000"))

    with pytest.raises(SystemExit) as exc_info:
        handle_prompt_show(argparse.Namespace(id="ph_ffffffffffff", format="raw"))

    assert exc_info.value.code == 2
    assert "No prompt matches selector" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# stats
# ---------------------------------------------------------------------------


def test_stats_json_has_stable_shape(
    history_file: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _seed(
        _entry("aaaa bbbb", "260601_000000"),
        _entry("cccc dddd eeee", "260603_000000"),
    )

    handle_prompt_stats(argparse.Namespace(json=True))

    payload = json.loads(capsys.readouterr().out)
    assert set(payload.keys()) == {
        "path",
        "exists",
        "size_bytes",
        "total",
        "launched",
        "cancelled",
        "oldest_last_used",
        "newest_last_used",
        "length_percentiles",
        "largest",
        "top_chips",
    }
    assert payload["total"] == 2
    assert set(payload["length_percentiles"]) == {"p50", "p90", "p99", "max"}


# ---------------------------------------------------------------------------
# parser / CLI contract
# ---------------------------------------------------------------------------


def test_prompt_subcommands_parse_with_short_flags() -> None:
    parser = create_parser()

    list_args = parser.parse_args(
        ["prompt", "list", "-a", "-c", "-j", "-l", "5", "-q", "auth"]
    )
    assert list_args.command == "prompt"
    assert list_args.prompt_subcommand == "list"
    assert list_args.all is True
    assert list_args.cancelled is True
    assert list_args.json is True
    assert list_args.limit == 5
    assert list_args.query == "auth"

    show_args = parser.parse_args(["prompt", "show", "ph_abc123", "-f", "markdown"])
    assert show_args.prompt_subcommand == "show"
    assert show_args.id == "ph_abc123"
    assert show_args.format == "markdown"

    stats_args = parser.parse_args(["prompt", "stats", "-j"])
    assert stats_args.prompt_subcommand == "stats"
    assert stats_args.json is True


def test_prompt_replay_subcommands_parse_with_short_flags() -> None:
    parser = create_parser()

    copy_args = parser.parse_args(["prompt", "copy", "ph_abc123"])
    assert copy_args.prompt_subcommand == "copy"
    assert copy_args.id == "ph_abc123"

    run_args = parser.parse_args(
        ["prompt", "run", "ph_abc123", "-d", "-e", "-P", "#gh:bob-cli"]
    )
    assert run_args.prompt_subcommand == "run"
    assert run_args.id == "ph_abc123"
    assert run_args.daemon is True
    assert run_args.edit is True
    assert run_args.prefix == "#gh:bob-cli"

    edit_args = parser.parse_args(["prompt", "edit", "ph_abc123", "-d"])
    assert edit_args.prompt_subcommand == "edit"
    assert edit_args.id == "ph_abc123"
    assert edit_args.daemon is True

    select_args = parser.parse_args(
        ["prompt", "select", "-a", "-c", "-d", "-e", "-P", "#gh:bob-cli", "-q", "auth"]
    )
    assert select_args.prompt_subcommand == "select"
    assert select_args.all is True
    assert select_args.cancelled is True
    assert select_args.daemon is True
    assert select_args.edit is True
    assert select_args.prefix == "#gh:bob-cli"
    assert select_args.query == "auth"


def test_prompt_maintenance_subcommands_parse_with_short_flags() -> None:
    parser = create_parser()

    delete_args = parser.parse_args(["prompt", "delete", "ph_abc123", "-y"])
    assert delete_args.prompt_subcommand == "delete"
    assert delete_args.id == "ph_abc123"
    assert delete_args.yes is True

    doctor_args = parser.parse_args(["prompt", "doctor", "-j"])
    assert doctor_args.prompt_subcommand == "doctor"
    assert doctor_args.json is True

    prune_args = parser.parse_args(
        ["prompt", "prune", "-b", "2026-01-01", "-c", "-d", "-k", "50", "-y"]
    )
    assert prune_args.prompt_subcommand == "prune"
    assert prune_args.before == "2026-01-01"
    assert prune_args.cancelled is True
    assert prune_args.dry_run is True
    assert prune_args.keep == 50
    assert prune_args.yes is True


def test_prompt_export_save_subcommands_parse_with_short_flags() -> None:
    parser = create_parser()

    export_args = parser.parse_args(
        ["prompt", "export", "ph_abc123", "-F", "-m", "-o", "/tmp/p.md"]
    )
    assert export_args.prompt_subcommand == "export"
    assert export_args.id == "ph_abc123"
    assert export_args.force is True
    assert export_args.metadata is True
    assert export_args.out == "/tmp/p.md"
    assert export_args.sdd is False

    save_args = parser.parse_args(
        [
            "prompt",
            "save",
            "ph_abc123",
            "-D",
            "desc",
            "-F",
            "-g",
            "-n",
            "fix-auth",
            "-t",
            "review",
            "-t",
            "auth",
        ]
    )
    assert save_args.prompt_subcommand == "save"
    assert save_args.id == "ph_abc123"
    assert save_args.description == "desc"
    assert save_args.force is True
    assert save_args.global_ is True
    assert save_args.name == "fix-auth"
    assert save_args.tag == ["review", "auth"]

    project_args = parser.parse_args(["prompt", "save", "ph_abc123", "-p", "bob"])
    assert project_args.project == "bob"


def test_prompt_subcommands_are_sorted() -> None:
    assert list(_prompt_subparsers()) == sorted(_prompt_subparsers())


def test_prompt_public_long_options_have_short_aliases() -> None:
    for name, subparser in _prompt_subparsers().items():
        for action in subparser._actions:
            public_long_options = [
                option
                for option in action.option_strings
                if option.startswith("--") and option != "--help"
            ]
            if not public_long_options:
                continue
            short_options = [
                option
                for option in action.option_strings
                if option.startswith("-") and not option.startswith("--")
            ]
            assert short_options, f"prompt {name}: {'/'.join(public_long_options)}"


# ---------------------------------------------------------------------------
# run / edit (replay)
# ---------------------------------------------------------------------------


def _run_ns(
    prompt_id: str,
    *,
    prefix: str | None = None,
    edit: bool = False,
    daemon: bool = False,
) -> argparse.Namespace:
    return argparse.Namespace(id=prompt_id, prefix=prefix, edit=edit, daemon=daemon)


def test_run_dispatches_exact_prompt_through_run_query(history_file: Path) -> None:
    text = "refactor the parser module to be cleaner"
    _seed(_entry(text, "260603_000000"))

    with patch("sase.main.query_handler.special_cases.run_query") as mock_run:
        handle_prompt_run(_run_ns(compute_prompt_id(text)))

    # Replay routes through the same dispatch path as `sase run "<prompt>"`.
    mock_run.assert_called_once_with(text)


def test_run_daemon_routes_through_daemon(history_file: Path) -> None:
    text = "build the daemon pipeline end to end"
    _seed(_entry(text, "260603_000000"))

    with patch("sase.main.query_handler.special_cases.run_query_daemon") as mock_daemon:
        handle_prompt_run(_run_ns(compute_prompt_id(text), daemon=True))

    mock_daemon.assert_called_once_with(text)


def test_run_prefix_replaces_vcs_tags_before_dispatch(history_file: Path) -> None:
    text = "#gh:sase fix the flaky launcher test"
    _seed(_entry(text, "260603_000000"))

    rewritten = "#gh:bob-cli fix the flaky launcher test"
    with (
        patch(
            "sase.xprompt.replace_vcs_workflow_tags", return_value=rewritten
        ) as mock_replace,
        patch("sase.main.query_handler.special_cases.run_query") as mock_run,
    ):
        handle_prompt_run(_run_ns(compute_prompt_id(text), prefix="#gh:bob-cli"))

    # The replay path and the `sase run "#vcs:ref ."` compatibility path share
    # one replacement function, so they cannot drift.
    mock_replace.assert_called_once_with(text, "#gh:bob-cli")
    mock_run.assert_called_once_with(rewritten)


def test_run_edit_launches_edited_content(history_file: Path) -> None:
    text = "original prompt body to edit"
    _seed(_entry(text, "260603_000000"))

    edited = "edited prompt body to launch"
    with (
        patch(
            "sase.main.query_handler._editor.edit_prompt_text", return_value=edited
        ) as mock_edit,
        patch("sase.main.query_handler.special_cases.run_query") as mock_run,
    ):
        handle_prompt_run(_run_ns(compute_prompt_id(text), edit=True))

    mock_edit.assert_called_once_with(text)
    mock_run.assert_called_once_with(edited)


def test_run_edit_empty_content_aborts(
    history_file: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    text = "prompt that the user will clear in the editor"
    _seed(_entry(text, "260603_000000"))

    with (
        patch("sase.main.query_handler._editor.edit_prompt_text", return_value=None),
        patch("sase.main.query_handler.special_cases.run_query") as mock_run,
        pytest.raises(SystemExit) as exc_info,
    ):
        handle_prompt_run(_run_ns(compute_prompt_id(text), edit=True))

    assert exc_info.value.code == 1
    mock_run.assert_not_called()
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
        patch("sase.main.query_handler.special_cases.run_query") as mock_run,
    ):
        handle_prompt_edit(
            argparse.Namespace(id=compute_prompt_id(text), prefix=None, daemon=False)
        )

    mock_edit.assert_called_once_with(text)
    mock_run.assert_called_once_with(edited)


# ---------------------------------------------------------------------------
# select (fzf picker)
# ---------------------------------------------------------------------------


def _select_ns(
    *,
    all_: bool = False,
    cancelled: bool = False,
    query: str | None = None,
    prefix: str | None = None,
    edit: bool = False,
    daemon: bool = False,
) -> argparse.Namespace:
    return argparse.Namespace(
        all=all_,
        cancelled=cancelled,
        query=query,
        prefix=prefix,
        edit=edit,
        daemon=daemon,
    )


def test_select_filters_candidates_and_launches(history_file: Path) -> None:
    launched = "launched prompt to pick"
    cancelled = "cancelled prompt to hide"
    _seed(
        _entry(launched, "260603_000000"),
        _entry(cancelled, "260605_000000", cancelled=True),
    )

    fzf_result = MagicMock(returncode=0, stdout=f"{compute_prompt_id(launched)}  x\n")
    with (
        patch("sase.prompt.cli_run.shutil.which", return_value="/usr/bin/fzf"),
        patch(
            "sase.prompt.cli_run.subprocess.run", return_value=fzf_result
        ) as mock_fzf,
        patch("sase.main.query_handler.special_cases.run_query") as mock_run,
    ):
        handle_prompt_select(_select_ns())

    mock_run.assert_called_once_with(launched)
    # Default candidates exclude cancelled prompts before reaching fzf.
    fzf_input = mock_fzf.call_args.kwargs["input"]
    assert compute_prompt_id(launched) in fzf_input
    assert compute_prompt_id(cancelled) not in fzf_input


def test_select_no_fzf_installed_exits_nonzero(
    history_file: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _seed(_entry("a launched prompt", "260603_000000"))

    with (
        patch("sase.prompt.cli_run.shutil.which", return_value=None),
        patch("sase.main.query_handler.special_cases.run_query") as mock_run,
        pytest.raises(SystemExit) as exc_info,
    ):
        handle_prompt_select(_select_ns())

    assert exc_info.value.code == 1
    mock_run.assert_not_called()
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
        patch("sase.main.query_handler.special_cases.run_query") as mock_run,
        pytest.raises(SystemExit) as exc_info,
    ):
        handle_prompt_select(_select_ns())

    assert exc_info.value.code == 1
    mock_run.assert_not_called()
    assert "No prompt selected" in capsys.readouterr().err


def test_select_no_candidates_exits_nonzero(
    history_file: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _seed(_entry("only a cancelled prompt", "260603_000000", cancelled=True))

    with (
        patch("sase.main.query_handler.special_cases.run_query") as mock_run,
        pytest.raises(SystemExit) as exc_info,
    ):
        handle_prompt_select(_select_ns())

    assert exc_info.value.code == 1
    mock_run.assert_not_called()
    assert "No matching prompts" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# copy (clipboard)
# ---------------------------------------------------------------------------


def test_copy_copies_exact_text(
    history_file: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    text = "exact text to copy to the clipboard"
    _seed(_entry(text, "260603_000000"))

    with patch(
        "sase.prompt.cli_copy.copy_to_system_clipboard", return_value=True
    ) as mock_copy:
        handle_prompt_copy(argparse.Namespace(id=compute_prompt_id(text)))

    mock_copy.assert_called_once_with(text)
    assert compute_prompt_id(text) in capsys.readouterr().out


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
        handle_prompt_copy(argparse.Namespace(id=compute_prompt_id(text)))

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


# ---------------------------------------------------------------------------
# delete (maintenance)
# ---------------------------------------------------------------------------


def test_delete_with_yes_removes_without_prompting(
    history_file: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    keep = "keep this launched prompt"
    drop = "remove this stored prompt"
    _seed(_entry(keep, "260601_000000"), _entry(drop, "260602_000000"))

    handle_prompt_delete(argparse.Namespace(id=compute_prompt_id(drop), yes=True))

    assert [e.text for e in _load_prompt_history()] == [keep]
    assert compute_prompt_id(drop) in capsys.readouterr().out


def test_delete_confirm_yes_on_tty_removes(history_file: Path) -> None:
    drop = "remove this after confirming"
    _seed(_entry("survivor prompt one", "260601_000000"), _entry(drop, "260602_000000"))

    with (
        patch("sase.prompt.cli_maintenance._stdin_is_tty", return_value=True),
        patch("builtins.input", return_value="y"),
    ):
        handle_prompt_delete(argparse.Namespace(id=compute_prompt_id(drop), yes=False))

    assert [e.text for e in _load_prompt_history()] == ["survivor prompt one"]


def test_delete_confirm_no_aborts(
    history_file: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    drop = "do not remove this prompt"
    _seed(_entry(drop, "260602_000000"))

    with (
        patch("sase.prompt.cli_maintenance._stdin_is_tty", return_value=True),
        patch("builtins.input", return_value="n"),
        pytest.raises(SystemExit) as exc_info,
    ):
        handle_prompt_delete(argparse.Namespace(id=compute_prompt_id(drop), yes=False))

    assert exc_info.value.code == 1
    assert [e.text for e in _load_prompt_history()] == [drop]
    assert "Aborted" in capsys.readouterr().err


def test_delete_non_tty_without_yes_fails(
    history_file: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    drop = "stored prompt in a script"
    _seed(_entry(drop, "260602_000000"))

    with (
        patch("sase.prompt.cli_maintenance._stdin_is_tty", return_value=False),
        pytest.raises(SystemExit) as exc_info,
    ):
        handle_prompt_delete(argparse.Namespace(id=compute_prompt_id(drop), yes=False))

    assert exc_info.value.code == 1
    assert [e.text for e in _load_prompt_history()] == [drop]
    assert "--yes" in capsys.readouterr().err


def test_delete_unknown_selector_exits_two(
    history_file: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _seed(_entry("a stored prompt here now", "260602_000000"))

    with pytest.raises(SystemExit) as exc_info:
        handle_prompt_delete(argparse.Namespace(id="ph_ffffffffffff", yes=True))

    assert exc_info.value.code == 2
    assert "No prompt matches selector" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# prune (maintenance)
# ---------------------------------------------------------------------------


def _prune_ns(
    *,
    keep: int | None = None,
    before: str | None = None,
    cancelled: bool = False,
    dry_run: bool = False,
    yes: bool = False,
) -> argparse.Namespace:
    return argparse.Namespace(
        keep=keep,
        before=before,
        cancelled=cancelled,
        dry_run=dry_run,
        yes=yes,
    )


def test_prune_dry_run_prints_plan_without_mutation(
    history_file: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _seed(
        _entry("newest prompt kept", "260603_000000"),
        _entry("oldest prompt dropped", "260601_000000"),
    )

    handle_prompt_prune(_prune_ns(keep=1, dry_run=True))

    out = capsys.readouterr().out
    assert "dry run" in out
    assert "would remove 1" in out
    # Dry-run never mutates.
    assert len(_load_prompt_history()) == 2


def test_prune_yes_applies(history_file: Path) -> None:
    _seed(
        _entry("newest prompt kept", "260603_000000"),
        _entry("oldest prompt dropped", "260601_000000"),
    )

    handle_prompt_prune(_prune_ns(keep=1, yes=True))

    assert [e.text for e in _load_prompt_history()] == ["newest prompt kept"]


def test_prune_confirm_yes_applies(history_file: Path) -> None:
    _seed(
        _entry("newest prompt kept", "260603_000000"),
        _entry("oldest prompt dropped", "260601_000000"),
    )

    with (
        patch("sase.prompt.cli_maintenance._stdin_is_tty", return_value=True),
        patch("builtins.input", return_value="y"),
    ):
        handle_prompt_prune(_prune_ns(keep=1))

    assert [e.text for e in _load_prompt_history()] == ["newest prompt kept"]


def test_prune_non_tty_without_yes_fails(
    history_file: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _seed(
        _entry("newest prompt kept", "260603_000000"),
        _entry("oldest prompt dropped", "260601_000000"),
    )

    with (
        patch("sase.prompt.cli_maintenance._stdin_is_tty", return_value=False),
        pytest.raises(SystemExit) as exc_info,
    ):
        handle_prompt_prune(_prune_ns(keep=1))

    assert exc_info.value.code == 1
    assert len(_load_prompt_history()) == 2
    err = capsys.readouterr().err
    assert "--yes" in err
    assert "--dry-run" in err


def test_prune_no_predicate_exits_two(
    history_file: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _seed(_entry("a stored prompt now", "260601_000000"))

    with pytest.raises(SystemExit) as exc_info:
        handle_prompt_prune(_prune_ns())

    assert exc_info.value.code == 2
    assert "at least one" in capsys.readouterr().err


def test_prune_bad_date_exits_two(
    history_file: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _seed(_entry("a stored prompt now", "260601_000000"))

    with pytest.raises(SystemExit) as exc_info:
        handle_prompt_prune(_prune_ns(before="20260101"))

    assert exc_info.value.code == 2
    assert "YYYY-MM-DD" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# doctor (maintenance)
# ---------------------------------------------------------------------------


def test_doctor_json_has_stable_shape(
    history_file: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _seed(
        _entry("launched prompt one", "260601_000000"),
        _entry("cancelled prompt two", "260602_000000", cancelled=True),
    )

    handle_prompt_doctor(argparse.Namespace(json=True))

    payload = json.loads(capsys.readouterr().out)
    assert set(payload.keys()) == {
        "path",
        "exists",
        "size_bytes",
        "parseable",
        "total",
        "cancelled",
        "invalid_entries",
        "duplicate_ids",
        "legacy_field_entries",
        "oversized",
        "short_recovery",
        "fzf_available",
        "clipboard_available",
    }
    assert payload["total"] == 2
    assert payload["cancelled"] == 1
    assert payload["parseable"] is True


# ---------------------------------------------------------------------------
# export
# ---------------------------------------------------------------------------


def _export_ns(
    prompt_id: str,
    *,
    out: str | None = None,
    sdd: bool = False,
    force: bool = False,
    metadata: bool = False,
) -> argparse.Namespace:
    return argparse.Namespace(
        id=prompt_id, out=out, sdd=sdd, force=force, metadata=metadata
    )


def test_export_stdout_raw_is_byte_exact(
    history_file: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    text = "export this exact prompt body"
    _seed(_entry(text, "260603_000000"))

    handle_prompt_export(_export_ns(compute_prompt_id(text)))

    # Default stdout export is a full-text escape hatch: no frontmatter, no
    # added or stripped newline.
    assert capsys.readouterr().out == text


def test_export_stdout_metadata_wraps_in_frontmatter(
    history_file: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    text = "export with provenance metadata"
    _seed(_entry(text, "260603_091500"))

    handle_prompt_export(_export_ns(compute_prompt_id(text), metadata=True))

    out = capsys.readouterr().out
    assert out.startswith("---\n")
    assert f"id: {compute_prompt_id(text)}" in out
    assert "sha256:" in out
    assert "last_used:" in out
    assert "cancelled: false" in out
    assert "source: sase prompt history" in out
    assert text in out


def test_export_out_writes_file_and_guards_overwrite(
    history_file: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    text = "export prompt to a chosen file path"
    _seed(_entry(text, "260603_000000"))
    dest = tmp_path / "exported.md"

    handle_prompt_export(_export_ns(compute_prompt_id(text), out=str(dest)))
    assert dest.read_text(encoding="utf-8") == text + "\n"
    assert compute_prompt_id(text) in capsys.readouterr().out

    # A second export to the same path fails without --force and never clobbers.
    with pytest.raises(SystemExit) as exc_info:
        handle_prompt_export(_export_ns(compute_prompt_id(text), out=str(dest)))
    assert exc_info.value.code == 1
    assert "--force" in capsys.readouterr().err

    # --force replaces the file.
    handle_prompt_export(_export_ns(compute_prompt_id(text), out=str(dest), force=True))
    assert dest.read_text(encoding="utf-8") == text + "\n"


def test_export_sdd_writes_snapshot_with_metadata(
    history_file: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    text = "snapshot this prompt under the sdd tree"
    _seed(_entry(text, "260603_000000"))

    handle_prompt_export(_export_ns(compute_prompt_id(text), sdd=True))

    snapshots = list((tmp_path / "sdd" / "prompts").rglob("*.md"))
    assert len(snapshots) == 1
    snapshot = snapshots[0]
    # Default SDD filename is a clean slug plus the short prompt ID.
    assert compute_prompt_id(text) in snapshot.name
    assert "snapshot-this-prompt" in snapshot.name
    content = snapshot.read_text(encoding="utf-8")
    # --sdd implies metadata even though --metadata was not passed.
    assert content.startswith("---\n")
    assert "source: sase prompt history" in content
    assert text in content


def test_export_out_and_sdd_are_mutually_exclusive(
    history_file: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    text = "ambiguous destination prompt"
    _seed(_entry(text, "260603_000000"))

    with pytest.raises(SystemExit) as exc_info:
        handle_prompt_export(
            _export_ns(compute_prompt_id(text), out=str(tmp_path / "x.md"), sdd=True)
        )

    assert exc_info.value.code == 2
    assert "only one" in capsys.readouterr().err


def test_export_unknown_selector_exits_two(
    history_file: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _seed(_entry("a stored prompt to export", "260603_000000"))

    with pytest.raises(SystemExit) as exc_info:
        handle_prompt_export(_export_ns("ph_ffffffffffff"))

    assert exc_info.value.code == 2
    assert "No prompt matches selector" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# save (xprompt curation)
# ---------------------------------------------------------------------------


def _save_ns(
    prompt_id: str,
    *,
    name: str | None = None,
    description: str | None = None,
    project: str | None = None,
    global_: bool = False,
    force: bool = False,
    tag: list[str] | None = None,
) -> argparse.Namespace:
    return argparse.Namespace(
        id=prompt_id,
        name=name,
        description=description,
        project=project,
        global_=global_,
        force=force,
        tag=tag,
    )


def test_save_local_creates_loadable_xprompt(
    history_file: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.xprompt.loader import load_xprompt_from_file

    monkeypatch.chdir(tmp_path)
    text = "do the important refactor across the parser"
    _seed(_entry(text, "260603_000000"))

    handle_prompt_save(_save_ns(compute_prompt_id(text), name="fix-parser"))

    dest = tmp_path / ".xprompts" / "fix-parser.md"
    xprompt = load_xprompt_from_file(dest)
    assert xprompt is not None
    assert xprompt.name == "fix-parser"
    assert text in xprompt.content
    # Default description is the cleaned one-line preview.
    assert xprompt.description == text


def test_save_tag_persists_prompt_tags_and_stays_loadable(
    history_file: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.xprompt.loader import load_xprompt_from_file

    monkeypatch.chdir(tmp_path)
    text = "review the authentication changes carefully"
    _seed(_entry(text, "260603_000000"))

    handle_prompt_save(
        _save_ns(compute_prompt_id(text), name="fix-auth-review", tag=["review"])
    )

    dest = tmp_path / ".xprompts" / "fix-auth-review.md"
    raw = dest.read_text(encoding="utf-8")
    # User tags live under prompt_tags, not the reserved semantic ``tags`` key,
    # so the loader does not raise on free-form labels.
    assert "prompt_tags:" in raw
    assert "review" in raw
    assert "\ntags:" not in raw

    xprompt = load_xprompt_from_file(dest)
    assert xprompt is not None
    assert xprompt.name == "fix-auth-review"
    # Free-form tags must not leak into the semantic tag set.
    assert xprompt.tags == frozenset()


def test_save_global_writes_home_xprompts(
    history_file: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    text = "save this prompt globally for reuse"
    _seed(_entry(text, "260603_000000"))

    handle_prompt_save(
        _save_ns(compute_prompt_id(text), name="global-prompt", global_=True)
    )

    assert (tmp_path / ".xprompts" / "global-prompt.md").is_file()


def test_save_project_writes_config_dir(
    history_file: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    text = "save this prompt under a project namespace"
    _seed(_entry(text, "260603_000000"))

    handle_prompt_save(
        _save_ns(compute_prompt_id(text), name="proj-prompt", project="bob")
    )

    dest = tmp_path / ".config" / "sase" / "xprompts" / "bob" / "proj-prompt.md"
    assert dest.is_file()


def test_save_auto_name_derives_slug(
    history_file: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    text = "Improve the launcher startup time"
    _seed(_entry(text, "260603_000000"))

    handle_prompt_save(_save_ns(compute_prompt_id(text)))

    assert (tmp_path / ".xprompts" / "improve-the-launcher-startup-time.md").is_file()


def test_save_description_override(
    history_file: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.xprompt.loader import load_xprompt_from_file

    monkeypatch.chdir(tmp_path)
    text = "prompt whose description is overridden"
    _seed(_entry(text, "260603_000000"))

    handle_prompt_save(
        _save_ns(compute_prompt_id(text), name="custom", description="My summary")
    )

    xprompt = load_xprompt_from_file(tmp_path / ".xprompts" / "custom.md")
    assert xprompt is not None
    assert xprompt.description == "My summary"


def test_save_guards_overwrite(
    history_file: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    text = "prompt saved twice to the same name"
    _seed(_entry(text, "260603_000000"))

    handle_prompt_save(_save_ns(compute_prompt_id(text), name="dup"))

    with pytest.raises(SystemExit) as exc_info:
        handle_prompt_save(_save_ns(compute_prompt_id(text), name="dup"))
    assert exc_info.value.code == 1
    assert "--force" in capsys.readouterr().err

    # --force replaces the existing file.
    handle_prompt_save(_save_ns(compute_prompt_id(text), name="dup", force=True))
    assert (tmp_path / ".xprompts" / "dup.md").is_file()


def test_save_global_and_project_are_mutually_exclusive(
    history_file: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    text = "prompt with conflicting destinations"
    _seed(_entry(text, "260603_000000"))

    with pytest.raises(SystemExit) as exc_info:
        handle_prompt_save(
            _save_ns(compute_prompt_id(text), name="x", global_=True, project="bob")
        )

    assert exc_info.value.code == 2
    assert "only one" in capsys.readouterr().err


def test_save_rejects_name_with_path_separator(
    history_file: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    text = "prompt with an unsafe name argument"
    _seed(_entry(text, "260603_000000"))

    with pytest.raises(SystemExit) as exc_info:
        handle_prompt_save(_save_ns(compute_prompt_id(text), name="../escape"))

    assert exc_info.value.code == 2
    assert "invalid name" in capsys.readouterr().err


def test_save_unknown_selector_exits_two(
    history_file: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _seed(_entry("a stored prompt to save", "260603_000000"))

    with pytest.raises(SystemExit) as exc_info:
        handle_prompt_save(_save_ns("ph_ffffffffffff"))

    assert exc_info.value.code == 2
    assert "No prompt matches selector" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# Phase 5: integration-scale bounds (thousands of prompts, a few huge ones)
# ---------------------------------------------------------------------------

# A history big enough that an unbounded command would be obviously wrong:
# thousands of ordinary prompts plus a handful of very large pastes. The
# read-only inspection commands must stay bounded and must never echo a full
# prompt body — only previews.
_BULK_PROMPT_COUNT = 3000
_HUGE_PROMPT_CHARS = 50_000
_HUGE_PROMPT_COUNT = 4

# Bounds the source code promises for inspection output.
_LIST_DEFAULT_LIMIT = 20
_STATS_LARGEST_LIMIT = 5
_STATS_CHIPS_LIMIT = 10
_DOCTOR_LIST_LIMIT = 5
_PREVIEW_MAX = 73  # 72-char window plus a possible ellipsis


@pytest.fixture
def large_history(history_file: Path) -> list[str]:
    """Seed thousands of prompts plus a few very large ones.

    Each huge prompt hides a unique sentinel near its very end — far beyond any
    preview cutoff — and the huge prompts carry the most recent timestamps so
    they land in the default ``list`` window. Returns the sentinels so callers
    can assert the full body never reaches command output.
    """
    entries: list[PromptEntry] = [
        _entry(f"bulk prompt number {i}", f"260101_{i:06d}")
        for i in range(_BULK_PROMPT_COUNT)
    ]

    sentinels: list[str] = []
    for j in range(_HUGE_PROMPT_COUNT):
        sentinel = f"SECRET_TAIL_{j}_END"
        sentinels.append(sentinel)
        # Innocuous head, a huge body, and the secret buried at the tail.
        text = f"huge paste {j} " + ("x" * _HUGE_PROMPT_CHARS) + f" {sentinel}"
        entries.append(_entry(text, f"260201_00000{j}"))

    _seed(*entries)
    return sentinels


def _assert_bounded_and_no_full_text(output: str, sentinels: list[str]) -> None:
    """No buried sentinel and no long run of the huge body may leak."""
    for sentinel in sentinels:
        assert sentinel not in output, f"leaked full prompt body ({sentinel})"
    # Previews cap well under 200 chars, so a long ``x`` run means a full
    # huge body escaped into the rendered output.
    assert "x" * 200 not in output


def test_large_history_list_stays_bounded_and_hides_full_text(
    large_history: list[str],
    capsys: pytest.CaptureFixture[str],
) -> None:
    sentinels = large_history

    # Default pretty table: bounded rows, previews only.
    handle_prompt_list(
        argparse.Namespace(all=False, cancelled=False, query=None, limit=20, json=False)
    )
    _assert_bounded_and_no_full_text(capsys.readouterr().out, sentinels)

    # Default JSON: at most the limit, preview-only, no full text.
    handle_prompt_list(
        argparse.Namespace(all=False, cancelled=False, query=None, limit=20, json=True)
    )
    out = capsys.readouterr().out
    _assert_bounded_and_no_full_text(out, sentinels)
    payload = json.loads(out)
    assert len(payload) == _LIST_DEFAULT_LIMIT
    for row in payload:
        assert "text" not in row  # list never emits full text
        assert len(row["text_preview"]) <= _PREVIEW_MAX


def test_large_history_stats_stays_bounded_and_hides_full_text(
    large_history: list[str],
    capsys: pytest.CaptureFixture[str],
) -> None:
    sentinels = large_history

    handle_prompt_stats(argparse.Namespace(json=True))
    out = capsys.readouterr().out
    _assert_bounded_and_no_full_text(out, sentinels)
    payload = json.loads(out)
    assert payload["total"] == _BULK_PROMPT_COUNT + _HUGE_PROMPT_COUNT
    assert payload["length_percentiles"]["max"] >= _HUGE_PROMPT_CHARS
    assert len(payload["largest"]) <= _STATS_LARGEST_LIMIT
    assert len(payload["top_chips"]) <= _STATS_CHIPS_LIMIT
    for item in payload["largest"]:
        assert "text" not in item
        assert len(item["preview"]) <= _PREVIEW_MAX

    handle_prompt_stats(argparse.Namespace(json=False))
    _assert_bounded_and_no_full_text(capsys.readouterr().out, sentinels)


def test_large_history_doctor_stays_bounded_and_hides_full_text(
    large_history: list[str],
    capsys: pytest.CaptureFixture[str],
) -> None:
    sentinels = large_history

    handle_prompt_doctor(argparse.Namespace(json=True))
    out = capsys.readouterr().out
    _assert_bounded_and_no_full_text(out, sentinels)
    payload = json.loads(out)
    assert payload["parseable"] is True
    assert payload["total"] == _BULK_PROMPT_COUNT + _HUGE_PROMPT_COUNT
    assert len(payload["oversized"]) <= _DOCTOR_LIST_LIMIT
    for item in payload["oversized"]:
        assert item["text_chars"] >= _HUGE_PROMPT_CHARS
        assert len(item["preview"]) <= _PREVIEW_MAX

    handle_prompt_doctor(argparse.Namespace(json=False))
    _assert_bounded_and_no_full_text(capsys.readouterr().out, sentinels)
