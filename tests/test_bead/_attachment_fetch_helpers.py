"""Shared fixtures and CLI drivers for attachment-fetch tests.

Split from ``tests.test_bead.test_attachment_fetch``; the original module
re-exports its tests so its import path keeps working.

Not a conftest so files opt in by importing the helpers directly. Names are
public so the ``test_attachment_fetch_*`` split modules can share them
without importing ``_``-prefixed names across files.
"""

from __future__ import annotations

import io
import subprocess
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import pytest

from sase.bead import cli as bead_cli
from sase.bead.model import IssueType
from sase.bead.project import BeadProject
from sase.main.parser import create_parser

_HANDLERS = {
    "note": bead_cli.handle_bead_note,
    "attach": bead_cli.handle_bead_attach,
    "attachment": bead_cli.handle_bead_attachment,
    "show": bead_cli.handle_bead_show,
    "read": bead_cli.handle_bead_read,
}

GIT_TIMEOUT = 60.0


def run_git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
        timeout=GIT_TIMEOUT,
    )


def run_cli(argv: list[str]) -> tuple[str, str, int]:
    args = create_parser().parse_args(["bead", *argv])
    handler = _HANDLERS[args.bead_subcommand]
    out, err, code = io.StringIO(), io.StringIO(), 0
    try:
        with redirect_stdout(out), redirect_stderr(err):
            handler(args)
    except SystemExit as exc:
        code = int(exc.code or 0)
    return out.getvalue(), err.getvalue(), code


@pytest.fixture(name="work_dir")
def fetch_work_dir(
    project_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Path:
    """Isolate the CAS home and resolve ``@./`` refs inside the project."""
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "sase-home-a"))
    monkeypatch.chdir(project_dir)
    return project_dir


@pytest.fixture(name="remote")
def fetch_remote(tmp_path: Path) -> Path:
    path = tmp_path / "remote.git"
    run_git(tmp_path, "init", "--bare", "-b", "main", path.name)
    run_git(path, "config", "uploadpack.allowFilter", "true")
    run_git(path, "config", "uploadpack.allowAnySHA1InWant", "true")
    return path


def plant_hidden_clone(home: Path, remote: Path) -> Path:
    """Clone the shared remote into one home's hidden attachments-private slot."""
    from sase.core.paths import sase_projects_dir

    clone = sase_projects_dir() / "test-project" / "repos" / "attachments-private"
    clone.parent.mkdir(parents=True, exist_ok=True)
    if clone.exists():
        return clone
    run_git(
        home,
        "clone",
        "--bare",
        "--filter=blob:none",
        f"file://{remote}",
        str(clone),
    )
    return clone


def use_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, name: str) -> Path:
    home = tmp_path / name
    home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("SASE_HOME", str(home))
    return home


def create_plan(project_dir: Path) -> str:
    with BeadProject(project_dir) as project:
        issue = project.create("Fetch target", IssueType.PLAN)
    return issue.id


def note_with_file(
    project_dir: Path, work_dir: Path, issue_id: str, filename: str, data: bytes
) -> str:
    (work_dir / filename).write_bytes(data)
    # -K pins the private audience: these tests exercise the private store,
    # while a clean workspace file would otherwise resolve public.
    out, err, code = run_cli(["note", issue_id, "-K", f"see @./{filename}"])
    assert code == 0, err
    with BeadProject(project_dir) as project:
        note = project.show(issue_id).notes[-1]
    assert note.attachments
    return note.attachments[-1].sha256


def read_full(issue_id: str, *extra: str) -> tuple[str, str, int]:
    return run_cli(
        [
            "read",
            issue_id,
            "--no-links",
            "--pager",
            "never",
            "--color",
            "never",
            "-r",
            "Need the attachment",
            *extra,
        ]
    )
