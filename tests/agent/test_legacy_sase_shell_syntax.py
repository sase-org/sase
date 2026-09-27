"""Both-state coverage for the retired sase-shell syntax flag."""

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
from sase.feature_flags import override_flags
from sase.main.parser_gate import register_gate_parser
from sase.notification_gates.models import GateError, GateSpec
from tests._notification_gates_fixtures import custom_gate_spec


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


def test_legacy_continuation_mode_is_enabled_alias_and_disabled_error() -> None:
    with override_flags(legacy_sase_shell_syntax=True):
        assert normalize_continuation_mode("gate_shell") == "gate_turn"
    with override_flags(legacy_sase_shell_syntax=False):
        with pytest.raises(ValueError, match=r"gate_shell.*retired"):
            normalize_continuation_mode("gate_shell")
    # Stored bundles map unconditionally, regardless of the flag.
    with override_flags(legacy_sase_shell_syntax=False):
        assert normalize_persisted_continuation_mode("gate_shell") == "gate_turn"
    with override_flags(legacy_sase_shell_syntax=True):
        assert normalize_persisted_continuation_mode("gate_shell") == "gate_turn"


def test_gate_spec_legacy_shell_block_and_continuation_follow_the_flag() -> None:
    """A pre-rename authored gate spec reads through the flag (sase-1ab.10.1)."""
    with override_flags(legacy_sase_shell_syntax=True):
        raw = custom_gate_spec(request_id="legacy-shell-on")
        raw["shell"] = {"next": {"fork": "session"}}
        raw["continuation_mode"] = "gate_shell"
        spec = GateSpec.from_mapping(raw)
    assert spec.turn is not None
    assert spec.turn.next.fork == "session"
    assert spec.continuation_mode == "gate_turn"

    with override_flags(legacy_sase_shell_syntax=False):
        raw = custom_gate_spec(request_id="legacy-shell-off")
        raw["shell"] = {"next": {"fork": "session"}}
        with pytest.raises(GateError, match=r"turn"):
            GateSpec.from_mapping(raw)
        raw = custom_gate_spec(request_id="legacy-continuation-off")
        raw["continuation_mode"] = "gate_shell"
        with pytest.raises(GateError, match=r"continuation_mode"):
            GateSpec.from_mapping(raw)


def test_reclaim_config_legacy_shell_key_follows_the_flag() -> None:
    with override_flags(legacy_sase_shell_syntax=True):
        normalized = normalize_reclaim_config(
            {"gate": {"shell": {"reclaim_grace_seconds": 60}}}
        )
        assert normalized["gate"]["turn"] == {"reclaim_grace_seconds": 60}  # type: ignore[index]
    with override_flags(legacy_sase_shell_syntax=False):
        with pytest.raises(ValueError, match=r"gate\.turn\.reclaim_grace_seconds"):
            normalize_reclaim_config({"gate": {"shell": {"reclaim_grace_seconds": 60}}})


def test_gate_turn_reclaim_grace_seconds_reads_legacy_key_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The config getter honors the flag instead of silently ignoring (sase-1ab.10.1)."""
    from sase.config import get_gate_turn_reclaim_grace_seconds

    monkeypatch.setattr(
        "sase.config.core.load_merged_config",
        lambda: {"gate": {"shell": {"reclaim_grace_seconds": 60}}},
    )
    with override_flags(legacy_sase_shell_syntax=True):
        assert get_gate_turn_reclaim_grace_seconds() == 60
    with override_flags(legacy_sase_shell_syntax=False):
        with pytest.raises(ValueError, match=r"gate\.turn\.reclaim_grace_seconds"):
            get_gate_turn_reclaim_grace_seconds()


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
