"""Tests for the ``config.notification_rules`` doctor check."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from sase.config.layers import ConfigLayer
from sase.core.notification_store_facade import (
    resolve_notification_deliveries as resolve_wire_deliveries,
)
from sase.doctor import checks_config
from sase.doctor import checks_config_notification_rules as rules_check
from sase.doctor.checks_config_notification_rules import (
    check_config_notification_rules,
)
from sase.doctor.runner import default_doctor_context
from sase.notifications import delivery
from sase.notifications.models import Notification


def _use_rules(
    monkeypatch: pytest.MonkeyPatch,
    rules: object,
    *,
    layer: str = "user",
    player: tuple[str, ...] | None = ("/usr/bin/afplay",),
) -> None:
    layers = [
        ConfigLayer(
            name=layer,
            path=None,
            exists=True,
            list_strategy="replace",
            data={"ace": {"notification_rules": rules}},
        )
    ]
    monkeypatch.setattr(delivery, "load_config_layers", lambda: layers)
    monkeypatch.setattr(rules_check, "resolve_sound_player", lambda: player)


def test_no_rules_configured_is_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    _use_rules(monkeypatch, [])

    check = check_config_notification_rules()

    assert check.id == "config.notification_rules"
    assert check.status == "OK"
    assert check.summary == "no notification rules configured"
    assert check.data["rule_count"] == 0


def test_valid_rules_are_ok(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    sound = tmp_path / "chime.wav"
    sound.write_bytes(b"")
    _use_rules(
        monkeypatch,
        [
            {
                "name": "quiet",
                "match": {"tab": "beads"},
                "toast": False,
                "sound": "none",
            },
            {"name": "chime", "sound": str(sound)},
            {"match": {"title": ["Plan ready*", "[!x]*"]}, "sound": "BELL"},
        ],
    )

    check = check_config_notification_rules()

    assert check.status == "OK", check.details
    assert check.summary == "3 notification rule(s) configured"
    assert check.details == ()
    assert check.next_steps == ()


def test_dropped_rules_name_the_layer_rule_and_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_rules(
        monkeypatch,
        [{"name": "typo", "match": {"sendr": "axe"}, "toast": False}],
        layer="overlay:sase_mac.yml",
    )

    check = check_config_notification_rules()

    assert check.status == "WARN"
    assert check.details == (
        "overlay:sase_mac.yml: typo: unknown match criterion 'sendr' (expected one "
        "of action, note, sender, tab, tags, title) (rule ignored)",
    )
    assert check.data["ignored_count"] == 1
    assert "sase notify rules" in check.next_steps[0]


@pytest.mark.parametrize(
    ("rule", "fragment"),
    [
        ({"match": "tab=beads", "toast": False}, "match must be a mapping, not str"),
        ({"toast": False, "extra": 1}, "unknown rule key 'extra'"),
        ({"toast": "no"}, "toast must be true or false"),
    ],
)
def test_malformed_rules_are_flagged_as_ignored(
    monkeypatch: pytest.MonkeyPatch, rule: dict[str, Any], fragment: str
) -> None:
    _use_rules(monkeypatch, [rule])

    check = check_config_notification_rules()

    assert check.status == "WARN"
    assert fragment in check.details[0]
    assert check.details[0].endswith("(rule ignored)")


def test_missing_sound_file_is_flagged_after_expansion(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("SASE_TEST_SOUND_DIR", str(tmp_path))
    (tmp_path / "here.wav").write_bytes(b"")
    _use_rules(
        monkeypatch,
        [
            {"name": "present", "sound": "$SASE_TEST_SOUND_DIR/here.wav"},
            {"name": "absent", "sound": "$SASE_TEST_SOUND_DIR/gone.wav"},
        ],
    )

    check = check_config_notification_rules()

    assert check.status == "WARN"
    assert check.details == (
        f"user: absent: sound file '{tmp_path / 'gone.wav'}' does not exist",
    )


def test_directory_is_not_a_playable_sound_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _use_rules(monkeypatch, [{"name": "dir", "sound": str(tmp_path)}])

    assert check_config_notification_rules().status == "WARN"


def test_reserved_sound_words_are_not_treated_as_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_rules(
        monkeypatch,
        [{"sound": "bell"}, {"sound": "None"}, {"sound": "BELL"}],
        player=None,
    )

    check = check_config_notification_rules()

    assert check.status == "OK", check.details


def test_sound_file_without_a_player_is_flagged_once(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    first = tmp_path / "a.wav"
    second = tmp_path / "b.wav"
    first.write_bytes(b"")
    second.write_bytes(b"")
    _use_rules(
        monkeypatch,
        [{"sound": str(first)}, {"sound": str(second)}],
        player=None,
    )

    check = check_config_notification_rules()

    assert check.status == "WARN"
    assert len(check.details) == 1
    assert (
        "no audio player found on PATH for 2 configured sound file(s)"
        in (check.details[0])
    )


@pytest.mark.parametrize(
    ("rule", "suffix"),
    [
        ({"name": "empty", "match": {"tab": "beads"}}, "never changes a delivery"),
        ({"name": "blank", "sound": "  "}, "(a blank sound sets nothing)"),
    ],
)
def test_rule_that_sets_nothing_is_flagged(
    monkeypatch: pytest.MonkeyPatch, rule: dict[str, Any], suffix: str
) -> None:
    _use_rules(monkeypatch, [rule])

    check = check_config_notification_rules()

    assert check.status == "WARN"
    assert check.details[0].endswith(suffix)


def test_toast_alone_or_sound_alone_is_enough(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_rules(monkeypatch, [{"toast": True}, {"toast": False}, {"sound": "none"}])

    assert check_config_notification_rules().status == "OK"


def test_empty_criterion_list_is_flagged(monkeypatch: pytest.MonkeyPatch) -> None:
    _use_rules(monkeypatch, [{"match": {"tags": []}, "toast": False}])

    check = check_config_notification_rules()

    assert check.status == "WARN"
    assert check.details == (
        "user: rule[0]: match.tags is an empty list, which matches nothing",
    )


def test_unclosed_bracket_in_any_criterion_value_is_flagged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_rules(
        monkeypatch,
        [{"match": {"title": "ok*", "note": ["fine", "broken[x"]}, "toast": False}],
    )

    check = check_config_notification_rules()

    assert check.status == "WARN"
    assert check.details == (
        "user: rule[0]: match.note pattern 'broken[x' has an unclosed '[', "
        "which matches a literal '['",
    )


def test_detail_rows_are_bounded_but_the_count_is_not(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_rules(monkeypatch, [{"toast": "no"}] * 25)

    check = check_config_notification_rules()

    assert len(check.details) == 10
    assert check.data["problem_count"] == 25
    assert check.summary == "25 notification rule problem(s) found"


def test_unreadable_layers_warn_instead_of_raising(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom() -> list[ConfigLayer]:
        raise RuntimeError("layer collision")

    monkeypatch.setattr(delivery, "load_config_layers", boom)

    check = check_config_notification_rules()

    assert check.status == "WARN"
    assert check.details == ("RuntimeError: layer collision",)
    assert "config.layers" in check.next_steps[0]


@pytest.mark.parametrize(
    ("pattern", "title", "unclosed"),
    [
        # An unclosed ``[`` is matched as a literal character by the core.
        ("[", "[", True),
        ("a[", "a[", True),
        ("[a", "[a", True),
        ("[]", "[]", True),
        ("[!]", "[!]", True),
        ("[a]b[c", "ab[c", True),
        # A closed class, including a leading ``]`` member, is a real class.
        ("[[]", "[", False),
        ("[]a]", "]", False),
        ("[!]a]", "b", False),
        ("[a]", "a", False),
        ("[a-c]", "b", False),
        ("[!a]", "b", False),
        ("x[*]y", "x*y", False),
        ("[[]x", "[x", False),
        ("[]a]b]", "ab]", False),
    ],
)
def test_unclosed_bracket_detection_agrees_with_the_core(
    pattern: str, title: str, unclosed: bool
) -> None:
    """Pin the scan to how the core reads each pattern, not to a reimplementation."""
    notification = Notification(
        id="n1", timestamp="2026-09-20T12:00:00+00:00", sender="s", notes=[title]
    )
    rule = {"match": {"title": pattern}, "toast": False}
    (resolved,) = resolve_wire_deliveries([rule], [notification])

    assert resolved.toast is False, "the core no longer matches this pattern"
    assert rules_check._has_unclosed_bracket(pattern) is unclosed


def test_registry_lists_the_check_after_notification_tabs() -> None:
    specs = checks_config.config_check_specs(default_doctor_context())
    ids = [spec.id for spec in specs]

    assert "config.notification_rules" in ids
    assert ids.index("config.notification_rules") == (
        ids.index("config.notification_tabs") + 1
    )
    spec = specs[ids.index("config.notification_rules")]
    assert spec.runner is check_config_notification_rules
