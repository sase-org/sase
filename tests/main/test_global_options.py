"""Tests for root-level feature-flag CLI options."""

from __future__ import annotations

import json
import os
import sys

import pytest

from sase.completion.kinds import ValueKind, resolve_value_kind
from sase.feature_flags import snapshot as snapshot_mod
from sase.feature_flags.env import SASE_FEATURE_FLAGS_ENV
from sase.main.global_options import (
    FEATURE_FLAG_OPTION_STRINGS,
    _GlobalOptionError,
    _extract_leading_feature_flag_options,
    consume_global_options,
)
from sase.main.parser import create_parser, parser_only_hint
from tests._conftest_runtime import reset_process_feature_flags


REGISTERED_ENABLE_KEY = "ref_sync_gesture"
REGISTERED_DISABLE_KEY = "ref_sync_gesture"


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        (["-f", "foo", "cmd"], {"foo": True}),
        (["-ffoo", "cmd"], {"foo": True}),
        (["--enable-feature", "foo", "cmd"], {"foo": True}),
        (["--enable-feature=foo", "cmd"], {"foo": True}),
        (["-F", "foo", "cmd"], {"foo": False}),
        (["-Ffoo", "cmd"], {"foo": False}),
        (["--disable-feature", "foo", "cmd"], {"foo": False}),
        (["--disable-feature=foo", "cmd"], {"foo": False}),
    ],
)
def test_extract_accepts_all_option_spellings(
    argv: list[str],
    expected: dict[str, bool],
) -> None:
    values, remaining = _extract_leading_feature_flag_options(argv)

    assert values == expected
    assert remaining == ["cmd"]


def test_extract_repeated_same_side_is_idempotent() -> None:
    values, remaining = _extract_leading_feature_flag_options(
        ["-f", "foo", "--enable-feature=foo", "-ffoo", "cmd"]
    )

    assert values == {"foo": True}
    assert remaining == ["cmd"]


def test_extract_mixed_enable_and_disable() -> None:
    values, remaining = _extract_leading_feature_flag_options(
        ["-f", "foo", "-F", "bar", "cmd"]
    )

    assert values == {"foo": True, "bar": False}
    assert remaining == ["cmd"]


def test_extract_stops_at_first_non_option_token() -> None:
    values, remaining = _extract_leading_feature_flag_options(
        ["-f", "foo", "bead", "-F", "bar"]
    )

    assert values == {"foo": True}
    assert remaining == ["bead", "-F", "bar"]


def test_extract_ignores_tokens_after_separator() -> None:
    values, remaining = _extract_leading_feature_flag_options(
        ["-f", "foo", "--", "-F", "bar"]
    )

    assert values == {"foo": True}
    assert remaining == ["--", "-F", "bar"]


def test_extract_leaves_argv_untouched_when_no_feature_flag_option() -> None:
    argv = ["bead", "list", "-f", "json"]
    original = list(argv)

    values, remaining = _extract_leading_feature_flag_options(argv)

    assert values == {}
    assert remaining == original
    assert argv == original


def test_extract_does_not_mutate_input() -> None:
    argv = ["-f", "foo", "cmd"]
    original = list(argv)

    _extract_leading_feature_flag_options(argv)

    assert argv == original


def test_extract_rejects_key_on_both_sides() -> None:
    with pytest.raises(_GlobalOptionError, match="both enabled and disabled") as exc:
        _extract_leading_feature_flag_options(["-f", "foo", "-F", "foo", "cmd"])

    assert "foo" in str(exc.value)


@pytest.mark.parametrize(
    "argv",
    [
        ["-f"],
        ["--enable-feature"],
        ["-F"],
        ["--disable-feature"],
        ["-f", "--"],
        ["--enable-feature="],
        ["--disable-feature="],
    ],
)
def test_extract_rejects_missing_value(argv: list[str]) -> None:
    with pytest.raises(_GlobalOptionError, match="expected one argument"):
        _extract_leading_feature_flag_options(argv)


def test_consume_rewrites_argv_and_records_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "sase",
            "-F",
            REGISTERED_DISABLE_KEY,
            "flag",
            "list",
        ],
    )
    monkeypatch.delenv(SASE_FEATURE_FLAGS_ENV, raising=False)
    reset_process_feature_flags()

    consume_global_options()

    assert sys.argv == ["sase", "flag", "list"]
    assert snapshot_mod._cli_values == {
        REGISTERED_DISABLE_KEY: False,
    }
    assert json.loads(os.environ[SASE_FEATURE_FLAGS_ENV]) == {
        REGISTERED_DISABLE_KEY: False,
    }


def test_consume_leaves_argv_untouched_without_feature_flag_options(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = ["sase", "-h"]
    monkeypatch.setattr(sys, "argv", original)

    consume_global_options()

    assert sys.argv == original


def test_consume_unknown_key_exits_2(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(sys, "argv", ["sase", "-f", "bogus_key", "ace"])

    with pytest.raises(SystemExit) as exc:
        consume_global_options()

    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert err.startswith("sase: error:")
    assert "bogus_key" in err
    assert "sase flag list" in err
    assert sys.argv == ["sase", "-f", "bogus_key", "ace"]


def test_consume_both_sides_exits_2(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        ["sase", "-f", REGISTERED_ENABLE_KEY, "-F", REGISTERED_ENABLE_KEY, "ace"],
    )

    with pytest.raises(SystemExit) as exc:
        consume_global_options()

    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert err.startswith("sase: error:")
    assert REGISTERED_ENABLE_KEY in err
    assert "both enabled and disabled" in err


def test_consume_missing_value_exits_2(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(sys, "argv", ["sase", "-f"])

    with pytest.raises(SystemExit) as exc:
        consume_global_options()

    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert err.startswith("sase: error:")
    assert "expected one argument" in err


def test_consume_reports_malformed_inherited_env(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        sys, "argv", ["sase", "-f", REGISTERED_ENABLE_KEY, "flag", "list"]
    )
    monkeypatch.setenv(SASE_FEATURE_FLAGS_ENV, "not-json")

    with pytest.raises(SystemExit) as exc:
        consume_global_options()

    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert err.startswith("sase: error:")
    assert SASE_FEATURE_FLAGS_ENV in err
    assert "Traceback" not in err


def test_consume_rewrites_argv_so_bead_fast_path_still_narrows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        ["sase", "-f", REGISTERED_ENABLE_KEY, "bead", "list"],
    )
    monkeypatch.delenv(SASE_FEATURE_FLAGS_ENV, raising=False)
    reset_process_feature_flags()

    consume_global_options()

    assert sys.argv == ["sase", "bead", "list"]
    assert parser_only_hint(sys.argv) == "bead"


def test_bead_list_format_flag_still_parses_after_root_registration() -> None:
    args = create_parser().parse_args(["bead", "list", "-f", "json"])

    assert args.command == "bead"
    assert args.bead_subcommand == "list"
    assert args.format == "json"
    assert getattr(args, "enable_feature", None) is None


def test_registered_option_strings_match_constant() -> None:
    parser = create_parser()
    registered = {
        action.dest: action
        for action in parser._actions
        if action.dest in {"enable_feature", "disable_feature"}
    }

    assert set(registered) == {"enable_feature", "disable_feature"}
    strings = {
        option for action in registered.values() for option in action.option_strings
    }
    expected = {option for group in FEATURE_FLAG_OPTION_STRINGS for option in group}
    assert strings == expected
    for action in registered.values():
        assert resolve_value_kind(action, ()) is ValueKind.FLAG
