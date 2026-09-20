"""Tests for ``sase notify rules`` and its ``--explain`` mode."""

from __future__ import annotations

import argparse
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from sase.config.layers import ConfigLayer
from sase.main.notify_handler import handle_notify_command
from sase.main.parser import create_parser
from sase.notifications import cli_rules, delivery
from sase.notifications.cli_rules import handle_notify_rules
from sase.notifications.store import append_notification

from tests.main.notify_handler_helpers import make_notification

pytest_plugins = ["tests.main.notify_handler_fixtures"]

_QUIET_BEADS: dict[str, Any] = {
    "name": "quiet-task-beads",
    "description": "Task-bead triage is too noisy to announce right now.",
    "match": {"tab": "beads"},
    "toast": False,
    "sound": "none",
}
_CHIME: dict[str, Any] = {"name": "mac-chime", "sound": "/tmp/Glass.aiff"}


@pytest.fixture(autouse=True)
def _clean_rule_cache() -> Iterator[None]:
    delivery._delivery_rules_for_token.cache_clear()
    yield
    delivery._delivery_rules_for_token.cache_clear()


def _use_rules(
    monkeypatch: pytest.MonkeyPatch,
    user: list[Any] | None = None,
    overlay: list[Any] | None = None,
) -> None:
    layers = [
        ConfigLayer(
            name="default",
            path=None,
            exists=True,
            list_strategy="concatenate",
            data={"ace": {"notification_rules": []}},
        )
    ]
    if user is not None:
        layers.append(
            ConfigLayer(
                name="user",
                path=None,
                exists=True,
                list_strategy="replace",
                data={"ace": {"notification_rules": user}},
            )
        )
    if overlay is not None:
        layers.append(
            ConfigLayer(
                name="overlay:sase_mac.yml",
                path=None,
                exists=True,
                list_strategy="concatenate",
                data={"ace": {"notification_rules": overlay}},
            )
        )
    merged = [*(user or []), *(overlay or [])]
    monkeypatch.setattr(delivery, "load_config_layers", lambda: layers)
    monkeypatch.setattr(
        delivery,
        "load_merged_config",
        lambda: {"ace": {"notification_rules": merged}},
    )
    monkeypatch.setattr(
        delivery, "current_config_token", lambda: ("token", len(merged))
    )


def _args(**overrides: object) -> argparse.Namespace:
    values: dict[str, object] = {
        "notify_subcommand": "rules",
        "explain": None,
        "json": False,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


def _task_triage(notification_id: str = "bead-1") -> Any:
    return make_notification(
        notification_id,
        sender="bead",
        action="TaskTriage",
        tags=["bead", "task"],
        notes=["Triage task sase-1"],
        action_data={"panel": "beads"},
    )


def _axe_error(notification_id: str = "axe-1") -> Any:
    return make_notification(
        notification_id,
        sender="axe",
        action="ViewErrorReport",
        notes=["Axe error digest"],
        tags=["error"],
    )


def test_parser_registers_rules_with_optional_options() -> None:
    parser = create_parser()

    bare = parser.parse_args(["notify", "rules"])
    assert bare.notify_subcommand == "rules"
    assert bare.explain is None
    assert bare.json is False

    explained = parser.parse_args(["notify", "rules", "-e", "abc123", "-j"])
    assert explained.explain == "abc123"
    assert explained.json is True
    assert parser.parse_args(["notify", "rules", "--explain", "x"]).explain == "x"
    assert parser.parse_args(["notify", "rules", "--json"]).json is True


def test_parser_still_defaults_bare_notify_to_list() -> None:
    args = create_parser().parse_args(["notify"])

    assert args.notify_subcommand == "list"


def test_dispatch_routes_rules_and_exits_zero(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _use_rules(monkeypatch, user=[])

    with pytest.raises(SystemExit) as excinfo:
        handle_notify_command(_args())

    assert excinfo.value.code == 0
    assert "No notification delivery rules are configured." in capsys.readouterr().out


def test_no_rules_prints_the_defaults(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _use_rules(monkeypatch)

    handle_notify_rules(_args())

    out = capsys.readouterr().out
    assert "No notification delivery rules are configured." in out
    assert "keeps the default: toast shown, sound bell." in out
    assert "Ignored" not in out


def test_rules_print_in_evaluation_order_with_layer_and_behaviors(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _use_rules(monkeypatch, user=[_QUIET_BEADS], overlay=[_CHIME])

    handle_notify_rules(_args())

    out = capsys.readouterr().out
    assert "Notification delivery rules (2)" in out
    assert out.index("1. quiet-task-beads  [user]") < out.index(
        "2. mac-chime  [overlay:sase_mac.yml]"
    )
    assert "Task-bead triage is too noisy to announce right now." in out
    assert "match  tab=beads" in out
    assert "toast  hidden" in out
    assert "sound  none" in out
    assert "match  every notification" in out
    assert "sound  /tmp/Glass.aiff" in out
    assert "keeps the default: toast shown, sound bell." in out


def test_priority_reorders_the_listing_but_not_the_rule_labels(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _use_rules(
        monkeypatch,
        user=[{"toast": False}, {"name": "urgent", "priority": 9, "toast": True}],
    )

    handle_notify_rules(_args())

    out = capsys.readouterr().out
    assert out.index("1. urgent  [user]  priority 9") < out.index("2. rule[0]  [user]")


def test_multi_criteria_and_any_of_values_read_naturally(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _use_rules(
        monkeypatch,
        user=[
            {
                "match": {
                    "title": "Plan ready*",
                    "tags": ["plan", "review notes"],
                    "action": "",
                },
                "toast": False,
            }
        ],
    )

    handle_notify_rules(_args())

    assert (
        'match  action="" AND tags=plan|"review notes" AND title="Plan ready*"'
        in capsys.readouterr().out
    )


def test_ignored_entries_are_listed_with_their_reasons(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _use_rules(
        monkeypatch,
        user=[{"name": "typo", "bogus": 1, "toast": False}, {"toast": False}],
    )

    handle_notify_rules(_args())

    out = capsys.readouterr().out
    assert "Notification delivery rules (1)" in out
    assert "Ignored entries (1)" in out
    assert "user entry 0: unknown rule key 'bogus'" in out
    assert "sase doctor -C config.notification_rules" in out


def test_only_ignored_entries_still_report_defaults(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _use_rules(monkeypatch, user=[{"bogus": 1}])

    handle_notify_rules(_args())

    out = capsys.readouterr().out
    assert "No notification delivery rules are configured." in out
    assert "Ignored entries (1)" in out


def test_rules_json_lists_rules_in_evaluation_order(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _use_rules(
        monkeypatch,
        user=[_QUIET_BEADS, {"bogus": 1}],
        overlay=[_CHIME],
    )

    handle_notify_rules(_args(json=True))

    payload = json.loads(capsys.readouterr().out)
    assert payload["defaults"] == {"toast": True, "sound": "bell"}
    assert payload["rules"] == [
        {
            "order": 1,
            "index": 0,
            "label": "quiet-task-beads",
            "name": "quiet-task-beads",
            "description": "Task-bead triage is too noisy to announce right now.",
            "layer": "user",
            "priority": 0,
            "match": {"tab": "beads"},
            "toast": False,
            "sound": "none",
        },
        {
            "order": 2,
            "index": 1,
            "label": "mac-chime",
            "name": "mac-chime",
            "description": None,
            "layer": "overlay:sase_mac.yml",
            "priority": 0,
            "match": {},
            "toast": None,
            "sound": "/tmp/Glass.aiff",
        },
    ]
    assert payload["ignored"] == [
        {
            "layer": "user",
            "layer_index": 1,
            "problems": [
                "unknown rule key 'bogus' (expected one of description, match, "
                "name, priority, sound, toast)"
            ],
        }
    ]


def test_explain_attributes_both_fields_to_the_global_rule(
    monkeypatch: pytest.MonkeyPatch,
    temp_notifications_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The chezmoi target: a global suppression rule beats a machine catch-all."""
    del temp_notifications_dir
    _use_rules(monkeypatch, user=[_QUIET_BEADS], overlay=[_CHIME])
    append_notification(_task_triage())

    handle_notify_rules(_args(explain="bead-1"))

    out = capsys.readouterr().out
    assert "Notification bead-1" in out
    assert "tab     beads" in out
    assert "sender  bead" in out
    assert "action  TaskTriage" in out
    assert "tags    bead, task" in out
    assert "title   Triage task sase-1" in out
    assert "toast   hidden  <- quiet-task-beads  [user]" in out
    assert "sound   none  <- quiet-task-beads  [user]" in out


def test_explain_reports_defaults_and_the_catch_all_for_other_rows(
    monkeypatch: pytest.MonkeyPatch,
    temp_notifications_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    del temp_notifications_dir
    _use_rules(monkeypatch, user=[_QUIET_BEADS], overlay=[_CHIME])
    append_notification(_axe_error())

    handle_notify_rules(_args(explain="axe-1"))

    out = capsys.readouterr().out
    assert "tab     errors" in out
    assert "toast   shown  <- default (no matching rule sets toast)" in out
    assert "sound   /tmp/Glass.aiff  <- mac-chime  [overlay:sase_mac.yml]" in out


def test_explain_with_no_rules_is_all_defaults_and_action_less_rows_show_dash(
    monkeypatch: pytest.MonkeyPatch,
    temp_notifications_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    del temp_notifications_dir
    _use_rules(monkeypatch)
    append_notification(make_notification("plain-1", notes=[]))

    handle_notify_rules(_args(explain="plain-1"))

    out = capsys.readouterr().out
    assert "action  -" in out
    assert "title   -" in out
    assert "toast   shown  <- default (no matching rule sets toast)" in out
    assert "sound   bell  <- default (no matching rule sets sound)" in out


def test_explain_json(
    monkeypatch: pytest.MonkeyPatch,
    temp_notifications_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    del temp_notifications_dir
    _use_rules(monkeypatch, user=[_QUIET_BEADS], overlay=[_CHIME])
    append_notification(_task_triage())
    append_notification(_axe_error())

    handle_notify_rules(_args(explain="bead-1", json=True))
    beads = json.loads(capsys.readouterr().out)
    handle_notify_rules(_args(explain="axe-1", json=True))
    axe = json.loads(capsys.readouterr().out)

    assert beads == {
        "notification": {
            "id": "bead-1",
            "tab": "beads",
            "sender": "bead",
            "action": "TaskTriage",
            "tags": ["bead", "task"],
            "title": "Triage task sase-1",
        },
        "delivery": {
            "toast": {"value": False, "rule": "quiet-task-beads", "layers": ["user"]},
            "sound": {
                "value": "none",
                "kind": "none",
                "rule": "quiet-task-beads",
                "layers": ["user"],
            },
        },
    }
    assert axe["delivery"] == {
        "toast": {"value": True, "rule": None, "layers": []},
        "sound": {
            "value": "/tmp/Glass.aiff",
            "kind": "file",
            "rule": "mac-chime",
            "layers": ["overlay:sase_mac.yml"],
        },
    }


def test_explain_accepts_a_unique_prefix_and_dismissed_rows(
    monkeypatch: pytest.MonkeyPatch,
    temp_notifications_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    del temp_notifications_dir
    _use_rules(monkeypatch, user=[_QUIET_BEADS])
    row = _task_triage("abcdef-0001")
    row.dismissed = True
    append_notification(row)
    append_notification(_axe_error("zzz-0002"))

    handle_notify_rules(_args(explain="abcd"))

    assert "Notification abcdef-0001" in capsys.readouterr().out


def test_explain_unknown_id_exits_2(
    monkeypatch: pytest.MonkeyPatch,
    temp_notifications_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    del temp_notifications_dir
    _use_rules(monkeypatch)

    with pytest.raises(SystemExit) as excinfo:
        handle_notify_rules(_args(explain="nope"))

    assert excinfo.value.code == 2
    assert "notification not found: nope" in capsys.readouterr().err


def test_explain_ambiguous_prefix_exits_2(
    monkeypatch: pytest.MonkeyPatch,
    temp_notifications_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    del temp_notifications_dir
    _use_rules(monkeypatch)
    append_notification(_axe_error("shared-1"))
    append_notification(_axe_error("shared-2"))

    with pytest.raises(SystemExit) as excinfo:
        handle_notify_rules(_args(explain="shared"))

    assert excinfo.value.code == 2
    assert "ambiguous notification id prefix: shared (2 matches)" in (
        capsys.readouterr().err
    )


def test_exact_id_wins_over_longer_ids_it_prefixes(
    monkeypatch: pytest.MonkeyPatch,
    temp_notifications_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    del temp_notifications_dir
    _use_rules(monkeypatch)
    append_notification(_axe_error("abc"))
    append_notification(_axe_error("abcdef"))

    handle_notify_rules(_args(explain="abc"))

    assert "Notification abc\n" in capsys.readouterr().out


def test_unreadable_config_exits_1(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def boom() -> list[ConfigLayer]:
        raise RuntimeError("layer collision")

    monkeypatch.setattr(delivery, "load_config_layers", boom)

    with pytest.raises(SystemExit) as excinfo:
        handle_notify_rules(_args())

    assert excinfo.value.code == 1
    assert "cannot read notification rules: layer collision" in capsys.readouterr().err


def test_layer_replay_disagreeing_with_the_poll_falls_back_to_the_polled_rules(
    monkeypatch: pytest.MonkeyPatch,
    temp_notifications_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``--explain`` must never attribute a decision to rules the poll is not using."""
    del temp_notifications_dir
    _use_rules(monkeypatch, user=[_QUIET_BEADS])
    monkeypatch.setattr(
        delivery,
        "load_merged_config",
        lambda: {"ace": {"notification_rules": [_CHIME]}},
    )
    append_notification(_axe_error())

    handle_notify_rules(_args())
    listing = capsys.readouterr().out
    handle_notify_rules(_args(explain="axe-1"))
    explained = capsys.readouterr().out

    assert "1. mac-chime  [merged]" in listing
    assert "quiet-task-beads" not in listing
    assert "sound   /tmp/Glass.aiff  <- mac-chime  [merged]" in explained


def test_help_documents_the_options(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        create_parser().parse_args(["notify", "rules", "-h"])

    out = capsys.readouterr().out
    assert "-e, --explain ID" in out
    assert "-j, --json" in out
    assert out.index("--explain") < out.index("--json")
    assert cli_rules.handle_notify_rules.__doc__
