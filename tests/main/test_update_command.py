"""Tests for the ``sase update`` parser, handler, dry-run, and JSON payload."""

from __future__ import annotations

import argparse
import io
import json
from pathlib import Path
from typing import Any

from rich.console import Console

from sase.axe.process import AxeStartResult
from sase.dev_update.models import (
    DevExecutedCommand,
    DevReconcileStep,
    DevUpdateOutcome,
    DevUpdatePackagePlan,
    DevUpdatePlan,
    DevUpdateResult,
    DevUpdateRootPlan,
)
from sase.main.parser import create_parser
from sase.main.update_handler import (
    UPDATE_JSON_SCHEMA_VERSION,
    _installed_version,
    handle_update_command,
)
from sase.uv_tool.detect import NotUvToolInstall, NotUvToolReason, UvToolInstall
from sase.uv_tool.errors import UvCommandFailedError
from sase.uv_tool.runner import UvChangeSet, parse_uv_output
from sase.version.inventory import RuntimeVersionInventory, VersionPackageRecord

_RECEIPT = """
[tool]
requirements = [
    { name = "sase" },
    { name = "sase-github" },
    { name = "sase-telegram" },
]
"""

# A dev receipt: editable entries plus bare index dups of two plugins, exactly
# what `uv tool install sase` records for an editable dev checkout.
_DEV_RECEIPT = """
[tool]
requirements = [
    { name = "sase", editable = "/home/u/sase" },
    { name = "sase-github", editable = "/home/u/sase-github" },
    { name = "sase-telegram", editable = "/home/u/sase-telegram" },
    { name = "sase-github" },
    { name = "sase-telegram" },
]
"""

_UPGRADE_OUTPUT = """\
Resolved 3 packages in 120ms
 - sase==0.5.0
 + sase==0.6.1
 - sase-github==0.3.2
 + sase-github==0.4.0
"""


def _install(tmp_path: Path, receipt: str = _RECEIPT) -> UvToolInstall:
    sase_dir = tmp_path / "sase"
    sase_dir.mkdir(parents=True, exist_ok=True)
    receipt_path = sase_dir / "uv-receipt.toml"
    receipt_path.write_text(receipt, encoding="utf-8")
    return UvToolInstall(
        uv_path="/usr/bin/uv",
        tool_dir=tmp_path,
        sase_dir=sase_dir,
        receipt_path=receipt_path,
    )


def _not_install() -> NotUvToolInstall:
    return NotUvToolInstall(
        reason=NotUvToolReason.WRONG_PREFIX,
        sys_prefix=Path("/home/u/sase/.venv"),
        expected_sase_dir=Path("/t/sase"),
        receipt_path=Path("/t/sase/uv-receipt.toml"),
        uv_path="/usr/bin/uv",
    )


def _args(*, json: bool = False, dry_run: bool = False, quiet: bool = False):
    return argparse.Namespace(json=json, dry_run=dry_run, quiet=quiet)


def _console() -> Console:
    return Console(file=io.StringIO(), width=200, no_color=True)


def _text(console: Console) -> str:
    return console.file.getvalue()  # type: ignore[attr-defined]


def _versions(name: str) -> str | None:
    return {"sase": "0.6.1", "sase-github": "0.4.0", "sase-telegram": "0.1.0"}.get(name)


def _record(
    name: str,
    *,
    role: str,
    source_root: str,
    display_version: str = "0.6.1+1.gaaaaaaaaa",
) -> VersionPackageRecord:
    return VersionPackageRecord(
        name=name,
        role=role,  # type: ignore[arg-type]
        display_version=display_version,
        distribution_version="0.6.1",
        source_version="0.6.1",
        import_module=None,
        import_path=None,
        code_directory=None,
        source_root=source_root,
        distribution_location=None,
        install_type="editable",
        git=None,
    )


def _inventory(*records: VersionPackageRecord) -> RuntimeVersionInventory:
    return RuntimeVersionInventory(
        executable="sase",
        python_executable="/venv/bin/python",
        python_version="3.12",
        packages=tuple(records),
    )


def _dev_plan(
    *records: VersionPackageRecord,
    status: str = "actionable",
) -> DevUpdatePlan:
    packages = tuple(
        DevUpdatePackagePlan(
            record=record,
            status=status,  # type: ignore[arg-type]
            reason="behind upstream by 1 commit(s)"
            if status == "actionable"
            else "already current",
            current_version=record.display_version,
            latest_version="0.6.1+2.gbbbbbbbbb",
            git_root=record.source_root,
            upstream="origin/main",
            remote="origin",
            remote_branch="main",
            ahead=0,
            behind=1,
        )
        for record in records
    )
    roots = (
        DevUpdateRootPlan(
            git_root=records[0].source_root or "/home/u/sase",
            status=status,  # type: ignore[arg-type]
            reason="behind upstream by 1 commit(s)",
            upstream="origin/main",
            remote="origin",
            remote_branch="main",
            packages=tuple(record.name for record in records),
            ahead=0,
            behind=1,
        ),
    )
    reconcile = (
        DevReconcileStep(
            kind="uv_tool_install",
            label="Reinstall uv-tool editable Python packages",
            command=("uv", "tool", "install", "--editable", "/home/u/sase"),
        ),
    )
    return DevUpdatePlan(packages=packages, roots=roots, reconcile_steps=reconcile)


def _dev_result(plan: DevUpdatePlan, *, changed: bool = True) -> DevUpdateResult:
    outcomes = tuple(
        DevUpdateOutcome(
            record=package.record,
            status="updated" if package.status == "actionable" else "skipped",
            reason=package.reason,
            old_version=package.current_version,
            new_version=package.latest_version,
            git_root=package.git_root,
        )
        for package in plan.packages
    )
    return DevUpdateResult(
        changed=changed,
        outcomes=outcomes,
        commands=(
            DevExecutedCommand(
                label="Reinstall uv-tool editable Python packages",
                command=("uv", "tool", "install", "--editable", "/home/u/sase"),
                cwd=None,
                returncode=0,
            ),
        )
        if changed
        else (),
    )


# --------------------------------------------------------------------------- #
# Parser
# --------------------------------------------------------------------------- #


def test_update_is_registered_top_level() -> None:
    ns = create_parser().parse_args(["update"])

    assert ns.command == "update"
    assert ns.dry_run is False
    assert ns.json is False
    assert ns.quiet is False


def test_update_accepts_each_flag() -> None:
    short = create_parser().parse_args(["update", "-n", "-j", "-q"])
    long = create_parser().parse_args(["update", "--dry-run", "--json", "--quiet"])

    for ns in (short, long):
        assert ns.dry_run is True
        assert ns.json is True
        assert ns.quiet is True


# --------------------------------------------------------------------------- #
# Detection failure
# --------------------------------------------------------------------------- #


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


def test_not_uv_tool_install_json_error(capsys: Any) -> None:
    code = handle_update_command(_args(json=True), probe_fn=_not_install)

    assert code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema_version"] == UPDATE_JSON_SCHEMA_VERSION
    assert "uv tool" in payload["error"]


# --------------------------------------------------------------------------- #
# Live upgrade flow
# --------------------------------------------------------------------------- #


def test_upgrade_runs_expected_argv_and_renders(tmp_path: Path) -> None:
    seen: dict[str, list[str]] = {}

    def _run(argv: list[str]) -> UvChangeSet:
        seen["argv"] = argv
        return parse_uv_output(_UPGRADE_OUTPUT)

    out = _console()
    code = handle_update_command(
        _args(),
        console=out,
        probe_fn=lambda: _install(tmp_path),
        run_fn=_run,
        axe_running_fn=lambda: False,
        version_fn=_versions,
        clock=lambda: 0.0,
    )

    assert code == 0
    assert seen["argv"] == ["uv", "tool", "upgrade", "--color", "never", "sase"]
    text = _text(out)
    assert "0.5.0 → 0.6.1" in text
    assert "already current" in text
    assert "Updated sase + 1 plugin" in text


def test_upgrade_json_payload_is_stable(tmp_path: Path, capsys: Any) -> None:
    clock = iter([10.0, 14.2])
    code = handle_update_command(
        _args(json=True),
        probe_fn=lambda: _install(tmp_path),
        run_fn=lambda _argv: parse_uv_output(_UPGRADE_OUTPUT),
        axe_running_fn=lambda: False,
        version_fn=_versions,
        clock=lambda: next(clock),
    )

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema_version"] == UPDATE_JSON_SCHEMA_VERSION
    assert payload["dry_run"] is False
    assert payload["changed"] is True
    assert payload["command"] == ["uv", "tool", "upgrade", "--color", "never", "sase"]
    assert payload["elapsed_seconds"] == 4.2
    assert payload["counts"] == {"updated": 2, "already_current": 1, "removed": 0}
    names = [p["name"] for p in payload["packages"]]
    assert names == ["sase", "sase-github", "sase-telegram"]
    sase = payload["packages"][0]
    assert sase["kind"] == "upgraded"
    assert sase["old_version"] == "0.5.0"
    assert sase["new_version"] == "0.6.1"


def test_upgrade_quiet_prints_one_line(tmp_path: Path) -> None:
    out = _console()
    code = handle_update_command(
        _args(quiet=True),
        console=out,
        probe_fn=lambda: _install(tmp_path),
        run_fn=lambda _argv: parse_uv_output(_UPGRADE_OUTPUT),
        axe_running_fn=lambda: False,
        version_fn=_versions,
        clock=lambda: 0.0,
    )

    assert code == 0
    assert _text(out).strip() == "Updated sase + 1 plugin in 0.0s · 1 already current"


def test_managed_upgrade_restarts_axe_when_changed(tmp_path: Path) -> None:
    restart_calls = 0

    def _restart() -> AxeStartResult:
        nonlocal restart_calls
        restart_calls += 1
        return AxeStartResult(status="started", pid=9753)

    out = _console()
    code = handle_update_command(
        _args(),
        console=out,
        probe_fn=lambda: _install(tmp_path),
        run_fn=lambda _argv: parse_uv_output(_UPGRADE_OUTPUT),
        axe_running_fn=lambda: True,
        restart_axe_fn=_restart,
        version_fn=_versions,
        clock=lambda: 0.0,
    )

    assert code == 0
    assert restart_calls == 1
    assert "Axe restarted (pid 9753)" in _text(out)


def test_upgrade_noop_says_up_to_date(tmp_path: Path) -> None:
    out = _console()
    code = handle_update_command(
        _args(),
        console=out,
        probe_fn=lambda: _install(tmp_path),
        run_fn=lambda _argv: parse_uv_output("Nothing to upgrade\n"),
        version_fn=_versions,
        clock=lambda: 0.0,
    )

    assert code == 0
    assert "Already up to date" in _text(out)


def test_upgrade_command_failure_exits_one(tmp_path: Path) -> None:
    def _run(argv: list[str]) -> UvChangeSet:
        raise UvCommandFailedError(argv=argv, returncode=2, stderr="No solution found")

    err = _console()
    code = handle_update_command(
        _args(),
        console=_console(),
        err_console=err,
        probe_fn=lambda: _install(tmp_path),
        run_fn=_run,
        version_fn=_versions,
    )

    assert code == 1
    assert "No solution found" in _text(err)


def test_upgrade_tolerates_missing_receipt(tmp_path: Path) -> None:
    # Receipt missing on disk: the upgrade still succeeds; the render degrades
    # gracefully (no "already current" cross-reference) instead of crashing.
    install = UvToolInstall(
        uv_path="/usr/bin/uv",
        tool_dir=tmp_path,
        sase_dir=tmp_path / "sase",
        receipt_path=tmp_path / "sase" / "uv-receipt.toml",
    )
    out = _console()
    code = handle_update_command(
        _args(),
        console=out,
        probe_fn=lambda: install,
        run_fn=lambda _argv: parse_uv_output(_UPGRADE_OUTPUT),
        axe_running_fn=lambda: False,
        version_fn=_versions,
        clock=lambda: 0.0,
    )

    assert code == 0
    assert "0.5.0 → 0.6.1" in _text(out)


# --------------------------------------------------------------------------- #
# Dev update flow
# --------------------------------------------------------------------------- #


def test_dev_update_runs_backend_and_restarts_axe(tmp_path: Path) -> None:
    host = _record("sase", role="host", source_root="/home/u/sase")
    github = _record("sase-github", role="plugin", source_root="/home/u/sase-github")
    telegram = _record(
        "sase-telegram", role="plugin", source_root="/home/u/sase-telegram"
    )
    seen: dict[str, Any] = {"restart_calls": 0}

    def _run_uv(_argv: list[str]) -> UvChangeSet:
        raise AssertionError("uv tool upgrade must not run for all-editable updates")

    def _plan(
        records: tuple[VersionPackageRecord, ...] | list[VersionPackageRecord],
        *,
        host_record: VersionPackageRecord,
        receipt: Any = None,
    ) -> DevUpdatePlan:
        seen["records"] = [record.name for record in records]
        seen["host"] = host_record.name
        assert receipt is not None
        return _dev_plan(*records)

    def _execute(plan: DevUpdatePlan, *, run: Any) -> DevUpdateResult:
        seen["executed"] = True
        return _dev_result(plan)

    def _restart() -> AxeStartResult:
        seen["restart_calls"] += 1
        return AxeStartResult(status="started", pid=2468)

    clock = iter([0.0, 2.0])
    out = _console()
    code = handle_update_command(
        _args(),
        console=out,
        probe_fn=lambda: _install(tmp_path, _DEV_RECEIPT),
        run_fn=_run_uv,
        inventory_fn=lambda: _inventory(host, github, telegram),
        plan_dev_update_fn=_plan,
        execute_dev_update_fn=_execute,
        axe_running_fn=lambda: True,
        restart_axe_fn=_restart,
        version_fn=_versions,
        clock=lambda: next(clock),
    )

    assert code == 0
    assert seen["records"] == ["sase", "sase-github", "sase-telegram"]
    assert seen["host"] == "sase"
    assert seen["executed"] is True
    assert seen["restart_calls"] == 1
    text = _text(out)
    assert "SASE Dev Update" in text
    assert "0.6.1+1.gaaaaaaaaa → 0.6.1+2.gbbbbbbbbb" in text
    assert "Axe restarted (pid 2468)" in text


def test_dev_update_json_includes_dev_outcomes_and_restart(
    tmp_path: Path, capsys: Any
) -> None:
    host = _record("sase", role="host", source_root="/home/u/sase")

    def _plan(
        records: tuple[VersionPackageRecord, ...] | list[VersionPackageRecord],
        *,
        host_record: VersionPackageRecord,
        receipt: Any = None,
    ) -> DevUpdatePlan:
        return _dev_plan(*records)

    def _execute(plan: DevUpdatePlan, *, run: Any) -> DevUpdateResult:
        return _dev_result(plan)

    code = handle_update_command(
        _args(json=True),
        probe_fn=lambda: _install(tmp_path, _DEV_RECEIPT),
        run_fn=lambda _argv: parse_uv_output("should not run"),
        inventory_fn=lambda: _inventory(host),
        plan_dev_update_fn=_plan,
        execute_dev_update_fn=_execute,
        axe_running_fn=lambda: True,
        restart_axe_fn=lambda: AxeStartResult(status="started", pid=1357),
        version_fn=_versions,
        clock=lambda: 0.0,
    )

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema_version"] == UPDATE_JSON_SCHEMA_VERSION
    assert payload["mode"] == "dev"
    assert payload["command"] == []
    assert payload["changed"] is True
    assert payload["counts"] == {
        "updated": 1,
        "already_current": 0,
        "removed": 0,
        "skipped": 0,
        "failed": 0,
    }
    assert payload["managed"] is None
    assert payload["dev"]["changed"] is True
    assert payload["dev"]["packages"][0]["name"] == "sase"
    assert payload["dev"]["packages"][0]["status"] == "updated"
    assert payload["restart"] == {
        "attempted": True,
        "message": "Axe restarted (pid 1357)",
        "pid": 1357,
        "reason": None,
        "status": "restarted",
    }


def test_dev_update_failure_exits_one_and_does_not_restart(tmp_path: Path) -> None:
    host = _record("sase", role="host", source_root="/home/u/sase")
    restart_calls = 0

    def _plan(
        records: tuple[VersionPackageRecord, ...] | list[VersionPackageRecord],
        *,
        host_record: VersionPackageRecord,
        receipt: Any = None,
    ) -> DevUpdatePlan:
        return _dev_plan(*records)

    def _execute(plan: DevUpdatePlan, *, run: Any) -> DevUpdateResult:
        outcome = DevUpdateOutcome(
            record=plan.packages[0].record,
            status="failed",
            reason="Rebuild sase-core-rs into the uv-tool venv failed",
            old_version=plan.packages[0].current_version,
            new_version=plan.packages[0].latest_version,
            git_root=plan.packages[0].git_root,
        )
        return DevUpdateResult(changed=True, outcomes=(outcome,))

    def _restart() -> AxeStartResult:
        nonlocal restart_calls
        restart_calls += 1
        return AxeStartResult(status="started", pid=1)

    err = _console()
    code = handle_update_command(
        _args(),
        console=_console(),
        err_console=err,
        probe_fn=lambda: _install(tmp_path, _DEV_RECEIPT),
        inventory_fn=lambda: _inventory(host),
        plan_dev_update_fn=_plan,
        execute_dev_update_fn=_execute,
        axe_running_fn=lambda: True,
        restart_axe_fn=_restart,
        version_fn=_versions,
    )

    assert code == 1
    assert restart_calls == 0
    text = _text(err)
    assert "Dev update failed" in text
    assert "uv-tool venv failed" in text


# --------------------------------------------------------------------------- #
# Dry run
# --------------------------------------------------------------------------- #


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


def test_dry_run_json(tmp_path: Path, capsys: Any) -> None:
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
    tmp_path: Path, capsys: Any
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


def test_upgrade_json_counts_exclude_receipt_duplicates(
    tmp_path: Path, capsys: Any
) -> None:
    host = _record("sase", role="host", source_root="/home/u/sase")
    github = _record("sase-github", role="plugin", source_root="/home/u/sase-github")
    telegram = _record(
        "sase-telegram", role="plugin", source_root="/home/u/sase-telegram"
    )

    code = handle_update_command(
        _args(json=True),
        probe_fn=lambda: _install(tmp_path, _DEV_RECEIPT),
        run_fn=lambda _argv: parse_uv_output("should not run"),
        inventory_fn=lambda: _inventory(host, github, telegram),
        plan_dev_update_fn=lambda records, **_kwargs: _dev_plan(*records),
        execute_dev_update_fn=lambda plan, **_kwargs: _dev_result(plan),
        axe_running_fn=lambda: False,
        version_fn=_versions,
        clock=lambda: 0.0,
    )

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    names = [p["name"] for p in payload["dev"]["packages"]]
    assert names == ["sase", "sase-github", "sase-telegram"]
    # Counts reflect unique editable distributions, not the raw duplicated
    # receipt rows.
    assert payload["counts"] == {
        "updated": 3,
        "already_current": 0,
        "removed": 0,
        "skipped": 0,
        "failed": 0,
    }


# --------------------------------------------------------------------------- #
# installed_version helper
# --------------------------------------------------------------------------- #


def test_installed_version_returns_none_for_unknown() -> None:
    assert _installed_version("this-distribution-does-not-exist-xyz") is None


def test_installed_version_returns_value_for_known() -> None:
    # ``rich`` is a hard dependency, so it is always importable here.
    assert _installed_version("rich") is not None
