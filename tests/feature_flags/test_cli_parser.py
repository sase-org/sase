"""Tests for ``sase flag`` parser wiring and command help."""

from __future__ import annotations

from sase.main.parser import create_parser, default_list_delegation_notice
from tests.main.parser_help_helpers import flat_help, help_subcommand_rows, parser_for


def test_flag_group_defaults_to_list() -> None:
    parser = create_parser()
    omitted = parser.parse_args(["flag"])
    explicit = parser.parse_args(["flag", "list"])

    assert omitted.flag_subcommand == "list"
    assert omitted.json is False
    assert default_list_delegation_notice(omitted) == (
        "No subcommand provided for 'sase flag'; delegating to 'sase flag list'."
    )
    assert default_list_delegation_notice(explicit) is None


def test_flag_help_lists_sorted_subcommands_and_managed_gate() -> None:
    flag_parser = parser_for(("sase", "flag"))
    help_text = flag_parser.format_help()
    expected = {"disable", "enable", "list", "new", "show"}

    assert help_subcommand_rows(help_text, expected) == sorted(expected)
    assert "{disable,enable,list,new,show}" in help_text
    assert "is_sase_managed" in help_text
    assert "defaults to `sase flag list`" in help_text
    assert "feature_flags.json" in help_text
    assert "sase/memory/sase_flags.md" not in help_text


def test_flag_enable_and_disable_help_document_persistence_and_restart() -> None:
    for name in ("disable", "enable"):
        help_text = parser_for(("sase", "flag", name)).format_help()
        assert "machine-state file" in help_text
        assert "feature_flags.json" in help_text
        assert "SASE_HOME" in help_text
        assert "SASE_FEATURE_FLAGS" in help_text
        assert "--enable-feature" in help_text
        assert "AXE" in help_text
        assert "ACE" in help_text
        assert "--json" in help_text
        assert "sase/memory/sase_flags.md" not in help_text


def test_flag_enable_and_disable_parse_key_and_json() -> None:
    parser = create_parser()
    enable = parser.parse_args(["flag", "enable", "ref_sync_gesture", "-j"])
    disable = parser.parse_args(["flag", "disable", "ref_sync_gesture"])

    assert enable.flag_subcommand == "enable"
    assert enable.flag_key == "ref_sync_gesture"
    assert enable.json is True
    assert disable.flag_subcommand == "disable"
    assert disable.flag_key == "ref_sync_gesture"
    assert disable.json is False


def test_flag_new_help_documents_optional_flags_with_short_aliases() -> None:
    help_text = flat_help(parser_for(("sase", "flag", "new")).format_help())

    for short, long in (
        ("-d", "--description"),
        ("-k", "--kind"),
        ("-r", "--remove-by"),
        ("-z", "--size"),
    ):
        assert short in help_text
        assert long in help_text
    assert "--when-enabled" in help_text
    assert "--when-disabled" in help_text
    assert "--remove-when" in help_text
    assert "is_sase_managed" in help_text
    assert "sase/memory/sase_flags.md" not in help_text
