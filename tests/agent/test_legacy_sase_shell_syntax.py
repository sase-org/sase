"""Both-state coverage for the retired sase-shell syntax flag."""

from __future__ import annotations

import argparse

import pytest

from sase.agent.legacy_sase_shell_syntax import (
    normalize_continuation_mode,
    normalize_gate_fork,
    normalize_gate_shell_bool_args,
    normalize_gate_spec_block,
    normalize_proc_name_args,
)
from sase.feature_flags import override_flags
from sase.main.parser_gate import register_gate_parser


def _gate_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    register_gate_parser(parser.add_subparsers(dest="command"))
    return parser


@pytest.mark.parametrize("enabled", [False, True])
def test_canonical_turn_syntax_works_in_both_flag_states(enabled: bool) -> None:
    with override_flags(legacy_sase_shell_syntax=enabled):
        assert normalize_gate_fork("turn") == "turn"
        assert normalize_gate_spec_block({"turn": {}}) == {"turn": {}}
        assert normalize_continuation_mode("gate_turn") == "gate_turn"
        assert normalize_proc_name_args({"name": "x", "shell": None}) == {
            "name": "x",
            "shell": None,
        }
        normalized = normalize_gate_shell_bool_args(
            {
                "turn": True,
                "turn_status": None,
                "turn_stop_status": None,
                "shell": False,
                "shell_status": None,
                "shell_stop_status": None,
            }
        )
        assert normalized["turn"] is True


def test_legacy_fork_is_enabled_alias_and_disabled_error() -> None:
    with override_flags(legacy_sase_shell_syntax=True):
        assert normalize_gate_fork("shell") == "turn"
    with override_flags(legacy_sase_shell_syntax=False):
        with pytest.raises(ValueError, match=r'"fork": "shell" is retired'):
            normalize_gate_fork("shell")


def test_legacy_spec_block_is_enabled_alias_and_disabled_error() -> None:
    with override_flags(legacy_sase_shell_syntax=True):
        assert normalize_gate_spec_block({"shell": {"a": 1}}) == {"turn": {"a": 1}}
    with override_flags(legacy_sase_shell_syntax=False):
        with pytest.raises(ValueError, match=r'"turn"'):
            normalize_gate_spec_block({"shell": {"a": 1}})


def test_legacy_proc_shell_is_enabled_alias_and_disabled_error() -> None:
    with override_flags(legacy_sase_shell_syntax=True):
        assert normalize_proc_name_args({"name": None, "shell": "b"}) == {"name": "b"}
    with override_flags(legacy_sase_shell_syntax=False):
        with pytest.raises(ValueError, match=r"--shell is retired; use --name"):
            normalize_proc_name_args({"name": None, "shell": "b"})


def test_gate_create_parses_canonical_turn_flags() -> None:
    parser = _gate_parser()
    args = parser.parse_args(
        ["gate", "create", "--turn", "--turn-status", "P", "--turn-stop-status", "S"]
    )
    assert args.turn is True
    assert args.turn_status == "P"
    assert args.turn_stop_status == "S"


def test_gate_create_legacy_shell_flags_normalize_when_enabled() -> None:
    parser = _gate_parser()
    args = parser.parse_args(["gate", "create", "--shell", "--shell-status", "P"])
    with override_flags(legacy_sase_shell_syntax=True):
        normalized = normalize_gate_shell_bool_args(
            {
                "turn": args.turn,
                "turn_status": args.turn_status,
                "turn_stop_status": args.turn_stop_status,
                "shell": args.shell,
                "shell_status": args.shell_status,
                "shell_stop_status": args.shell_stop_status,
            }
        )
    assert normalized["turn"] is True
    assert normalized["turn_status"] == "P"

    with override_flags(legacy_sase_shell_syntax=False):
        with pytest.raises(ValueError, match=r"--shell is retired"):
            normalize_gate_shell_bool_args(
                {
                    "turn": False,
                    "turn_status": None,
                    "turn_stop_status": None,
                    "shell": True,
                    "shell_status": None,
                    "shell_stop_status": None,
                }
            )
