from __future__ import annotations

import argparse
import io
from pathlib import Path

from rich.console import Console

from sase.dev_update.models import (
    DevExecutedCommand,
    DevReconcileStep,
    DevUpdateOutcome,
    DevUpdatePackagePlan,
    DevUpdatePlan,
    DevUpdateResult,
    DevUpdateRootPlan,
)
from sase.uv_tool.detect import NotUvToolInstall, NotUvToolReason, UvToolInstall
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


def _args(
    *,
    json: bool = False,
    dry_run: bool = False,
    quiet: bool = False,
    to: str | None = None,
    yes: bool = False,
) -> argparse.Namespace:
    return argparse.Namespace(json=json, dry_run=dry_run, quiet=quiet, to=to, yes=yes)


def _console() -> Console:
    return Console(file=io.StringIO(), width=200, no_color=True)


def _text(console: Console) -> str:
    return console.file.getvalue()  # type: ignore[attr-defined]


def _versions(name: str) -> str | None:
    return {
        "sase": "0.6.1",
        "sase-core-rs": "0.4.0",
        "sase-github": "0.4.0",
        "sase-telegram": "0.1.0",
    }.get(name)


def _record(
    name: str,
    *,
    role: str,
    source_root: str | None,
    display_version: str = "0.6.1+1.gaaaaaaaaa",
    distribution_version: str = "0.6.1",
    install_type: str = "editable",
) -> VersionPackageRecord:
    return VersionPackageRecord(
        name=name,
        role=role,  # type: ignore[arg-type]
        display_version=display_version,
        distribution_version=distribution_version,
        source_version="0.6.1",
        import_module=None,
        import_path=None,
        code_directory=None,
        source_root=source_root,
        distribution_location=None,
        install_type=install_type,  # type: ignore[arg-type]
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
