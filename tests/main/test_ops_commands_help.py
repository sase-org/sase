"""Parser help for durable operation commands.

Split from ``test_ops_commands``; the original module re-exports these
tests so its import path keeps working.
"""

from __future__ import annotations

from tests.main.parser_help_helpers import (
    assert_metavar_option_documented,
    flat_help,
    help_subcommand_rows,
    parser_for,
)


def test_patch_help_lists_operation_commands_sorted() -> None:
    patch_parser = parser_for(("sase", "patch"))
    expected = {
        "accept",
        "archive",
        "current",
        "mail",
        "migrate-extension",
        "rebase",
        "ref",
        "restore",
        "revert",
        "rewind",
        "reword",
        "search",
        "set-origin",
        "status",
        "submit",
        "sync",
        "sync-deltas",
        "sync-external",
        "tag",
    }
    assert help_subcommand_rows(patch_parser.format_help(), expected) == sorted(
        expected
    )
    status_help = flat_help(parser_for(("sase", "patch", "status")).format_help())
    assert_metavar_option_documented(
        status_help, "-p", "--project-file", "PROJECT_FILE"
    )
    assert (
        "-Q, --request-path" in status_help
        or "-Q PATH, --request-path PATH" in status_help
    )


def test_notify_and_agent_operation_help() -> None:
    notify_help = parser_for(("sase", "notify")).format_help()
    assert help_subcommand_rows(
        notify_help,
        {"apply-state", "apply-state-many", "create", "list", "show"},
    ) == ["apply-state", "apply-state-many", "create", "list", "show"]
    agent_help = parser_for(("sase", "agent", "persist-directive")).format_help()
    assert "artifacts directory" in agent_help.lower() or "artifacts_dir" in agent_help
    assert "-Q" in agent_help and "--request-path" in agent_help
    cleanup_help = parser_for(("sase", "agent", "persist-cleanup")).format_help()
    assert "-Q" in cleanup_help and "--request-path" in cleanup_help


def test_bead_apply_status_help_is_documented() -> None:
    help_text = parser_for(("sase", "bead", "apply-status")).format_help()
    assert "bead id" in help_text.lower() or "BEAD_ID" in help_text
    assert "-R" in help_text and "--result-path" in help_text
