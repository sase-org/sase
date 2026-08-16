"""Append-only event-stream guards for bead publication and sync."""

from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

from sase.bead._stream_integrity import (
    BeadStreamIntegrityError,
    diagnose_event_stream_history,
    prepare_event_streams_for_commit,
    refuse_unpublished_event_stream_shrink,
)
from sase.bead._stream_integrity_analysis import analyze_stream_against_ancestor
from sase.bead._stream_integrity_files import (
    encode_stream_events,
    is_event_stream_relpath,
    parse_stream_text,
)
from sase.bead.model import IssueType
from sase.bead.project import BEADS_DIRNAME_ROOT, BeadProject
from sase.bead.sync import bead_sync_diagnostics, commit_epic_graph_checkpoint
from sase.bead.sync_worker import run_managed_sync_worker
from sase.bead_pages.publication import publish_committed_bead_pages
from sase.sdd._commit_store import commit_sdd_files
from sase.sdd.store import SddStore

from .sync_conflict_regression_helpers import _clone, _commit, _git
from .sync_test_helpers import init_git_repo


def _event(event_id: str, **fields: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "event_id": event_id,
        "timestamp": "2026-08-13T00:00:00Z",
        "actor": "tester@example.com",
        "operation": "issue_updated",
        "note": event_id,
    }
    payload.update(fields)
    return payload


def _write_events(path: Path, events: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(encode_stream_events(events), encoding="utf-8")


def test_is_event_stream_relpath_accepts_canonical_layouts() -> None:
    assert is_event_stream_relpath("events/streams/sase-l1.jsonl")
    assert is_event_stream_relpath("sdd/beads/events/streams/sase-l1.jsonl")
    assert not is_event_stream_relpath("events/manifest.json")
    assert not is_event_stream_relpath("pages/sase-l1/README.md")


def test_analyze_allows_ordinary_append() -> None:
    ancestor = [_event("a"), _event("b")]
    local = [_event("a"), _event("b"), _event("c")]
    analysis = analyze_stream_against_ancestor(
        ancestor,
        local,
        ancestor_text=encode_stream_events(ancestor),
        other_streams={},
        new_stream_ids=set(),
        stream_id="sase-l1",
    )
    assert analysis.kind == "ok"


def test_analyze_restores_pure_shrink_and_rejects_rewrite() -> None:
    ancestor = [_event("a"), _event("b"), _event("c")]
    shrink = analyze_stream_against_ancestor(
        ancestor,
        ancestor[:2],
        ancestor_text=encode_stream_events(ancestor),
        other_streams={},
        new_stream_ids=set(),
        stream_id="sase-l1",
    )
    assert shrink.kind == "restore_exact"
    assert shrink.first_event == 3
    assert shrink.last_event == 3

    rewritten = [_event("a"), _event("b", note="mutated"), _event("c")]
    rewrite = analyze_stream_against_ancestor(
        ancestor,
        rewritten,
        ancestor_text=encode_stream_events(ancestor),
        other_streams={},
        new_stream_ids=set(),
        stream_id="sase-l1",
    )
    assert rewrite.kind == "rewrite"
    assert rewrite.first_event == 2
    assert rewrite.rewrite_diagnosis == "value changed at note"


def test_analyze_rewrite_diagnosis_names_dropped_and_added_nested_keys() -> None:
    # Mirrors the bead_event_resolution_roundtrip wedge: a nested field
    # silently dropped by a non-round-trip-stable decode/encode pair.
    ancestor = [
        _event(
            "a",
            payload={"kind": "issue_updated", "fields": {"resolution": None}},
        ),
    ]
    local = [
        _event("a", payload={"kind": "issue_updated", "fields": {}}),
    ]
    rewrite = analyze_stream_against_ancestor(
        ancestor,
        local,
        ancestor_text=encode_stream_events(ancestor),
        other_streams={},
        new_stream_ids=set(),
        stream_id="sase-l1",
    )
    assert rewrite.kind == "rewrite"
    assert rewrite.rewrite_diagnosis == "removed payload.fields.resolution"

    reversed_rewrite = analyze_stream_against_ancestor(
        local,
        ancestor,
        ancestor_text=encode_stream_events(local),
        other_streams={},
        new_stream_ids=set(),
        stream_id="sase-l1",
    )
    assert reversed_rewrite.kind == "rewrite"
    assert reversed_rewrite.rewrite_diagnosis == "added payload.fields.resolution"


def test_analyze_preserves_local_extras_when_restoring_missing_prefix() -> None:
    ancestor = [_event("a"), _event("b"), _event("c")]
    local = [_event("a"), _event("b"), _event("extra")]
    analysis = analyze_stream_against_ancestor(
        ancestor,
        local,
        ancestor_text=encode_stream_events(ancestor),
        other_streams={},
        new_stream_ids=set(),
        stream_id="sase-l1",
    )
    assert analysis.kind == "restore_superset"
    assert analysis.restored_events == (
        _event("a"),
        _event("b"),
        _event("c"),
        _event("extra"),
    )


def test_analyze_allows_relocation_into_a_new_stream() -> None:
    ancestor = [_event("a"), _event("b"), _event("moved")]
    local = [_event("a"), _event("b")]
    relocated = [_event("moved-remap", timestamp="2026-08-13T00:00:00Z")]
    analysis = analyze_stream_against_ancestor(
        ancestor,
        local,
        ancestor_text=encode_stream_events(ancestor),
        other_streams={"sase-l9": relocated},
        new_stream_ids={"sase-l9"},
        stream_id="sase-l1",
    )
    assert analysis.kind == "ok"


def _init_beads_repo(repo: Path) -> tuple[str, Path]:
    repo.mkdir(parents=True, exist_ok=True)
    init_git_repo(repo)
    _git(repo, "branch", "-M", "main")
    (repo / ".gitignore").write_text("beads.db*\n", encoding="utf-8")
    with BeadProject.init(repo, beads_dirname=BEADS_DIRNAME_ROOT) as project:
        issue = project.create("Protected stream", IssueType.PLAN)
        project.update(issue.id, notes="keep this event")
    _commit(repo, "seed append-only stream")
    stream = repo / f"events/streams/{issue.id}.jsonl"
    return issue.id, stream


def test_prepare_restores_shrink_and_keeps_unrelated_page_changes(
    tmp_path: Path,
) -> None:
    issue_id, stream = _init_beads_repo(tmp_path / "beads")
    committed = stream.read_text(encoding="utf-8")
    events = parse_stream_text(committed)
    assert len(events) >= 2
    _write_events(stream, events[:-1])
    page = tmp_path / "beads" / "pages" / issue_id / "README.md"
    page.parent.mkdir(parents=True)
    page.write_text("stale page\n", encoding="utf-8")

    result = prepare_event_streams_for_commit(
        tmp_path / "beads",
        [
            f"events/streams/{issue_id}.jsonl",
            f"pages/{issue_id}/README.md",
        ],
    )

    assert result.restored_paths == (f"events/streams/{issue_id}.jsonl",)
    assert stream.read_text(encoding="utf-8") == committed
    assert page.read_text(encoding="utf-8") == "stale page\n"


def test_prepare_rejects_rewrite_and_restores_ancestor(tmp_path: Path) -> None:
    issue_id, stream = _init_beads_repo(tmp_path / "beads")
    committed = stream.read_text(encoding="utf-8")
    events = parse_stream_text(committed)
    events[0] = dict(events[0])
    events[0]["actor"] = "rewriter@example.com"
    _write_events(stream, events)

    with pytest.raises(
        BeadStreamIntegrityError,
        match=r"rewrote ancestor event 1 \(value changed at actor\)",
    ):
        prepare_event_streams_for_commit(
            tmp_path / "beads",
            [f"events/streams/{issue_id}.jsonl"],
        )

    assert stream.read_text(encoding="utf-8") == committed


def test_commit_sdd_files_allows_append_and_refuses_to_commit_a_shrink(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "beads"
    issue_id, stream = _init_beads_repo(repo)
    with BeadProject(repo, beads_dirname=BEADS_DIRNAME_ROOT) as project:
        project.update(issue_id, notes="local append")
    appended = stream.read_text(encoding="utf-8")

    assert commit_sdd_files(repo, "chore(beads): append") is True
    assert stream.read_text(encoding="utf-8") == appended
    subject = _git(repo, "log", "-1", "--format=%s").stdout.strip()
    assert "append" in subject

    events = parse_stream_text(appended)
    _write_events(stream, events[:-1])
    page = repo / "pages" / issue_id / "README.md"
    page.parent.mkdir(parents=True)
    page.write_text("page after shrink\n", encoding="utf-8")

    assert (
        commit_sdd_files(
            repo,
            "chore(beads): sync bead state and pages for sase-l3",
        )
        is True
    )
    assert stream.read_text(encoding="utf-8") == appended
    show = _git(
        repo,
        "show",
        "HEAD:events/streams/" + issue_id + ".jsonl",
    )
    assert show.stdout == appended
    committed_page = _git(
        repo,
        "show",
        f"HEAD:pages/{issue_id}/README.md",
    )
    assert committed_page.stdout == "page after shrink\n"


def test_publication_commit_cannot_delete_a_base_event(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checkout = tmp_path / "checkout"
    plans = checkout / "sase" / "repos" / "plans"
    beads = checkout / "sase" / "repos" / "beads"
    checkout.mkdir(parents=True)
    plans.mkdir(parents=True)
    init_git_repo(plans)
    issue_id, stream = _init_beads_repo(beads)
    committed = stream.read_text(encoding="utf-8")
    events = parse_stream_text(committed)
    _write_events(stream, events[:-1])

    store = SddStore(
        storage="sidecar_repos",
        sdd_dir=plans,
        repo_root=plans,
        beads_dir=beads,
        beads_remote_url="git@example.com:sase-org/sase--beads.git",
    )
    monkeypatch.setattr(
        "sase.sdd.plan_refs.workspace_context_for_plan_resolution",
        lambda _root: (plans, 1),
    )
    monkeypatch.setattr("sase.sdd.store.resolve_sdd_store", lambda *_args: store)
    monkeypatch.setattr(
        "sase.bead.sync.push_bead_work_launch_async",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        "sase.bead.sync.push_bead_work_launch",
        lambda *_args, **_kwargs: None,
    )

    outcome = publish_committed_bead_pages(
        f"feat: publish\n\nSASE_BEAD={issue_id}",
        primary_root=checkout,
    )

    assert outcome.error is None
    assert stream.read_text(encoding="utf-8") == committed
    head_stream = _git(
        beads,
        "show",
        f"HEAD:events/streams/{issue_id}.jsonl",
    ).stdout
    assert head_stream == committed
    if outcome.committed:
        subject = _git(beads, "log", "-1", "--format=%s").stdout
        assert "sync bead state and pages" in subject
        names = _git(beads, "show", "--name-only", "--format=", "HEAD").stdout
        assert f"events/streams/{issue_id}.jsonl" not in names.splitlines()


def test_commit_epic_graph_checkpoint_restores_exact_starting_stream(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    issue_id, stream = _init_beads_repo(repo)
    committed = stream.read_text(encoding="utf-8")
    events = parse_stream_text(committed)
    _write_events(stream, events[:-1])
    starting = stream.read_text(encoding="utf-8")

    committed_any = commit_epic_graph_checkpoint(repo, issue_id)

    assert committed_any is False
    assert stream.read_text(encoding="utf-8") == committed
    assert starting != committed


def _bare_remote(path: Path) -> Path:
    subprocess.run(
        ["git", "init", "--bare", "-b", "main", str(path)],
        check=True,
        capture_output=True,
        text=True,
    )
    return path


def test_managed_sync_worker_refuses_to_push_a_committed_shrink(
    tmp_path: Path,
) -> None:
    remote = _bare_remote(tmp_path / "remote.git")
    seed = tmp_path / "seed"
    issue_id, stream = _init_beads_repo(seed)
    _git(seed, "remote", "add", "origin", str(remote))
    _git(seed, "push", "-u", "origin", "main")
    full = stream.read_text(encoding="utf-8")

    local = tmp_path / "local"
    _clone(remote, local)
    local_stream = local / f"events/streams/{issue_id}.jsonl"
    _write_events(local_stream, parse_stream_text(full)[:-1])
    _commit(local, "chore(beads): sync bead state and pages for sase-l3", "events")

    outcome = run_managed_sync_worker(
        local,
        local,
        log_path=tmp_path / "sync.log",
    )

    assert outcome.pushed is False
    assert outcome.error is not None
    assert "non-append-only bead event stream" in outcome.error
    assert "missing ancestor events" in outcome.error
    remote_stream = _git(
        local,
        "show",
        f"origin/main:events/streams/{issue_id}.jsonl",
    ).stdout
    assert remote_stream == full
    assert not (local / ".git/rebase-merge").exists()
    assert not (local / ".git/rebase-apply").exists()


def test_refuse_unpublished_shrink_is_quiet_when_only_behind(
    tmp_path: Path,
) -> None:
    remote = _bare_remote(tmp_path / "remote.git")
    seed = tmp_path / "seed"
    issue_id, stream = _init_beads_repo(seed)
    _git(seed, "remote", "add", "origin", str(remote))
    _git(seed, "push", "-u", "origin", "main")
    behind = tmp_path / "behind"
    _clone(remote, behind)
    with BeadProject(seed, beads_dirname=BEADS_DIRNAME_ROOT) as project:
        project.update(issue_id, notes="origin append")
    _commit(seed, "origin append", "events")
    _git(seed, "push")

    refuse_unpublished_event_stream_shrink(behind, behind)
    assert stream.read_text(encoding="utf-8") != (
        behind / f"events/streams/{issue_id}.jsonl"
    ).read_text(encoding="utf-8")


def test_diagnostics_name_stream_range_and_offending_commit(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "beads"
    issue_id, stream = _init_beads_repo(repo)
    parent = _git(repo, "rev-parse", "HEAD").stdout.strip()
    _write_events(stream, parse_stream_text(stream.read_text(encoding="utf-8"))[:-1])
    _commit(
        repo,
        "chore(beads): sync bead state and pages for sase-l3",
        f"events/streams/{issue_id}.jsonl",
    )
    offender = _git(repo, "rev-parse", "HEAD").stdout.strip()

    messages = diagnose_event_stream_history(repo, repo)

    matching = [message for message in messages if issue_id in message]
    assert matching
    message = matching[0]
    assert message.startswith(f"ERROR: bead event stream {issue_id} is shorter")
    assert "missing events" in message
    assert parent[:12] in message
    assert offender[:12] in message
    assert "sync bead state and pages for sase-l3" in message


def test_bead_sync_diagnostics_include_historical_corruption(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "beads"
    issue_id, stream = _init_beads_repo(repo)
    _write_events(stream, parse_stream_text(stream.read_text(encoding="utf-8"))[:-1])
    _commit(repo, "chore(beads): drop an event", f"events/streams/{issue_id}.jsonl")

    messages = bead_sync_diagnostics(repo)

    assert any(
        f"bead event stream {issue_id} is shorter than its own history" in message
        for message in messages
    )


def test_diagnostics_degrade_when_history_is_unavailable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "beads"
    _init_beads_repo(repo)

    def boom(*_args: object, **_kwargs: object) -> None:
        raise OSError("git unavailable")

    monkeypatch.setattr(
        "sase.bead._stream_integrity_git.run_sdd_git",
        boom,
    )

    assert diagnose_event_stream_history(repo, repo) == []


def test_concurrent_independent_append_still_merges(
    tmp_path: Path,
) -> None:
    remote = _bare_remote(tmp_path / "remote.git")
    seed = tmp_path / "seed"
    issue_id, _stream = _init_beads_repo(seed)
    _git(seed, "remote", "add", "origin", str(remote))
    _git(seed, "push", "-u", "origin", "main")
    left = tmp_path / "left"
    right = tmp_path / "right"
    _clone(remote, left)
    _clone(remote, right)
    with BeadProject(left, beads_dirname=BEADS_DIRNAME_ROOT) as project:
        project.update(issue_id, notes="left append")
    _commit(left, "left append")
    with BeadProject(right, beads_dirname=BEADS_DIRNAME_ROOT) as project:
        project.update(issue_id, title="right append")
    _commit(right, "right append")
    _git(right, "push")

    outcome = run_managed_sync_worker(
        left,
        left,
        log_path=tmp_path / "merge.log",
    )

    assert outcome.error is None
    assert outcome.pushed is True
    merged = (left / f"events/streams/{issue_id}.jsonl").read_text(encoding="utf-8")
    assert "left append" in merged
    assert "right append" in merged
