"""Readout CLI parser and help tests (split from test_readout)."""

from __future__ import annotations

import pytest

from sase.main.parser import create_parser
from tests.instructions._readout_support import passthrough_manifest_normalize
from tests.main.parser_help_helpers import (
    assert_metavar_option_documented,
    flat_help,
    parser_for,
)


@pytest.fixture(autouse=True)
def _passthrough_manifest_normalize(monkeypatch: pytest.MonkeyPatch) -> None:
    passthrough_manifest_normalize(monkeypatch)


def test_readout_parser_options_are_alphabetical_with_short_aliases() -> None:
    """Every ``readout`` value-taking option keeps its short alias."""
    args = create_parser().parse_args(
        [
            "instructions",
            "readout",
            "-j",
            "-p",
            "codex",
            "-p",
            "claude",
            "-s",
            "7d",
            "-u",
            "2026-10-02T00:00:00Z",
        ]
    )
    assert args.instructions_subcommand == "readout"
    assert args.json is True
    assert args.provider == ["codex", "claude"]
    assert args.since == "7d"
    assert args.until == "2026-10-02T00:00:00Z"


def test_readout_help_documents_flags() -> None:
    """``readout -h`` names every option and the reporting contract."""
    help_text = flat_help(parser_for(("sase", "instructions", "readout")).format_help())
    assert "-j, --json" in help_text
    assert_metavar_option_documented(help_text, "-p", "--provider", "PROVIDER")
    assert_metavar_option_documented(help_text, "-s", "--since", "WHEN")
    assert_metavar_option_documented(help_text, "-u", "--until", "WHEN")
    assert "reports; it does not gate" in help_text


def test_readout_rejects_bad_since() -> None:
    """A bare ``-s 24`` is a clean CLI error (exit 2), not a traceback."""
    from sase.main.instructions_handler import _run_instructions_readout

    args = create_parser().parse_args(["instructions", "readout", "-s", "24"])
    assert _run_instructions_readout(args) == 2
