"""Tests for the ``sase update`` parser and install detection errors."""

from __future__ import annotations

import json

import pytest

from sase.main.parser import create_parser
from sase.main.update_handler import UPDATE_JSON_SCHEMA_VERSION, handle_update_command
from tests.main.update_command_helpers import _args, _console, _not_install, _text


def test_update_is_registered_top_level() -> None:
    ns = create_parser().parse_args(["update"])

    assert ns.command == "update"
    assert ns.dry_run is False
    assert ns.json is False
    assert ns.quiet is False
    assert ns.to is None
    assert ns.yes is False


def test_update_accepts_each_flag() -> None:
    short = create_parser().parse_args(["update", "-n", "-j", "-q", "-t", "dev", "-y"])
    long = create_parser().parse_args(
        ["update", "--dry-run", "--json", "--quiet", "--to", "dev", "--yes"]
    )

    for ns in (short, long):
        assert ns.dry_run is True
        assert ns.json is True
        assert ns.quiet is True
        assert ns.to == "dev"
        assert ns.yes is True


def test_update_json_schema_version_is_pinned_to_dev_schema() -> None:
    assert UPDATE_JSON_SCHEMA_VERSION == 3


def test_not_uv_tool_install_renders_error_and_exits_one() -> None:
    err = _console()
    code = handle_update_command(
        _args(),
        console=_console(),
        err_console=err,
        probe_fn=_not_install,
    )

    assert code == 1
    assert "uv tool" in _text(err)
    assert "uv tool install sase" in _text(err)


def test_not_uv_tool_install_json_error(capsys: pytest.CaptureFixture[str]) -> None:
    code = handle_update_command(_args(json=True), probe_fn=_not_install)

    assert code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema_version"] == UPDATE_JSON_SCHEMA_VERSION
    assert "uv tool" in payload["error"]
