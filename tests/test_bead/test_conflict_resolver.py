"""Tests for bead conflict resolver command behavior."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from sase.bead._stream_integrity import prepare_event_streams_for_commit
from sase.bead import conflict_resolver
from sase.bead.conflict_resolver import _git_add, resolve_bead_conflicts
from sase.bead.model import IssueType
from sase.bead.project import BEADS_DIRNAME, BEADS_DIRNAME_ROOT, BeadProject
from sase.bead_pages.paths import bead_page_path
from sase.core import bead_mutation_facade


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


def test_resolve_bead_conflicts_noops_without_conflicts(tmp_path: Path) -> None:
    _init_repo(tmp_path)

    result = resolve_bead_conflicts(tmp_path)

    assert result.ok is True
    assert result.message == "no conflicted bead files"


def test_git_add_recovers_stale_index_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _init_repo(tmp_path)
    note = tmp_path / "note.txt"
    note.write_text("resolved\n", encoding="utf-8")
    lock = tmp_path / ".git" / "index.lock"
    lock.write_text("stale", encoding="utf-8")
    monkeypatch.setenv("SASE_GIT_LOCK_RETRY_DELAYS", "0.001,0.001")

    _git_add(tmp_path, ["note.txt"])

    assert not lock.exists()
    assert _git(tmp_path, "diff", "--cached", "--name-only").stdout.strip() == (
        "note.txt"
    )


def test_resolve_bead_conflicts_rejects_nonmergeable_bead_file(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    config = tmp_path / "sdd/beads/config.json"
    config.parent.mkdir(parents=True)
    config.write_text('{"owner":"base"}\n', encoding="utf-8")
    _git(tmp_path, "add", "sdd/beads/config.json")
    _git(tmp_path, "commit", "-m", "base")
    _git(tmp_path, "checkout", "-b", "other")
    config.write_text('{"owner":"other"}\n', encoding="utf-8")
    _git(tmp_path, "commit", "-am", "other")
    _git(tmp_path, "checkout", "master")
    config.write_text('{"owner":"local"}\n', encoding="utf-8")
    _git(tmp_path, "commit", "-am", "local")
    _git(tmp_path, "merge", "other", check=False)

    result = resolve_bead_conflicts(tmp_path)

    assert result.ok is False
    assert result.message == "unsupported bead conflicts: sdd/beads/config.json"


def test_resolve_bead_conflicts_rejects_only_non_bead_conflicts(
    tmp_path: Path,
) -> None:
    _init_repo(tmp_path)
    (tmp_path / "sdd/beads").mkdir(parents=True)
    notes = tmp_path / "notes.txt"
    notes.write_text("base\n", encoding="utf-8")
    _git(tmp_path, "add", "notes.txt")
    _git(tmp_path, "commit", "-m", "base")
    _git(tmp_path, "checkout", "-b", "other")
    notes.write_text("other\n", encoding="utf-8")
    _git(tmp_path, "commit", "-am", "other")
    _git(tmp_path, "checkout", "master")
    notes.write_text("local\n", encoding="utf-8")
    _git(tmp_path, "commit", "-am", "local")
    _git(tmp_path, "merge", "other", check=False)

    result = resolve_bead_conflicts(tmp_path)

    assert result.ok is False
    assert result.message == "non-bead conflicts remain: notes.txt"


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


def test_root_store_event_stream_conflict_is_mergeable(tmp_path: Path) -> None:
    contested, _quiet = _build_stream_conflict(
        tmp_path,
        beads_dirname=BEADS_DIRNAME_ROOT,
    )

    result = resolve_bead_conflicts(tmp_path, beads_dir=tmp_path)

    assert result.ok is True, result.message
    assert contested in result.resolved_files
    assert "events/manifest.json" in result.resolved_files
    assert "issues.jsonl" in result.resolved_files


def test_root_store_page_only_conflict_takes_upstream_without_store_merge(
    tmp_path: Path,
) -> None:
    page = _build_root_page_conflict(tmp_path)

    result = resolve_bead_conflicts(tmp_path, beads_dir=tmp_path)

    assert result.ok is True, result.message
    assert result.resolved_files == (page,)
    assert (tmp_path / page).read_text(encoding="utf-8") == "upstream\n"
    assert _git(tmp_path, "diff", "--name-only", "--diff-filter=U").stdout == ""
    assert _git(tmp_path, "diff", "--cached", "--name-only").stdout.split() == [page]


def test_root_store_page_conflict_accepts_upstream_deletion(
    tmp_path: Path,
) -> None:
    page = _build_root_page_conflict(tmp_path, upstream_deletes=True)

    result = resolve_bead_conflicts(tmp_path, beads_dir=tmp_path)

    assert result.ok is True, result.message
    assert result.resolved_files == (page,)
    assert not (tmp_path / page).exists()
    assert _git(tmp_path, "diff", "--name-only", "--diff-filter=U").stdout == ""
    assert _git(tmp_path, "diff", "--cached", "--name-status").stdout == (
        f"D\t{page}\n"
    )


def test_root_store_mixed_page_and_store_conflicts_resolve(
    tmp_path: Path,
) -> None:
    contested, page = _build_root_store_and_page_conflict(tmp_path)

    result = resolve_bead_conflicts(tmp_path, beads_dir=tmp_path)

    assert result.ok is True, result.message
    assert set(result.resolved_files) == {
        contested,
        "events/manifest.json",
        "issues.jsonl",
        page,
    }
    assert (tmp_path / page).read_text(encoding="utf-8") == "upstream\n"
    assert _git(tmp_path, "diff", "--name-only", "--diff-filter=U").stdout == ""
    merged = (tmp_path / contested).read_text(encoding="utf-8")
    assert "from local" in merged and "from upstream" in merged


def test_root_store_readme_conflict_is_not_a_bead_conflict(tmp_path: Path) -> None:
    _build_root_store_conflict(tmp_path, conflict_stream=False)

    result = resolve_bead_conflicts(tmp_path, beads_dir=tmp_path)

    assert result.ok is False
    assert result.message == "non-bead conflicts remain: README.md"


def test_root_store_mixed_conflicts_are_refused(tmp_path: Path) -> None:
    issue_id = _build_root_store_conflict(tmp_path, conflict_stream=True)

    result = resolve_bead_conflicts(tmp_path, beads_dir=tmp_path)

    assert result.ok is False
    assert result.message == "non-bead conflicts remain: README.md"
    assert f"events/streams/{issue_id}.jsonl" not in result.resolved_files


def test_prefixed_store_page_conflict_is_still_unsupported(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    with BeadProject.init(tmp_path, beads_dirname=BEADS_DIRNAME):
        pass
    page = f"{BEADS_DIRNAME}/{bead_page_path('sase-ai')}"
    page_path = tmp_path / page
    page_path.parent.mkdir(parents=True)
    page_path.write_text("base\n", encoding="utf-8")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-m", "base")

    _git(tmp_path, "checkout", "-b", "other")
    page_path.write_text("upstream\n", encoding="utf-8")
    _git(tmp_path, "commit", "-am", "other")
    _git(tmp_path, "checkout", "master")
    page_path.write_text("local\n", encoding="utf-8")
    _git(tmp_path, "commit", "-am", "local")
    _git(tmp_path, "merge", "other", check=False)

    result = resolve_bead_conflicts(tmp_path, beads_dir=tmp_path / BEADS_DIRNAME)

    assert result.ok is False
    assert result.message == f"unsupported bead conflicts: {page}"


def test_failed_conflict_probe_is_not_reported_as_clean(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _init_repo(tmp_path)
    real_run_git = conflict_resolver._run_git

    def fail_conflict_probe(
        cwd: Path, args: list[str]
    ) -> subprocess.CompletedProcess[str]:
        if args[:1] == ["diff"]:
            return subprocess.CompletedProcess(
                ["git", *args],
                128,
                stdout="",
                stderr="fatal: Unable to create '.git/index.lock': File exists.",
            )
        return real_run_git(cwd, args)

    monkeypatch.setattr(conflict_resolver, "_run_git", fail_conflict_probe)

    result = resolve_bead_conflicts(tmp_path)

    assert result.ok is False
    assert "could not list conflicted bead files" in result.message
    assert result.resolved_files == ()


def test_conflict_probe_retries_through_a_stale_index_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The probes contend on index.lock, so they use the shared retry policy."""
    contested, _quiet = _build_stream_conflict(tmp_path)
    monkeypatch.setenv("SASE_GIT_LOCK_RETRY_DELAYS", "0.001,0.001")
    lock = tmp_path / ".git" / "index.lock"
    lock.write_text("stale", encoding="utf-8")

    result = resolve_bead_conflicts(tmp_path, beads_dir=tmp_path / BEADS_DIRNAME)

    assert result.ok is True, result.message
    assert contested in result.resolved_files
    assert not lock.exists()


def test_resolution_leaves_untouched_streams_alone(tmp_path: Path) -> None:
    contested, quiet = _build_stream_conflict(tmp_path, bystanders=3)
    streams = tmp_path / BEADS_DIRNAME / "events" / "streams"
    quiet_paths = [streams / f"{stream_id}.jsonl" for stream_id in quiet]
    quiet_mtimes = {path: path.stat().st_mtime_ns for path in quiet_paths}

    result = resolve_bead_conflicts(tmp_path, beads_dir=tmp_path / BEADS_DIRNAME)

    assert result.ok is True, result.message
    assert set(result.resolved_files) == {
        contested,
        f"{BEADS_DIRNAME}/events/manifest.json",
        f"{BEADS_DIRNAME}/issues.jsonl",
    }
    assert {path: path.stat().st_mtime_ns for path in quiet_paths} == quiet_mtimes
    staged = _git(tmp_path, "diff", "--cached", "--name-only").stdout.split()
    assert not [path for path in staged if any(name in path for name in quiet)]
    merged = (tmp_path / contested).read_text(encoding="utf-8")
    assert "from local" in merged and "from other" in merged


def test_duplicate_top_level_creations_report_typed_relocation(
    tmp_path: Path,
) -> None:
    _init_repo(tmp_path)
    (tmp_path / ".gitignore").write_text("beads/beads.db*\n", encoding="utf-8")
    with BeadProject.init(tmp_path, beads_dirname=BEADS_DIRNAME):
        pass
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-m", "seed empty bead store")

    _git(tmp_path, "checkout", "-b", "other")
    upstream, _ = bead_mutation_facade.create(
        tmp_path / BEADS_DIRNAME,
        title="Upstream wins",
        issue_type=IssueType.PLAN,
        now="2026-08-20T00:00:00Z",
    )
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-m", f"other creates {upstream.id}")

    _git(tmp_path, "checkout", "master")
    local, _ = bead_mutation_facade.create(
        tmp_path / BEADS_DIRNAME,
        title="Local relocates",
        issue_type=IssueType.PLAN,
        now="2026-08-20T00:00:01Z",
    )
    assert local.id == upstream.id
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-m", f"local creates {local.id}")
    _git(tmp_path, "merge", "other", check=False)

    result = resolve_bead_conflicts(tmp_path, beads_dir=tmp_path / BEADS_DIRNAME)

    assert result.ok is True, result.message
    assert len(result.bead_relocations) == 1
    relocation = result.bead_relocations[0]
    assert relocation.old_id == local.id
    assert relocation.new_id == f"{local.id.rsplit('-', 1)[0]}-2"
    assert relocation.kind == "top_level_duplicate"
    assert f"{relocation.old_id} -> {relocation.new_id}" in result.message
    relocated_stream = (
        tmp_path / BEADS_DIRNAME / "events" / "streams" / f"{relocation.new_id}.jsonl"
    ).read_text(encoding="utf-8")
    assert f'"issue_id":"{relocation.old_id}"' not in relocated_stream
    assert f'"issue_id":"{relocation.new_id}"' in relocated_stream
    with BeadProject(tmp_path, beads_dirname=BEADS_DIRNAME) as project:
        assert project.show(upstream.id).title == "Upstream wins"
        assert project.show(relocation.new_id).title == "Local relocates"


def test_resolution_preserves_non_ascii_bytes_in_untouched_streams(
    tmp_path: Path,
) -> None:
    """The Rust writer emits unescaped UTF-8; escaping it here churns every file."""
    _contested, quiet = _build_stream_conflict(
        tmp_path, bystanders=2, bystander_label="Quiét — ünicode"
    )
    streams = tmp_path / BEADS_DIRNAME / "events" / "streams"
    quiet_paths = [streams / f"{stream_id}.jsonl" for stream_id in quiet]
    quiet_bytes = {path: path.read_bytes() for path in quiet_paths}
    assert all(b"Qui\xc3\xa9t" in data for data in quiet_bytes.values())
    # Written by the Rust store writer, and the merge changes no manifest field.
    manifest_path = tmp_path / BEADS_DIRNAME / "events" / "manifest.json"
    manifest_bytes = manifest_path.read_bytes()

    result = resolve_bead_conflicts(tmp_path, beads_dir=tmp_path / BEADS_DIRNAME)

    assert result.ok is True, result.message
    assert {path: path.read_bytes() for path in quiet_paths} == quiet_bytes
    assert manifest_path.read_bytes() == manifest_bytes
    staged = _git(tmp_path, "diff", "--cached", "--name-only").stdout.split()
    assert not [path for path in staged if any(name in path for name in quiet)]
    issues = (tmp_path / BEADS_DIRNAME / "issues.jsonl").read_bytes()
    assert b"Qui\xc3\xa9t" in issues
    assert b"\\u" not in issues


@pytest.mark.parametrize(
    ("legacy_notes", "expected_legacy_note_texts"),
    [
        ("", []),
        ("a pre-existing legacy note", ["a pre-existing legacy note"]),
    ],
)
def test_resolution_preserves_legacy_notes_event_bytes_in_conflicted_stream(
    tmp_path: Path,
    legacy_notes: str,
    expected_legacy_note_texts: list[str],
) -> None:
    contested, _quiet = _build_stream_conflict(
        tmp_path,
        legacy_notes=legacy_notes,
    )
    legacy_line = _git(tmp_path, "show", f":2:{contested}").stdout.splitlines()[0]
    assert f'"notes":{json.dumps(legacy_notes)}' in legacy_line

    result = resolve_bead_conflicts(tmp_path, beads_dir=tmp_path / BEADS_DIRNAME)

    assert result.ok is True, result.message
    resolved = (tmp_path / contested).read_text(encoding="utf-8")
    assert resolved.startswith(f"{legacy_line}\n")
    assert "from local" in resolved and "from other" in resolved
    assert prepare_event_streams_for_commit(tmp_path, [contested]).restored_paths == ()
    with BeadProject(tmp_path, beads_dirname=BEADS_DIRNAME) as project:
        issue = project.show(Path(contested).stem)
    assert [note.text for note in issue.notes] == [
        *expected_legacy_note_texts,
        "from other",
    ]


def test_failed_stage_read_does_not_silently_drop_one_side(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unreadable conflict stage is an error, not an empty stream."""
    contested, _quiet = _build_stream_conflict(tmp_path)
    real_run_git = conflict_resolver._run_git

    def fail_stage_read(cwd: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
        if args[:1] == ["show"]:
            return subprocess.CompletedProcess(
                ["git", *args], 128, stdout="", stderr="fatal: injected show failure"
            )
        return real_run_git(cwd, args)

    monkeypatch.setattr(conflict_resolver, "_run_git", fail_stage_read)

    result = resolve_bead_conflicts(tmp_path, beads_dir=tmp_path / BEADS_DIRNAME)

    assert result.ok is False
    assert f"could not read stage 1 of {contested}" in result.message
