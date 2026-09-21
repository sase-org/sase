"""Alias contract tests for ``sase axe start|stop|restart|status``."""

from __future__ import annotations

import argparse

import pytest

import sase.main.scheduler_handler as scheduler_handler
from sase.main.axe_handler import handle_axe_command
from sase.main.parser import create_parser
from tests.main.parser_help_helpers import flat_help, parser_for


def _parse(argv: list[str]) -> argparse.Namespace:
    return create_parser().parse_args(argv)


@pytest.mark.parametrize("verb", ["restart", "start", "status", "stop"])
def test_axe_lifecycle_verbs_alias_scheduler_verbs(
    monkeypatch: pytest.MonkeyPatch, verb: str
) -> None:
    """Each axe lifecycle verb reaches the scheduler handler with the same values."""
    seen: list[argparse.Namespace] = []

    def fake_handle(args: argparse.Namespace) -> None:
        seen.append(args)
        raise SystemExit(0)

    monkeypatch.setattr(scheduler_handler, "handle_scheduler_command", fake_handle)

    extra = ["-j"] if verb == "status" else []

    axe_ns = _parse(["axe", verb, *extra])
    scheduler_ns = _parse(["scheduler", verb, *extra])

    assert axe_ns.axe_subcommand == verb
    assert scheduler_ns.scheduler_subcommand == verb

    with pytest.raises(SystemExit):
        handle_axe_command(axe_ns)

    assert len(seen) == 1
    delegated = seen[0]
    assert delegated is axe_ns
    assert delegated.scheduler_subcommand == verb
    assert getattr(delegated, "json", None) == getattr(scheduler_ns, "json", None)


def test_axe_restart_rejects_verify_timeout() -> None:
    with pytest.raises(SystemExit):
        _parse(["axe", "restart", "--verify-timeout", "30"])


def test_axe_stop_rejects_force() -> None:
    with pytest.raises(SystemExit):
        _parse(["axe", "stop", "--force"])
    with pytest.raises(SystemExit):
        _parse(["axe", "stop", "-f"])


def test_axe_help_names_scheduler_alias() -> None:
    help_text = flat_help(create_parser().format_help())

    assert "Alias of `sase scheduler`, plus the routine and job tree" in help_text


def test_scheduler_help_names_axe_alias() -> None:
    help_text = flat_help(parser_for(("sase", "scheduler")).format_help())

    assert "sase axe" in help_text
