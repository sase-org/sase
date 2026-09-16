"""Unit tests for ``start_command``'s argv-quoting-preserving remainder join."""

from __future__ import annotations

from sase.main.monitor.common import start_command
from sase.main.parser import create_parser


def _parse_remainder(*words: str) -> str:
    args = create_parser().parse_args(
        ["monitor", "start", "-r", "verify", "-t", "30s", "--", *words]
    )
    return start_command(args)


def test_start_command_preserves_bare_words() -> None:
    """A plain multi-word command round-trips unchanged."""
    assert _parse_remainder("just", "check-full") == "just check-full"


def test_start_command_preserves_a_single_quoted_string_verbatim() -> None:
    """A single shell-quoted remainder word is returned verbatim, untouched."""
    assert (
        _parse_remainder("just install && just check") == "just install && just check"
    )


def test_start_command_shlex_joins_a_wrapped_shell_c_command() -> None:
    """A `bash -c '...'` remainder is rejoined so its inner quoting survives.

    Regression test for the sase-11o.1 incident: a naive `" ".join` turned
    `bash -c 'just install && just check'` into `bash -c just install &&
    just check`, silently dropping `just install` from the monitored
    command.
    """
    assert (
        _parse_remainder("bash", "-c", "just install && just check")
        == "bash -c 'just install && just check'"
    )
