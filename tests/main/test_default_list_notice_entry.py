"""Entrypoint tests for the bare list-group delegation notice."""

from __future__ import annotations

import sys
from typing import NoReturn

import pytest


def _stub_agent_handler(marker: str) -> object:
    def _handler(args: object) -> NoReturn:
        del args
        print(marker)
        raise SystemExit(0)

    return _handler


def test_bare_command_group_prints_delegation_notice_before_handler(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A bare defaulted group announces the delegation, then runs ``list``."""
    from sase.main import agent_handler, entry

    monkeypatch.setattr(
        agent_handler, "handle_agent_command", _stub_agent_handler("AGENT-LIST-OUTPUT")
    )
    monkeypatch.setattr(sys, "argv", ["sase", "agent"])

    with pytest.raises(SystemExit) as exc:
        entry.main()

    assert exc.value.code == 0
    out = capsys.readouterr().out
    notice = "No subcommand provided for 'sase agent'; delegating to 'sase agent list'."
    assert notice in out
    assert "AGENT-LIST-OUTPUT" in out
    assert out.index(notice) < out.index("AGENT-LIST-OUTPUT")


def test_explicit_list_subcommand_prints_no_delegation_notice(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Explicitly typing ``list`` skips the delegation notice."""
    from sase.main import agent_handler, entry

    monkeypatch.setattr(
        agent_handler, "handle_agent_command", _stub_agent_handler("AGENT-LIST-OUTPUT")
    )
    monkeypatch.setattr(sys, "argv", ["sase", "agent", "list"])

    with pytest.raises(SystemExit) as exc:
        entry.main()

    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "delegating to" not in out
    assert "AGENT-LIST-OUTPUT" in out
