"""CLI, display, and tagging surfaces for detached tool runs."""

from __future__ import annotations

import pytest

from ._detach_helpers import clean_env


def test_detached_runs_raise_no_settlement_notification() -> None:
    from sase.tool.notify import deliver_handoff_settlement

    run = {
        "run_id": "abc",
        "state": "succeeded",
        "launch_mode": "handoff",
        "owner_kind": "proc",
        "starter": {"agent": "agent-1", "pid": 1},
    }
    assert deliver_handoff_settlement(run) == "skipped"


def test_show_renders_starter_and_join(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from sase.tool._query_shared import print_show

    clean_env(monkeypatch, tmp_path)
    print_show(
        {
            "run": {
                "run_id": "abc",
                "launch_mode": "handoff",
                "starter": {"agent": "agent-1", "pid": 1},
                "join": {"kind": "monitor", "id": "mon-1", "joined_ts": 1720000000},
            }
        }
    )
    out = capsys.readouterr().out
    assert "detached by agent agent-1" in out
    assert "joined by monitor mon-1 at " in out
    capsys.readouterr()
    print_show({"run": {"run_id": "abc", "launch_mode": "handoff"}})
    out = capsys.readouterr().out
    assert "DETACHED" not in out
    assert "JOINED" not in out


def test_parser_detach_mutually_exclusive_with_hand_off() -> None:
    import argparse

    from sase.main.parser_tool import register_tool_parser

    parser = argparse.ArgumentParser(prog="sase")
    subs = parser.add_subparsers(dest="command")
    register_tool_parser(subs)
    args = parser.parse_args(["tool", "run", "-d", "--", "printf", "hi"])
    assert args.detach is True
    assert args.hand_off is False
    with pytest.raises(SystemExit) as excinfo:
        parser.parse_args(["tool", "run", "-H", "-d", "--", "printf", "hi"])
    assert excinfo.value.code == 2


def test_detached_owner_tags_carry_detached_marker() -> None:
    from sase.tool.handoff import owner_tags

    assert owner_tags("abc") == ["tool-run", "tool-run:abc"]
    assert owner_tags("abc", detached=True) == [
        "tool-run",
        "tool-run:abc",
        "tool-run-detached",
    ]


def test_join_tags_carry_only_the_join_prefix() -> None:
    from sase.tool.handoff import (
        TOOL_RUN_JOIN_TAG_PREFIX,
        join_tags,
        owner_tags,
    )

    assert TOOL_RUN_JOIN_TAG_PREFIX == "tool-run-join:"
    assert join_tags("abc") == ["tool-run-join:abc"]
    assert join_tags("abc") != owner_tags("abc")
