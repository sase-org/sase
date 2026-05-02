"""Golden CLI contract tests for ``sase bead``.

These fixtures pin the current public text contract before the bead backend
moves into ``sase-core``. The expected files intentionally live on disk so the
Rust phases can reuse them without importing Python test helpers.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

from sase.bead.config import save_config
from sase.bead.project import BeadProject
from sase.main.entry import main as sase_main

GOLDEN = Path(__file__).parent / "golden"


@dataclass(frozen=True)
class CliResult:
    code: int
    stdout: str
    stderr: str


@dataclass(frozen=True)
class CliCase:
    name: str
    argv: list[str]
    setup: str
    code: int = 0
    stdout: str = ""
    stderr: str = ""


def _read_expected(name: str) -> str:
    text = (GOLDEN / "cli" / name).read_text(encoding="utf-8")
    return text if text.endswith("\n") else text + "\n"


def _project_root(tmp_path: Path, name: str) -> Path:
    root = tmp_path / name
    root.mkdir()
    (root / "plans").mkdir()
    for plan in ("alpha.md", "beta.md", "gamma.md", "cross.md", "new.md"):
        (root / "plans" / plan).write_text(f"# {plan}\n", encoding="utf-8")
    return root


def _copy_current_store(root: Path) -> None:
    shutil.copytree(GOLDEN / "stores" / "current", root / "sdd/beads")


def _init_empty_store(root: Path, *, prefix: str = "case") -> None:
    with BeadProject.init(root):
        pass
    save_config(
        root / "sdd/beads",
        {"issue_prefix": prefix, "next_counter": 1, "owner": ""},
    )


def _init_git_repo(root: Path) -> None:
    subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=root,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=root,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "add", "sdd/beads/issues.jsonl"],
        cwd=root,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "add beads"],
        cwd=root,
        check=True,
        capture_output=True,
    )


def _setup_case(tmp_path: Path, setup: str) -> Path:
    root = _project_root(tmp_path, setup)
    if setup == "empty":
        return root
    if setup == "initialized":
        _init_empty_store(root)
        return root
    _copy_current_store(root)
    if setup == "current_git":
        _init_git_repo(root)
    return root


def _run_cli(
    argv: list[str],
    *,
    cwd: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> CliResult:
    monkeypatch.chdir(cwd)
    monkeypatch.setattr(sys, "argv", ["sase", *argv])
    monkeypatch.setattr("sase.bead.workspace.resolve_primary_workspace", lambda: None)

    with pytest.raises(SystemExit) as excinfo:
        sase_main()

    captured = capsys.readouterr()
    code = int(excinfo.value.code or 0)
    return CliResult(
        code=code,
        stdout=captured.out.replace(str(cwd), "<ROOT>"),
        stderr=captured.err.replace(str(cwd), "<ROOT>"),
    )


@pytest.mark.parametrize(
    "case",
    [
        CliCase(
            "init",
            ["bead", "init"],
            "empty",
            stdout=_read_expected("init.stdout"),
        ),
        CliCase(
            "create",
            [
                "bead",
                "create",
                "--title",
                "Created Epic",
                "--type",
                "plan(plans/new.md)",
                "--description",
                "Created description",
                "--assignee",
                "bob",
                "--changespec",
                "created_epic",
                "--bug-id",
                "BUG-9",
            ],
            "initialized",
            stdout=_read_expected("create.stdout"),
        ),
        CliCase(
            "list",
            ["bead", "list"],
            "current",
            stdout=_read_expected("list.stdout"),
        ),
        CliCase(
            "show",
            ["bead", "show", "beads-1"],
            "current",
            stdout=_read_expected("show.stdout"),
        ),
        CliCase(
            "ready",
            ["bead", "ready"],
            "current",
            stdout=_read_expected("ready.stdout"),
        ),
        CliCase(
            "blocked",
            ["bead", "blocked"],
            "current",
            stdout=_read_expected("blocked.stdout"),
        ),
        CliCase(
            "stats",
            ["bead", "stats"],
            "current",
            stdout=_read_expected("stats.stdout"),
        ),
        CliCase(
            "dep_add",
            ["bead", "dep", "add", "beads-4", "beads-1"],
            "current",
            stdout=_read_expected("dep_add.stdout"),
        ),
        CliCase(
            "update",
            ["bead", "update", "beads-1.1", "--title", "Build Alpha Updated"],
            "current",
            stdout=_read_expected("update.stdout"),
        ),
        CliCase(
            "open",
            ["bead", "open", "beads-3"],
            "current",
            stdout=_read_expected("open.stdout"),
        ),
        CliCase(
            "close",
            ["bead", "close", "beads-1.1"],
            "current",
            stdout=_read_expected("close.stdout"),
        ),
        CliCase(
            "rm",
            ["bead", "rm", "beads-1.2"],
            "current",
            stdout=_read_expected("rm.stdout"),
        ),
        CliCase(
            "sync_status",
            ["bead", "sync", "--status"],
            "current_git",
            stdout=_read_expected("sync_status.stdout"),
        ),
        CliCase(
            "show_missing",
            ["bead", "show", "beads-missing"],
            "current",
            code=1,
            stderr=_read_expected("show_missing.stderr"),
        ),
        CliCase(
            "create_invalid_type",
            ["bead", "create", "--title", "Bad", "--type", "bogus"],
            "initialized",
            code=1,
            stderr=_read_expected("create_invalid_type.stderr"),
        ),
        CliCase(
            "create_missing_parent",
            [
                "bead",
                "create",
                "--title",
                "Orphan",
                "--type",
                "phase(beads-missing)",
            ],
            "current",
            code=1,
            stderr=_read_expected("create_missing_parent.stderr"),
        ),
    ],
    ids=lambda case: case.name,
)
def test_bead_cli_golden_contract(
    case: CliCase,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = _setup_case(tmp_path, case.setup)

    result = _run_cli(case.argv, cwd=root, monkeypatch=monkeypatch, capsys=capsys)

    assert result.code == case.code
    assert result.stdout == case.stdout
    assert result.stderr == case.stderr
