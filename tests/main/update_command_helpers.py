from __future__ import annotations

import argparse
import io
import re
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
    bin_dir = sase_dir / "bin"
    bin_dir.mkdir(exist_ok=True)
    executable = bin_dir / "sase"
    executable.write_text(
        "#!/usr/bin/env python3\n"
        "import json\n"
        "print(json.dumps({'attempted': True, 'shells': []}))\n",
        encoding="utf-8",
    )
    executable.chmod(0o755)
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
    verbose: bool = False,
) -> argparse.Namespace:
    return argparse.Namespace(
        json=json, dry_run=dry_run, quiet=quiet, to=to, yes=yes, verbose=verbose
    )


def _console() -> Console:
    return Console(file=io.StringIO(), width=200, no_color=True)


def _text(console: Console) -> str:
    return console.file.getvalue()  # type: ignore[attr-defined]


class _TickingClock:
    """Manually advanced clock giving steps nonzero durations."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _shared_terminal(width: int = 80) -> tuple[io.StringIO, Console, Console]:
    """Build ``out`` and ``err`` consoles on one shared terminal stream."""
    stream = io.StringIO()
    out = Console(file=stream, width=width, force_terminal=True)
    err = Console(file=stream, width=width, force_terminal=True)
    return stream, out, err


_LIVE_SEQUENCES = (
    "\x1b[1A",
    "\x1b[A",
    "\x1b[2K",
    "\x1b[K",
    "\x1b[G",
    "\x1b[H",
    "\x1b[2J",
    "\x1b[?25l",
    "\x1b[?25h",
)
"""Cursor-movement and erase sequences a torn-down Live region never emits."""

_SGR_RE = re.compile(r"\x1b\[[0-9;]*m")
"""SGR color sequences: stripped for marker matching, never asserted on."""


def _assert_quiet_after(stream: io.StringIO, marker: str) -> str:
    """Return the text after *marker*; fail on Live sequences following it.

    SGR color codes are stripped first (rich interleaves them inside panel
    words), but cursor-movement and erase sequences survive the strip, so a
    live region still drawing after the marker is caught.
    """
    text = _SGR_RE.sub("", stream.getvalue())
    assert marker in text, f"{marker!r} missing from shared terminal output"
    tail = text.split(marker, 1)[1]
    for sequence in _LIVE_SEQUENCES:
        assert sequence not in tail, (
            f"{sequence!r} follows the stdout panel: the live region "
            "was still running when stdout printed"
        )
    return text


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
