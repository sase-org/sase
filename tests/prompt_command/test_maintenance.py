"""Delete, prune, and doctor coverage for ``sase prompt``."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.history.prompt_store import load_prompt_history
from sase.prompt.cli_maintenance import (
    handle_prompt_delete,
    handle_prompt_doctor,
    handle_prompt_prune,
)

from ._helpers import _entry, _prompt_id, _prune_ns, _seed


def test_delete_with_yes_removes_without_prompting(
    history_file: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    keep = "keep this launched prompt"
    drop = "remove this stored prompt"
    _seed(_entry(keep, "260601_000000"), _entry(drop, "260602_000000"))

    handle_prompt_delete(argparse.Namespace(id=_prompt_id(drop), yes=True))

    assert [e.text for e in load_prompt_history()] == [keep]
    assert _prompt_id(drop) in capsys.readouterr().out


def test_delete_confirm_yes_on_tty_removes(history_file: Path) -> None:
    drop = "remove this after confirming"
    _seed(_entry("survivor prompt one", "260601_000000"), _entry(drop, "260602_000000"))

    with (
        patch("sase.prompt.cli_maintenance._stdin_is_tty", return_value=True),
        patch("builtins.input", return_value="y"),
    ):
        handle_prompt_delete(argparse.Namespace(id=_prompt_id(drop), yes=False))

    assert [e.text for e in load_prompt_history()] == ["survivor prompt one"]


def test_delete_confirm_no_aborts(
    history_file: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    drop = "do not remove this prompt"
    _seed(_entry(drop, "260602_000000"))

    with (
        patch("sase.prompt.cli_maintenance._stdin_is_tty", return_value=True),
        patch("builtins.input", return_value="n"),
        pytest.raises(SystemExit) as exc_info,
    ):
        handle_prompt_delete(argparse.Namespace(id=_prompt_id(drop), yes=False))

    assert exc_info.value.code == 1
    assert [e.text for e in load_prompt_history()] == [drop]
    assert "Aborted" in capsys.readouterr().err


def test_delete_non_tty_without_yes_fails(
    history_file: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    drop = "stored prompt in a script"
    _seed(_entry(drop, "260602_000000"))

    with (
        patch("sase.prompt.cli_maintenance._stdin_is_tty", return_value=False),
        pytest.raises(SystemExit) as exc_info,
    ):
        handle_prompt_delete(argparse.Namespace(id=_prompt_id(drop), yes=False))

    assert exc_info.value.code == 1
    assert [e.text for e in load_prompt_history()] == [drop]
    assert "--yes" in capsys.readouterr().err


def test_delete_unknown_selector_exits_two(
    history_file: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _seed(_entry("a stored prompt here now", "260602_000000"))

    with pytest.raises(SystemExit) as exc_info:
        handle_prompt_delete(argparse.Namespace(id="ph_ffffffffffff", yes=True))

    assert exc_info.value.code == 2
    assert "No prompt matches selector" in capsys.readouterr().err


def test_prune_dry_run_prints_plan_without_mutation(
    history_file: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _seed(
        _entry("newest prompt kept", "260603_000000"),
        _entry("oldest prompt dropped", "260601_000000"),
    )

    handle_prompt_prune(_prune_ns(keep=1, dry_run=True))

    out = capsys.readouterr().out
    assert "dry run" in out
    assert "would remove 1" in out
    # Dry-run never mutates.
    assert len(load_prompt_history()) == 2


def test_prune_yes_applies(history_file: Path) -> None:
    _seed(
        _entry("newest prompt kept", "260603_000000"),
        _entry("oldest prompt dropped", "260601_000000"),
    )

    handle_prompt_prune(_prune_ns(keep=1, yes=True))

    assert [e.text for e in load_prompt_history()] == ["newest prompt kept"]


def test_prune_confirm_yes_applies(history_file: Path) -> None:
    _seed(
        _entry("newest prompt kept", "260603_000000"),
        _entry("oldest prompt dropped", "260601_000000"),
    )

    with (
        patch("sase.prompt.cli_maintenance._stdin_is_tty", return_value=True),
        patch("builtins.input", return_value="y"),
    ):
        handle_prompt_prune(_prune_ns(keep=1))

    assert [e.text for e in load_prompt_history()] == ["newest prompt kept"]


def test_prune_non_tty_without_yes_fails(
    history_file: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _seed(
        _entry("newest prompt kept", "260603_000000"),
        _entry("oldest prompt dropped", "260601_000000"),
    )

    with (
        patch("sase.prompt.cli_maintenance._stdin_is_tty", return_value=False),
        pytest.raises(SystemExit) as exc_info,
    ):
        handle_prompt_prune(_prune_ns(keep=1))

    assert exc_info.value.code == 1
    assert len(load_prompt_history()) == 2
    err = capsys.readouterr().err
    assert "--yes" in err
    assert "--dry-run" in err


def test_prune_no_predicate_exits_two(
    history_file: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _seed(_entry("a stored prompt now", "260601_000000"))

    with pytest.raises(SystemExit) as exc_info:
        handle_prompt_prune(_prune_ns())

    assert exc_info.value.code == 2
    assert "at least one" in capsys.readouterr().err


def test_prune_negative_keep_exits_two_without_mutation(
    history_file: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _seed(
        _entry("newest prompt kept", "260603_000000"),
        _entry("oldest prompt would be dangerous", "260601_000000"),
    )

    with pytest.raises(SystemExit) as exc_info:
        handle_prompt_prune(_prune_ns(keep=-1, yes=True))

    assert exc_info.value.code == 2
    assert len(load_prompt_history()) == 2
    assert "greater than or equal to 0" in capsys.readouterr().err


def test_prune_bad_date_exits_two(
    history_file: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _seed(_entry("a stored prompt now", "260601_000000"))

    with pytest.raises(SystemExit) as exc_info:
        handle_prompt_prune(_prune_ns(before="20260101"))

    assert exc_info.value.code == 2
    assert "YYYY-MM-DD" in capsys.readouterr().err


def test_doctor_json_has_stable_shape(
    history_file: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _seed(
        _entry("launched prompt one", "260601_000000"),
        _entry("cancelled prompt two", "260602_000000", cancelled=True),
    )

    handle_prompt_doctor(argparse.Namespace(json=True))

    payload = json.loads(capsys.readouterr().out)
    assert set(payload.keys()) == {
        "path",
        "exists",
        "size_bytes",
        "shard_count",
        "parseable",
        "total",
        "cancelled",
        "invalid_entries",
        "duplicate_ids",
        "legacy_field_entries",
        "oversized",
        "short_recovery",
        "fzf_available",
        "clipboard_available",
    }
    assert payload["total"] == 2
    assert payload["shard_count"] == 1
    assert payload["cancelled"] == 1
    assert payload["parseable"] is True
