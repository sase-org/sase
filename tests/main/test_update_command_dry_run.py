"""Tests for ``sase update --dry-run``."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.main.update_handler import handle_update_command
from sase.uv_tool.runner import UvChangeSet
from tests.main.update_command_helpers import (
    _DEV_RECEIPT,
    _args,
    _console,
    _dev_plan,
    _install,
    _inventory,
    _record,
    _text,
    _versions,
)


def test_dry_run_does_not_execute_uv(tmp_path: Path) -> None:
    def _run(_argv: list[str]) -> UvChangeSet:
        raise AssertionError("uv must not run during --dry-run")

    out = _console()
    code = handle_update_command(
        _args(dry_run=True),
        console=out,
        probe_fn=lambda: _install(tmp_path),
        run_fn=_run,
        version_fn=_versions,
    )

    assert code == 0
    text = _text(out)
    assert "uv tool upgrade --color never sase" in text
    assert "sase-github" in text
    assert "Dry run" in text


def test_dry_run_json(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    code = handle_update_command(
        _args(json=True, dry_run=True),
        probe_fn=lambda: _install(tmp_path),
        version_fn=_versions,
    )

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["dry_run"] is True
    assert payload["command"] == ["uv", "tool", "upgrade", "--color", "never", "sase"]
    assert [p["name"] for p in payload["packages"]] == [
        "sase",
        "sase-github",
        "sase-telegram",
    ]
    assert payload["packages"][0] == {
        "name": "sase",
        "role": "primary",
        "current_version": "0.6.1",
    }


def test_dry_run_json_dedupes_duplicate_dev_receipt_plugins(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    host = _record("sase", role="host", source_root="/home/u/sase")
    github = _record("sase-github", role="plugin", source_root="/home/u/sase-github")
    telegram = _record(
        "sase-telegram", role="plugin", source_root="/home/u/sase-telegram"
    )

    code = handle_update_command(
        _args(json=True, dry_run=True),
        probe_fn=lambda: _install(tmp_path, _DEV_RECEIPT),
        inventory_fn=lambda: _inventory(host, github, telegram),
        plan_dev_update_fn=lambda records, **_kwargs: _dev_plan(*records),
        version_fn=_versions,
    )

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["mode"] == "dev"
    assert payload["command"] == []
    # One dev plan package per editable distribution, no duplicated
    # sase-github/telegram from the receipt's bare-index duplicate rows.
    assert [p["name"] for p in payload["dev"]["packages"]] == [
        "sase",
        "sase-github",
        "sase-telegram",
    ]


def test_dev_dry_run_renders_plan_without_executing(tmp_path: Path) -> None:
    host = _record("sase", role="host", source_root="/home/u/sase")

    def _run_uv(_argv: list[str]) -> UvChangeSet:
        raise AssertionError("uv must not run during --dry-run")

    out = _console()
    code = handle_update_command(
        _args(dry_run=True),
        console=out,
        probe_fn=lambda: _install(tmp_path, _DEV_RECEIPT),
        run_fn=_run_uv,
        inventory_fn=lambda: _inventory(host),
        plan_dev_update_fn=lambda records, **_kwargs: _dev_plan(*records),
        version_fn=_versions,
    )

    assert code == 0
    text = _text(out)
    assert "SASE Update (dry run)" in text
    assert "fetch + fast-forward" in text
    assert "Reinstall uv-tool editable Python packages" in text


def test_editable_dry_run_includes_managed_core_reconciliation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    host = _record("sase", role="host", source_root="/home/u/sase")
    github = _record("sase-github", role="plugin", source_root="/home/u/sase-github")
    telegram = _record(
        "sase-telegram", role="plugin", source_root="/home/u/sase-telegram"
    )
    core = _record(
        "sase-core-rs",
        role="core",
        source_root=None,
        display_version="0.4.0",
        distribution_version="0.4.0",
        install_type="wheel",
    )
    overrides = tmp_path / "editable-overrides.txt"
    monkeypatch.setattr(
        "sase.main.update_routing.write_editable_overrides",
        lambda _requirements: overrides,
    )

    code = handle_update_command(
        _args(json=True, dry_run=True),
        probe_fn=lambda: _install(tmp_path, _DEV_RECEIPT),
        inventory_fn=lambda: _inventory(host, core, github, telegram),
        plan_dev_update_fn=lambda records, **_kwargs: _dev_plan(
            *records, status="skipped"
        ),
        version_fn=_versions,
    )

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["mode"] == "mixed"
    assert payload["command"][-2:] == ["--upgrade-package", "sase-core-rs"]
    assert payload["managed"] == {
        "command": payload["command"],
        "packages": [
            {
                "name": "sase-core-rs",
                "role": "dependency",
                "current_version": "0.4.0",
            }
        ],
    }
    assert [package["status"] for package in payload["dev"]["packages"]] == [
        "skipped",
        "skipped",
        "skipped",
    ]
