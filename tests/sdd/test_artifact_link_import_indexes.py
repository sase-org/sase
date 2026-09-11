"""Tests for legacy artifact-link index import."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess

import pytest

from sase.bead._sync_publication import PushOutcome
from sase.sdd._artifact_link_cutover_state import read_artifact_link_cutover_marker
from sase.sdd._artifact_link_cutover_state import artifact_link_cutover_marker_path
from sase.sdd.artifact_link_import_indexes import import_artifact_link_indexes
from sase.sdd.artifact_link_outbox import (
    ARTIFACT_LINK_OUTBOX_DROPPED_FILENAME,
    ARTIFACT_LINK_OUTBOX_FILENAME,
    inspect_artifact_link_outbox,
    read_artifact_link_outbox_entries,
)
from sase.sdd.artifact_link_store import (
    ARTIFACT_LINK_ROW_SCHEMA_VERSION,
    ArtifactLinkStore,
)
from tests._conftest_environment import redirect_sase_home
from tests.sdd._artifact_link_store_helpers import _row, allow_machine_sidecar_writes


PROJECT_KEY = "gh_sase-org__sase"


def test_import_indexes_preview_is_deterministic_without_writes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    repo = _init_repo(tmp_path / "plans")
    _write_index(repo, "a.md", [_row(target="plan:b.md")])
    _write_index(repo, "b.md", [_row(target="plan:b.md")])
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "legacy link indexes")
    store = ArtifactLinkStore(project_key=PROJECT_KEY, sidecar_roots={"plan": repo})
    head = _git(repo, "rev-parse", "HEAD")

    first = import_artifact_link_indexes(store).plan
    second = import_artifact_link_indexes(store).plan

    assert first.import_id == second.import_id
    assert first.operation_id == second.operation_id
    assert first.duplicate_rows == 1
    assert len(first.rows) == 1
    assert first.baseline_event["kind"]["type"] == "baseline-import"
    assert read_artifact_link_cutover_marker(repo) is None
    assert not (repo / "link-events").exists()
    assert _git(repo, "rev-parse", "HEAD") == head


def test_import_indexes_apply_publishes_markers_and_baseline_event(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    allow_machine_sidecar_writes(monkeypatch)
    repo = _init_repo(tmp_path / "plans")
    _write_index(repo, "a.md", [_row(target="plan:b.md")])
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "legacy link indexes")
    store = ArtifactLinkStore(project_key=PROJECT_KEY, sidecar_roots={"plan": repo})

    report = import_artifact_link_indexes(
        store,
        apply=True,
        push_after_commit=False,
    )

    assert report.applied is True
    assert report.already_imported is False
    marker = read_artifact_link_cutover_marker(repo, expected_project_key=PROJECT_KEY)
    assert marker is not None
    assert marker.state == "imported"
    assert marker.import_id == report.plan.import_id
    assert any(path.exists() for path in report.event_paths)
    [row] = store.load_durable_rows()
    assert row["source_ref"] == "plan:202608/a.md"
    assert row["target_ref"] == "plan:b.md"
    with pytest.raises(RuntimeError, match="legacy index writes are fenced"):
        store.upsert_row(_row(relation="cites"))

    reapply = import_artifact_link_indexes(
        store,
        apply=True,
        push_after_commit=False,
    )

    assert reapply.already_imported is True
    assert reapply.plan.import_id == report.plan.import_id
    assert _git(repo, "status", "--porcelain=v1", "--untracked-files=all") == ""


def test_import_indexes_resumes_from_committed_fenced_marker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    allow_machine_sidecar_writes(monkeypatch)
    repo = _init_repo(tmp_path / "plans")
    _write_index(repo, "a.md", [_row(target="plan:b.md")])
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "legacy link indexes")
    store = ArtifactLinkStore(project_key=PROJECT_KEY, sidecar_roots={"plan": repo})
    preview = import_artifact_link_indexes(store)
    marker_path = artifact_link_cutover_marker_path(repo)
    marker_path.parent.mkdir(parents=True, exist_ok=True)
    marker_path.write_bytes(preview.plan.fenced_marker.canonical_bytes)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "partial cutover marker")

    report = import_artifact_link_indexes(
        store,
        apply=True,
        push_after_commit=False,
    )

    marker = read_artifact_link_cutover_marker(repo, expected_project_key=PROJECT_KEY)
    assert marker is not None
    assert marker.state == "imported"
    assert report.fenced_markers_changed == ()
    assert len(report.event_paths) == 1
    assert len(report.imported_markers_changed) == 1
    [row] = store.load_durable_rows()
    assert row["target_ref"] == "plan:b.md"


def test_import_indexes_resumes_multi_root_after_partial_marker_write_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A crash between two roles' marker writes must not corrupt either root.

    Reproduces the audited defect where failing the second of two
    ``atomic_write_bytes`` marker writes left a role with a partial marker
    set that every retry rejected as ``partial; missing roles``.
    """

    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    allow_machine_sidecar_writes(monkeypatch)
    plans = _init_repo(tmp_path / "plans")
    research = _init_repo(tmp_path / "research")
    _write_index(plans, "a.md", [_row(target="research:202608/a.md")])
    _git(plans, "add", "-A")
    _git(plans, "commit", "-q", "-m", "legacy link indexes")
    store = ArtifactLinkStore(
        project_key=PROJECT_KEY,
        sidecar_roots={"plan": plans, "research": research},
    )

    import sase.sdd._artifact_link_import_apply as import_apply

    original_write = import_apply.atomic_write_bytes
    calls = 0

    def _fail_second_marker_write(path: Path, payload: bytes) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("simulated crash between role marker writes")
        original_write(path, payload)

    monkeypatch.setattr(import_apply, "atomic_write_bytes", _fail_second_marker_write)

    with pytest.raises(OSError, match="simulated crash between role marker writes"):
        import_artifact_link_indexes(store, apply=True, push_after_commit=False)

    monkeypatch.setattr(import_apply, "atomic_write_bytes", original_write)

    report = import_artifact_link_indexes(store, apply=True, push_after_commit=False)

    assert report.applied is True
    for root in (plans, research):
        marker = read_artifact_link_cutover_marker(
            root, expected_project_key=PROJECT_KEY
        )
        assert marker is not None
        assert marker.state == "imported"
        assert _git(root, "status", "--porcelain=v1", "--untracked-files=all") == ""
    [row] = store.load_durable_rows()
    assert row["source_ref"] == "plan:202608/a.md"
    assert row["target_ref"] == "research:202608/a.md"

    resumed_again = import_artifact_link_indexes(
        store, apply=True, push_after_commit=False
    )
    assert resumed_again.already_imported is True
    assert len(store.load_durable_rows()) == 1


def test_import_retry_publishes_previously_failed_final_marker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    allow_machine_sidecar_writes(monkeypatch)
    repo = _init_repo_with_remote(tmp_path, "plans")
    _write_index(repo, "a.md", [_row(target="plan:b.md")])
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "legacy link indexes")
    _git(repo, "push")
    store = ArtifactLinkStore(project_key=PROJECT_KEY, sidecar_roots={"plan": repo})
    from sase.bead.sync import push_bead_work_launch

    def fail_imported_marker(root: Path, **kwargs: object) -> PushOutcome:
        marker = read_artifact_link_cutover_marker(Path(root))
        if marker is not None and marker.state == "imported":
            return PushOutcome(
                pushed=False,
                skipped_no_remote=False,
                error="simulated final-marker publication failure",
            )
        return push_bead_work_launch(root, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr("sase.bead.sync.push_bead_work_launch", fail_imported_marker)
        with pytest.raises(RuntimeError, match="NOT published"):
            import_artifact_link_indexes(store, apply=True, push_after_commit=True)

    retried = import_artifact_link_indexes(store, apply=True, push_after_commit=True)

    assert retried.already_imported is True
    assert _git(repo, "rev-parse", "HEAD") == _git(repo, "rev-parse", "origin/main")


def test_import_indexes_converts_legacy_outbox_and_preserves_invalid_lines(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / ".sase"
    redirect_sase_home(monkeypatch, home)
    allow_machine_sidecar_writes(monkeypatch)
    repo = _init_repo(tmp_path / "plans")
    baseline_row = _row(target="plan:b.md")
    queued_row = _row(
        relation="related",
        target="plan:c.md",
        description="queued legacy outbox row",
    )
    _write_index(repo, "a.md", [baseline_row])
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "legacy link indexes")
    _write_legacy_outbox(
        home,
        baseline_row=baseline_row,
        queued_row=queued_row,
    )
    store = ArtifactLinkStore(project_key=PROJECT_KEY, sidecar_roots={"plan": repo})

    report = import_artifact_link_indexes(
        store,
        apply=True,
        push_after_commit=False,
    )

    assert report.converted_outbox_entries == 1
    assert report.covered_outbox_entries == 1
    assert report.queued_legacy_outbox_entries == 0
    assert report.queued_invalid_outbox_entries == 1
    [entry] = read_artifact_link_outbox_entries(PROJECT_KEY)
    assert entry.event is not None
    assert entry.event["kind"]["type"] == "edge-put"
    stats = inspect_artifact_link_outbox(PROJECT_KEY)
    assert stats.event_queued == 1
    assert stats.invalid_queued == 1
    outbox_path = home / "projects" / PROJECT_KEY / ARTIFACT_LINK_OUTBOX_FILENAME
    assert "{not-json}" in outbox_path.read_text(encoding="utf-8")
    dropped = (
        home / "projects" / PROJECT_KEY / ARTIFACT_LINK_OUTBOX_DROPPED_FILENAME
    ).read_text(encoding="utf-8")
    assert "legacy_row_covered_by_baseline_import" in dropped


def test_import_indexes_rejects_conflicting_duplicate_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    repo = _init_repo(tmp_path / "plans")
    _write_index(
        repo,
        "a.md",
        [_row(target="plan:b.md", description="one source of truth")],
    )
    _write_index(
        repo,
        "b.md",
        [_row(target="plan:b.md", description="different source of truth")],
    )
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "conflicting legacy indexes")
    store = ArtifactLinkStore(project_key=PROJECT_KEY, sidecar_roots={"plan": repo})

    with pytest.raises(RuntimeError, match="conflicting legacy artifact-link rows"):
        import_artifact_link_indexes(store)


def _init_repo(repo: Path) -> Path:
    repo.mkdir(parents=True)
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "sase-test@example.invalid")
    _git(repo, "config", "user.name", "SASE Test")
    (repo / "202608").mkdir()
    (repo / "202608" / "a.md").write_text("# A\n", encoding="utf-8")
    (repo / "b.md").write_text("# B\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "seed docs")
    return repo


def _init_repo_with_remote(tmp_path: Path, name: str) -> Path:
    remote = tmp_path / "remotes" / f"{name}.git"
    repo = tmp_path / name
    remote.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "init", "--bare", "-q", "-b", "main", str(remote)],
        check=True,
    )
    subprocess.run(["git", "clone", "-q", str(remote), str(repo)], check=True)
    _git(repo, "config", "user.email", "sase-test@example.invalid")
    _git(repo, "config", "user.name", "SASE Test")
    (repo / "202608").mkdir()
    (repo / "202608" / "a.md").write_text("# A\n", encoding="utf-8")
    (repo / "b.md").write_text("# B\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "seed docs")
    _git(repo, "push", "-u", "origin", "main")
    return repo


def _write_index(
    repo: Path,
    artifact_relpath: str,
    rows: list[dict[str, object]],
) -> None:
    path = repo / "links" / f"{artifact_relpath}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema_version": ARTIFACT_LINK_ROW_SCHEMA_VERSION,
                "artifact_ref": f"plan:{artifact_relpath}",
                "rows": rows,
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def _write_legacy_outbox(
    home: Path,
    *,
    baseline_row: dict[str, object],
    queued_row: dict[str, object],
) -> None:
    path = home / "projects" / PROJECT_KEY / ARTIFACT_LINK_OUTBOX_FILENAME
    path.parent.mkdir(parents=True, exist_ok=True)
    records = [
        {
            "schema_version": 1,
            "id": "legacy-covered",
            "created_at": 100.0,
            "project_key": PROJECT_KEY,
            "agent_name": "reader",
            "run_id": "run-1",
            "row": baseline_row,
        },
        {
            "schema_version": 1,
            "id": "legacy-convert",
            "created_at": 101.0,
            "project_key": PROJECT_KEY,
            "agent_name": "reader",
            "run_id": "run-2",
            "row": queued_row,
        },
    ]
    path.write_text(
        "\n".join(json.dumps(record, sort_keys=True) for record in records)
        + "\n{not-json}\n",
        encoding="utf-8",
    )


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        check=True,
        text=True,
    )
    return result.stdout.strip()
