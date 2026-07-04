from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.main.update_handler import handle_update_command
from sase.uv_tool.runner import UvChangeSet
from tests.main.update_command_helpers import (
    _args,
    _console,
    _install,
    _inventory,
    _record,
    _text,
)


def _managed_inventory() -> object:
    return _inventory(
        _record(
            "sase",
            role="host",
            source_root="",
            display_version="0.8.0",
        ),
        _record(
            "sase-core-rs",
            role="core",
            source_root="",
            display_version="0.3.1",
        ),
        _record(
            "sase-github",
            role="plugin",
            source_root="",
            display_version="0.1.0",
        ),
        _record(
            "sase-telegram",
            role="plugin",
            source_root="",
            display_version="0.2.0",
        ),
    )


def test_mode_switch_dry_run_renders_plan(tmp_path: Path) -> None:
    def _run(_argv: list[str]) -> UvChangeSet:
        raise AssertionError("uv must not run during mode-switch dry-run")

    out = _console()
    code = handle_update_command(
        _args(dry_run=True, to="dev"),
        console=out,
        probe_fn=lambda: _install(tmp_path),
        run_fn=_run,
        inventory_fn=_managed_inventory,
        config_fn=lambda: {"update": {"dev_root": str(tmp_path / "dev")}},
    )

    assert code == 0
    text = _text(out)
    assert "Switch install mode" in text
    assert "PyPI (managed)" in text
    assert "Dev (editable)" in text
    assert "uv tool install --color never --force --reinstall" in text
    assert str(tmp_path / "dev" / "sase") in text


def test_mode_switch_json_dry_run_shape(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    code = handle_update_command(
        _args(json=True, dry_run=True, to="dev"),
        probe_fn=lambda: _install(tmp_path),
        inventory_fn=_managed_inventory,
        config_fn=lambda: {"update": {"dev_root": str(tmp_path / "dev")}},
    )

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["dry_run"] is True
    assert payload["switch"]["current_mode"] == "managed"
    assert payload["switch"]["target_mode"] == "dev"
    assert [package["name"] for package in payload["switch"]["packages"]] == [
        "sase",
        "sase-core-rs",
        "sase-github",
        "sase-telegram",
    ]


def test_mode_switch_same_target_is_friendly_noop(tmp_path: Path) -> None:
    out = _console()
    code = handle_update_command(
        _args(to="pypi"),
        console=out,
        probe_fn=lambda: _install(tmp_path),
        inventory_fn=_managed_inventory,
        config_fn=lambda: {"update": {"dev_root": str(tmp_path / "dev")}},
    )

    assert code == 0
    assert "Already a PyPI (managed) install" in _text(out)


def test_mode_switch_json_noop_is_not_dry_run(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    code = handle_update_command(
        _args(json=True, to="pypi"),
        probe_fn=lambda: _install(tmp_path),
        inventory_fn=_managed_inventory,
        config_fn=lambda: {"update": {"dev_root": str(tmp_path / "dev")}},
    )

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["dry_run"] is False
    assert payload["changed"] is False
