"""Tests for editable checkout updates handled by the dev-update backend."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from sase.axe.process import AxeStartResult
import sase.dev_update.journal as journal_mod
from sase.dev_update.models import (
    DevCommandResult,
    DevReconcileStep,
    DevUpdateOutcome,
    DevUpdatePackagePlan,
    DevUpdatePlan,
    DevUpdateResult,
)
from sase.main.update_handler import handle_update_command
from sase.uv_tool.errors import UvCommandFailedError
from sase.uv_tool.runner import UvChangeSet, parse_uv_output
from sase.version.inventory import VersionPackageRecord
from tests.main.update_command_helpers import (
    _DEV_RECEIPT,
    _args,
    _console,
    _dev_plan,
    _dev_result,
    _install,
    _inventory,
    _record,
    _text,
    _versions,
)


def test_dev_update_runs_backend_and_restarts_axe(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
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
    journal_path = tmp_path / "dev_update.jsonl"
    monkeypatch.setattr(journal_mod, "DEV_UPDATE_JOURNAL", str(journal_path))
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
    assert "0.6.1+1.gaaaaaaaaa \u2192 0.6.1+2.gbbbbbbbbb" in text
    assert "Axe restarted (pid 2468)" in text
    journal_payload = json.loads(journal_path.read_text(encoding="utf-8"))
    assert journal_payload["result"]["status"] == "updated"
    assert journal_payload["plan"]["packages"][0]["name"] == "sase"


def test_dev_update_json_includes_dev_outcomes_and_restart(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
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
    assert payload["schema_version"] == 2
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
    assert payload["dev"]["plan"]["packages"][0]["status"] == "actionable"
    assert payload["dev"]["plan"]["packages"][0]["latest_version"] == (
        "0.6.1+2.gbbbbbbbbb"
    )
    assert payload["dev"]["plan"]["packages"][0]["fetch_error"] is None
    assert payload["dev"]["plan"]["roots"][0]["fetch_error"] is None
    assert payload["dev"]["plan"]["reconcile_steps"][0]["kind"] == "uv_tool_install"
    assert payload["dev"]["packages"][0]["name"] == "sase"
    assert payload["dev"]["packages"][0]["status"] == "updated"
    assert payload["restart"] == {
        "attempted": True,
        "message": "Axe restarted (pid 1357)",
        "pid": 1357,
        "reason": None,
        "status": "restarted",
    }


def test_dev_update_appends_editable_runtime_core_to_receipt_targets(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    host = _record("sase", role="host", source_root="/home/u/sase")
    core = _record("sase-core-rs", role="core", source_root="/home/u/sase-core")
    github = _record("sase-github", role="plugin", source_root="/home/u/sase-github")
    telegram = _record(
        "sase-telegram", role="plugin", source_root="/home/u/sase-telegram"
    )
    seen: dict[str, list[str]] = {}

    def _plan(
        records: tuple[VersionPackageRecord, ...] | list[VersionPackageRecord],
        *,
        host_record: VersionPackageRecord,
        receipt: Any = None,
    ) -> DevUpdatePlan:
        seen["records"] = [record.name for record in records]
        seen["roles"] = [str(record.role) for record in records]
        assert host_record.name == "sase"
        assert receipt is not None
        return _dev_plan(*records)

    journal_path = tmp_path / "dev_update.jsonl"
    monkeypatch.setattr(journal_mod, "DEV_UPDATE_JOURNAL", str(journal_path))

    code = handle_update_command(
        _args(json=True),
        probe_fn=lambda: _install(tmp_path, _DEV_RECEIPT),
        run_fn=lambda _argv: parse_uv_output("should not run"),
        inventory_fn=lambda: _inventory(host, core, github, telegram),
        plan_dev_update_fn=_plan,
        execute_dev_update_fn=lambda plan, **_kwargs: _dev_result(plan),
        axe_running_fn=lambda: False,
        version_fn=_versions,
        clock=lambda: 0.0,
    )

    assert code == 0
    assert seen["records"] == [
        "sase",
        "sase-github",
        "sase-telegram",
        "sase-core-rs",
    ]
    assert seen["roles"] == ["host", "plugin", "plugin", "core"]

    payload = json.loads(capsys.readouterr().out)
    assert payload["mode"] == "dev"
    assert payload["command"] == []
    assert [package["name"] for package in payload["dev"]["packages"]] == [
        "sase",
        "sase-github",
        "sase-telegram",
        "sase-core-rs",
    ]
    core_package = payload["dev"]["packages"][3]
    assert core_package["role"] == "core"
    assert core_package["status"] == "updated"
    assert payload["counts"] == {
        "updated": 4,
        "already_current": 0,
        "removed": 0,
        "skipped": 0,
        "failed": 0,
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


def test_upgrade_json_counts_exclude_receipt_duplicates(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
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


def test_editable_roots_with_wheel_core_restore_core_via_dev_leg(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A dev install never upgrades sase-core-rs on the managed PyPI leg.

    A wheel-installed core in an editable-host install is a clobbered
    environment: it is handed to the dev-update plan as the stale core so the
    editable build gets restored from the local checkout.
    """
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
    monkeypatch.setattr(
        journal_mod, "DEV_UPDATE_JOURNAL", str(tmp_path / "dev_update.jsonl")
    )
    seen: dict[str, Any] = {}
    restart_calls = 0

    def _plan(
        records: tuple[VersionPackageRecord, ...] | list[VersionPackageRecord],
        **kwargs: Any,
    ) -> DevUpdatePlan:
        seen["records"] = [record.name for record in records]
        seen["stale_core_record"] = kwargs.get("stale_core_record")
        return _dev_plan(*records)

    def _run(_argv: list[str]) -> UvChangeSet:
        raise AssertionError(
            "the managed leg must not run when only sase-core-rs is non-editable"
        )

    def _restart() -> AxeStartResult:
        nonlocal restart_calls
        restart_calls += 1
        return AxeStartResult(status="started", pid=2468)

    code = handle_update_command(
        _args(json=True),
        probe_fn=lambda: _install(tmp_path, _DEV_RECEIPT),
        run_fn=_run,
        inventory_fn=lambda: _inventory(host, core, github, telegram),
        plan_dev_update_fn=_plan,
        execute_dev_update_fn=lambda plan, **_kwargs: _dev_result(plan),
        axe_running_fn=lambda: True,
        restart_axe_fn=_restart,
        version_fn=_versions,
        clock=lambda: 0.0,
    )

    assert code == 0
    assert seen["records"] == ["sase", "sase-github", "sase-telegram"]
    assert seen["stale_core_record"] is core
    assert restart_calls == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["mode"] == "dev"
    assert payload["command"] == []
    assert payload["managed"] is None
    assert payload["changed"] is True


@pytest.mark.parametrize(
    "reason",
    [
        "checkout has local changes",
        "checkout has diverged from upstream",
        "checkout is detached",
        "already current",
        "fetch failed; using cached upstream ref: offline",
    ],
)
def test_skipped_editable_states_do_not_block_stale_core_restore(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    reason: str,
) -> None:
    """Skipped checkouts still let the dev leg rebuild a wheel-installed core."""
    host = _record("sase", role="host", source_root="/home/u/sase")
    core = _record(
        "sase-core-rs",
        role="core",
        source_root=None,
        display_version="0.4.0",
        distribution_version="0.4.0",
        install_type="wheel",
    )
    base = _dev_plan(host, status="skipped")
    core_restore = DevUpdatePackagePlan(
        record=core,
        status="actionable",
        reason=(
            "installed sase-core-rs is a published wheel; dev installs use "
            "the editable build from the local checkout"
        ),
        current_version="0.4.0",
        latest_version="0.6.1",
    )
    rust_step = DevReconcileStep(
        kind="rust_install_uv_tool",
        label="Rebuild sase-core-rs into the uv-tool venv",
        command=("just", "rust-install-uv-tool"),
        cwd="/home/u/sase",
    )
    plan = replace(
        base,
        packages=(replace(base.packages[0], reason=reason), core_restore),
        roots=(replace(base.roots[0], reason=reason),),
        reconcile_steps=(rust_step,),
    )
    monkeypatch.setattr(
        journal_mod, "DEV_UPDATE_JOURNAL", str(tmp_path / "dev_update.jsonl")
    )
    reconcile_commands: list[tuple[str, ...]] = []

    def _run_command(argv: Any, *, cwd: Any = None) -> DevCommandResult:
        reconcile_commands.append(tuple(argv))
        return DevCommandResult(returncode=0)

    code = handle_update_command(
        _args(),
        console=_console(),
        probe_fn=lambda: _install(tmp_path, _DEV_RECEIPT),
        run_fn=lambda _argv: pytest.fail(
            "a dev install must not upgrade sase-core-rs on the managed leg"
        ),
        inventory_fn=lambda: _inventory(host, core),
        plan_dev_update_fn=lambda _records, **_kwargs: plan,
        run_dev_update_fn=_run_command,
        axe_running_fn=lambda: False,
        version_fn=_versions,
        clock=lambda: 0.0,
    )

    assert code == 0
    assert reconcile_commands == [("just", "rust-install-uv-tool")]


def test_managed_core_failure_is_not_success_and_does_not_restart(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A published host keeps sase-core-rs on the managed leg, which can fail."""
    github_root = tmp_path / "sase-github"
    github_root.mkdir()
    mixed_receipt = f"""
    [tool]
    requirements = [
        {{ name = "sase" }},
        {{ name = "sase-github", editable = "{github_root}" }},
    ]
    """
    host = _record("sase", role="host", source_root=None, install_type="wheel")
    github = _record("sase-github", role="plugin", source_root=str(github_root))
    core = _record(
        "sase-core-rs",
        role="core",
        source_root=None,
        display_version="0.4.0",
        distribution_version="0.4.0",
        install_type="wheel",
    )
    monkeypatch.setattr(
        journal_mod, "DEV_UPDATE_JOURNAL", str(tmp_path / "dev_update.jsonl")
    )
    restart_calls = 0

    def _run(argv: list[str]) -> UvChangeSet:
        assert argv[-2:] == ["--upgrade-package", "sase-core-rs"]
        raise UvCommandFailedError(argv=argv, returncode=2, stderr="core conflict")

    def _restart() -> AxeStartResult:
        nonlocal restart_calls
        restart_calls += 1
        return AxeStartResult(status="started", pid=1)

    plan = _dev_plan(github, status="skipped")
    err = _console()
    code = handle_update_command(
        _args(),
        console=_console(),
        err_console=err,
        probe_fn=lambda: _install(tmp_path, mixed_receipt),
        run_fn=_run,
        inventory_fn=lambda: _inventory(host, core, github),
        plan_dev_update_fn=lambda _records, **_kwargs: plan,
        axe_running_fn=lambda: True,
        restart_axe_fn=_restart,
        version_fn=_versions,
    )

    assert code == 1
    assert restart_calls == 0
    assert "core conflict" in _text(err)
