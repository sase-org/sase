"""Shared fixture-repository helpers for bead conflict resolver tests."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from sase.bead.config import save_config
from sase.bead.model import IssueType
from sase.bead.project import BEADS_DIRNAME, BEADS_DIRNAME_ROOT, BeadProject
from sase.bead_pages.paths import bead_page_path


def _git(cwd: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=check,
    )


def _init_repo(repo: Path) -> None:
    _git(repo, "init", "--initial-branch=master")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test User")


def _assert_config_roundtrips_save_config(beads_dir: Path, tmp_path: Path) -> None:
    parsed = json.loads((beads_dir / "config.json").read_text(encoding="utf-8"))
    roundtrip_dir = tmp_path / "_save_config_roundtrip"
    roundtrip_dir.mkdir(exist_ok=True)
    save_config(roundtrip_dir, parsed)
    assert (beads_dir / "config.json").read_bytes() == (
        roundtrip_dir / "config.json"
    ).read_bytes()


def _build_stream_conflict(
    repo: Path,
    *,
    bystanders: int = 0,
    bystander_label: str = "Quiet",
    beads_dirname: str = BEADS_DIRNAME,
    legacy_notes: str | None = None,
) -> tuple[str, list[str]]:
    """Diverge one bead event stream, leaving *bystanders* streams untouched."""
    _init_repo(repo)
    if beads_dirname == BEADS_DIRNAME_ROOT:
        (repo / ".gitignore").write_text(
            "beads.db\nbeads.db-shm\nbeads.db-wal\n",
            encoding="utf-8",
        )
    with BeadProject.init(repo, beads_dirname=beads_dirname) as project:
        quiet = [
            project.create(f"{bystander_label} {index}", IssueType.PLAN).id
            for index in range(bystanders)
        ]
        contested = project.create("Contested", IssueType.PLAN).id
    if legacy_notes is not None:
        _inject_legacy_notes(repo, beads_dirname, contested, legacy_notes)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "base")

    _git(repo, "checkout", "-b", "other")
    with BeadProject(repo, beads_dirname=beads_dirname) as project:
        project.update(contested, notes="from other")
    _git(repo, "commit", "-am", "other")

    _git(repo, "checkout", "master")
    with BeadProject(repo, beads_dirname=beads_dirname) as project:
        project.update(contested, design="from local")
    _git(repo, "commit", "-am", "local")

    _git(repo, "merge", "other", check=False)
    prefix = "" if beads_dirname == BEADS_DIRNAME_ROOT else f"{beads_dirname}/"
    return f"{prefix}events/streams/{contested}.jsonl", quiet


def _inject_legacy_notes(
    repo: Path,
    beads_dirname: str,
    issue_id: str,
    notes: str,
) -> None:
    stream = repo / beads_dirname / "events" / "streams" / f"{issue_id}.jsonl"
    events = [
        json.loads(line)
        for line in stream.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(events) == 1
    issue = events[0]["payload"]["issue"]
    assert "notes" not in issue
    issue["notes"] = notes
    stream.write_text(
        "".join(
            json.dumps(event, separators=(",", ":"), ensure_ascii=False) + "\n"
            for event in events
        ),
        encoding="utf-8",
    )


def _build_root_store_conflict(repo: Path, *, conflict_stream: bool) -> str:
    """Diverge README plus, optionally, one root-store event stream."""
    _init_repo(repo)
    (repo / ".gitignore").write_text(
        "beads.db\nbeads.db-shm\nbeads.db-wal\n",
        encoding="utf-8",
    )
    with BeadProject.init(repo, beads_dirname=BEADS_DIRNAME_ROOT) as project:
        issue = project.create("Contested", IssueType.PLAN)
    readme = repo / "README.md"
    readme.write_text("base\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "base")

    _git(repo, "checkout", "-b", "other")
    if conflict_stream:
        with BeadProject(repo, beads_dirname=BEADS_DIRNAME_ROOT) as project:
            project.update(issue.id, notes="from other")
    readme.write_text("other\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "other")

    _git(repo, "checkout", "master")
    if conflict_stream:
        with BeadProject(repo, beads_dirname=BEADS_DIRNAME_ROOT) as project:
            project.update(issue.id, design="from local")
    readme.write_text("local\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "local")
    _git(repo, "merge", "other", check=False)
    return issue.id


def _build_root_page_conflict(repo: Path, *, upstream_deletes: bool = False) -> str:
    _init_repo(repo)
    (repo / ".gitignore").write_text(
        "beads.db\nbeads.db-shm\nbeads.db-wal\n",
        encoding="utf-8",
    )
    with BeadProject.init(repo, beads_dirname=BEADS_DIRNAME_ROOT):
        pass
    page = bead_page_path("sase-ai")
    page_path = repo / page
    page_path.parent.mkdir(parents=True)
    page_path.write_text("base\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "base")

    _git(repo, "checkout", "-b", "other")
    if upstream_deletes:
        _git(repo, "rm", page)
    else:
        page_path.write_text("upstream\n", encoding="utf-8")
    _git(repo, "commit", "-am", "other")

    _git(repo, "checkout", "master")
    page_path.write_text("local\n", encoding="utf-8")
    _git(repo, "commit", "-am", "local")
    _git(repo, "merge", "other", check=False)
    return page


def _build_root_store_and_page_conflict(repo: Path) -> tuple[str, str]:
    _init_repo(repo)
    (repo / ".gitignore").write_text(
        "beads.db\nbeads.db-shm\nbeads.db-wal\n",
        encoding="utf-8",
    )
    with BeadProject.init(repo, beads_dirname=BEADS_DIRNAME_ROOT) as project:
        issue = project.create("Contested", IssueType.PLAN)
    page = bead_page_path(issue.id)
    page_path = repo / page
    page_path.parent.mkdir(parents=True)
    page_path.write_text("base\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "base")

    _git(repo, "checkout", "-b", "other")
    with BeadProject(repo, beads_dirname=BEADS_DIRNAME_ROOT) as project:
        project.update(issue.id, notes="from upstream")
    page_path.write_text("upstream\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "other")

    _git(repo, "checkout", "master")
    with BeadProject(repo, beads_dirname=BEADS_DIRNAME_ROOT) as project:
        project.update(issue.id, design="from local")
    page_path.write_text("local\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "local")
    _git(repo, "merge", "other", check=False)
    return f"events/streams/{issue.id}.jsonl", page
