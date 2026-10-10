"""Unconditional coverage for the retired sase-shell syntax aliases."""

from __future__ import annotations

import argparse

import pytest

from sase.agent.legacy_sase_shell_syntax import (
    normalize_continuation_mode,
    normalize_gate_fork,
    normalize_gate_shell_bool_args,
    normalize_gate_spec_block,
    normalize_persisted_continuation_mode,
    normalize_proc_name_args,
    normalize_reclaim_config,
)
from sase.main.parser_gate import register_gate_parser
from sase.notification_gates.models import GateSpec
from tests._notification_gates_fixtures import custom_gate_spec


def _gate_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    register_gate_parser(parser.add_subparsers(dest="command"))
    return parser


def test_canonical_turn_syntax_passes_through() -> None:
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


def test_legacy_fork_is_always_an_accepted_alias() -> None:
    assert normalize_gate_fork("shell") == "turn"


def test_legacy_spec_block_is_always_an_accepted_alias() -> None:
    assert normalize_gate_spec_block({"shell": {"a": 1}}) == {"turn": {"a": 1}}


def test_legacy_proc_shell_is_always_an_accepted_alias() -> None:
    assert normalize_proc_name_args({"name": None, "shell": "b"}) == {"name": "b"}


def test_legacy_continuation_mode_is_always_an_accepted_alias() -> None:
    assert normalize_continuation_mode("gate_shell") == "gate_turn"
    # Stored bundles map the same way.
    assert normalize_persisted_continuation_mode("gate_shell") == "gate_turn"
    assert normalize_persisted_continuation_mode("gate_turn") == "gate_turn"


def test_gate_spec_legacy_shell_block_and_continuation_normalize() -> None:
    """A pre-rename authored gate spec reads as its turn spelling (sase-1ab.10.1)."""
    raw = custom_gate_spec(request_id="legacy-shell-on")
    raw["shell"] = {"next": {"fork": "session"}}
    raw["continuation_mode"] = "gate_shell"
    spec = GateSpec.from_mapping(raw)
    assert spec.turn is not None
    assert spec.turn.next.fork == "session"
    assert spec.continuation_mode == "gate_turn"


def test_reclaim_config_legacy_shell_key_normalizes() -> None:
    normalized = normalize_reclaim_config(
        {"gate": {"shell": {"reclaim_grace_seconds": 60}}}
    )
    assert normalized["gate"]["turn"] == {"reclaim_grace_seconds": 60}  # type: ignore[index]


def test_gate_turn_reclaim_grace_seconds_reads_legacy_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The config getter reads the legacy key as the turn setting (sase-1ab.10.1)."""
    from sase.config import get_gate_turn_reclaim_grace_seconds

    monkeypatch.setattr(
        "sase.config.core.load_merged_config",
        lambda: {"gate": {"shell": {"reclaim_grace_seconds": 60}}},
    )
    assert get_gate_turn_reclaim_grace_seconds() == 60


def test_gate_create_parses_canonical_turn_flags() -> None:
    parser = _gate_parser()
    args = parser.parse_args(
        ["gate", "create", "--turn", "--turn-status", "P", "--turn-stop-status", "S"]
    )
    assert args.turn is True
    assert args.turn_status == "P"
    assert args.turn_stop_status == "S"


def test_gate_create_legacy_shell_flags_normalize() -> None:
    parser = _gate_parser()
    args = parser.parse_args(["gate", "create", "--shell", "--shell-status", "P"])
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
