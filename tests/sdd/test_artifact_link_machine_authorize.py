"""Authorize-before-mutate for background artifact-link writers."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from sase.agents_sync.referenced_by_outbox import ReferencedByOutboxItem
from sase.sdd._artifact_link_authorize import (
    probe_machine_writable_sidecar_root,
    sidecar_root_not_machine_writable_message,
)
from sase.sdd._artifact_link_commit import persist_artifact_link_graph_mutation
from sase.sdd._artifact_link_renames import repair_historical_artifact_renames
from sase.sdd._artifact_link_store_support import sidecar_index_path
from sase.sdd.artifact_link_backfill import (
    reconcile_and_repair_artifact_links,
    run_artifact_link_backfill_batch,
)
from sase.sdd.artifact_link_outbox import (
    append_artifact_link_outbox_entry,
    drain_artifact_link_outbox,
    _read_artifact_link_outbox_entries,
)
from sase.sdd.artifact_link_store import ArtifactLinkStore
from sase.sdd.referenced_by_refresh import refresh_referenced_by
from sase.sdd.store import SddStore
from tests._conftest_environment import redirect_sase_home
from tests.sdd._artifact_link_store_helpers import _row, _store


def _primary_owned_sidecars(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Path, Path, Path]:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    primary = tmp_path / "proj"
    primary.mkdir()
    (primary / ".sase").mkdir()
    (primary / ".sase" / "sdd-store.json").write_text("{}\n", encoding="utf-8")
    plans = primary / "sase" / "repos" / "plans"
    research = primary / "sase" / "repos" / "research"
    plans.mkdir(parents=True)
    research.mkdir(parents=True)
    return primary, plans, research


def _link_store(plans: Path, research: Path) -> ArtifactLinkStore:
    return ArtifactLinkStore(
        project_key="gh_sase-org__sase",
        sidecar_roots={"plan": plans, "research": research},
    )


def _init_git_repo(repo: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    _git(repo, "config", "user.email", "test@test.com")
    _git(repo, "config", "user.name", "Test")


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )


def _git_output(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _worktree_snapshot(root: Path) -> tuple[str, str, dict[str, bytes]]:
    head = ""
    status = ""
    if (root / ".git").exists():
        head = _git_output(root, "rev-parse", "HEAD")
        status = _git_output(root, "status", "--porcelain", "--untracked-files=all")
    files: dict[str, bytes] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file() or ".git" in path.parts:
            continue
        files[path.relative_to(root).as_posix()] = path.read_bytes()
    return head, status, files


def _write_link_index(
    repo: Path,
    artifact_ref: str,
    *,
    rows: list[dict[str, object]],
) -> Path:
    path = sidecar_index_path(repo, artifact_ref)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "artifact_ref": artifact_ref,
                "rows": rows,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def _plan_request() -> ReferencedByOutboxItem:
    return ReferencedByOutboxItem(
        project_key="proj",
        project="Project",
        global_agent="alice.athena.worker",
        agent_url="https://example.test/agents/worker",
        primary_revision="a" * 40,
        sidecar_role="plans",
        provider="plan",
        artifact_id="plan:202608/example.md",
        repo_relpath="202608/example.md",
        identity_value=None,
        canonical_ref="plan:202608/example.md",
        destination="https://example.test/prompts/example.md",
        uses=2,
        published_date="2026-08-12",
        description="prompt reference @plan:202608/example.md",
    )


def test_probe_refuses_primary_owned_sidecar(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _primary, plans, _research = _primary_owned_sidecars(tmp_path, monkeypatch)

    result = probe_machine_writable_sidecar_root(plans)

    assert result.writable is False
    assert result.diagnostic is not None
    assert "primary workspace #0" in result.diagnostic
    assert (
        sidecar_root_not_machine_writable_message(
            "plan", plans, diagnostic=result.diagnostic
        )
        == "plan root not machine-writable: resolves to primary #0"
    )


def test_probe_refuses_unidentified_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    orphan = tmp_path / "orphan"
    orphan.mkdir()

    result = probe_machine_writable_sidecar_root(orphan)

    assert result.writable is False
    assert result.diagnostic is not None
    assert "missing checkout marker or registry evidence" in result.diagnostic


def test_probe_reports_writable_when_authorize_accepts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "sase.workspace_provider.ownership.authorize_store_mutation",
        lambda *_args, **_kwargs: None,
    )

    result = probe_machine_writable_sidecar_root(tmp_path)

    assert result.writable is True
    assert result.diagnostic is None


def test_rename_repair_skips_primary_owned_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _primary, plans, research = _primary_owned_sidecars(tmp_path, monkeypatch)
    store = _link_store(plans, research)
    _init_git_repo(plans)
    old_doc = plans / "202608" / "old.md"
    new_doc = plans / "202608" / "new.md"
    old_doc.parent.mkdir(parents=True)
    old_doc.write_text("# old\n", encoding="utf-8")
    _write_link_index(
        plans,
        "plan:202608/old.md",
        rows=[
            _row(
                source="agent:planner.coder",
                relation="read",
                target="plan:202608/old.md",
                origin="read",
            )
        ],
    )
    _git(plans, "add", ".")
    _git(plans, "commit", "-m", "seed old artifact")
    old_doc.rename(new_doc)
    _git(plans, "add", "-A")
    _git(plans, "commit", "-m", "rename artifact")
    before = _worktree_snapshot(plans)

    report = repair_historical_artifact_renames(
        store,
        ("plan:202608/old.md",),
        require_machine_writable=True,
    )

    assert report.changed_paths == ()
    assert report.skip_diagnostics
    assert any("not machine-writable" in item for item in report.skip_diagnostics)
    assert any("resolves to primary #0" in item for item in report.skip_diagnostics)
    assert _worktree_snapshot(plans) == before


def test_reconcile_and_repair_reports_skip_and_does_not_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _primary, plans, research = _primary_owned_sidecars(tmp_path, monkeypatch)
    store = _link_store(plans, research)
    _init_git_repo(plans)
    _git(plans, "commit", "--allow-empty", "-m", "seed")
    monkeypatch.setattr(ArtifactLinkStore, "reconcile_aggregate", lambda _store: None)
    monkeypatch.setattr(
        "sase.artifact_cli.link_health.dangling_and_orphaned_artifact_link_refs",
        lambda _store: ("plan:202608/old.md",),
    )
    monkeypatch.setattr(
        "sase.sdd._artifact_link_renames.repair_historical_artifact_renames",
        lambda _store, _refs, **_kwargs: SimpleNamespace(
            renames=(),
            changed_paths=(),
            deferred_refs=0,
            skip_diagnostics=(
                "plan root not machine-writable: resolves to primary #0",
            ),
        ),
    )
    commit_calls: list[object] = []
    monkeypatch.setattr(
        "sase.sdd._artifact_link_commit.commit_artifact_link_indexes",
        lambda paths, **kwargs: commit_calls.append((paths, kwargs)),
    )

    report = reconcile_and_repair_artifact_links(store)

    assert commit_calls == []
    assert report.repaired_renames == 0
    assert report.skip_diagnostics == (
        "plan root not machine-writable: resolves to primary #0",
    )
    assert _git_output(plans, "status", "--short") == ""


def test_backfill_sweep_skips_primary_owned_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _primary, plans, research = _primary_owned_sidecars(tmp_path, monkeypatch)
    store = _link_store(plans, research)
    plan_path = plans / "202608" / "example.md"
    plan_path.parent.mkdir(parents=True)
    plan_path.write_text("---\ntier: tale\nbead_id: sase-xx\n---\n\nbody\n")
    before = _worktree_snapshot(plans)

    report, swept = run_artifact_link_backfill_batch(
        store, already_swept=frozenset(), batch_size=10
    )

    assert report.scanned == 0
    assert report.persisted == 0
    assert report.remaining == 1
    assert any("not machine-writable" in item for item in report.errors)
    assert any("resolves to primary #0" in item for item in report.errors)
    assert swept == frozenset()
    assert _worktree_snapshot(plans) == before
    assert not list(plans.joinpath("links").rglob("*.json"))


def test_outbox_drain_skips_primary_owned_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _primary, plans, research = _primary_owned_sidecars(tmp_path, monkeypatch)
    store = _link_store(plans, research)
    _init_git_repo(plans)
    (plans / "doc.md").write_text("# Doc\n", encoding="utf-8")
    _git(plans, "add", ".")
    _git(plans, "commit", "-m", "seed")
    append_artifact_link_outbox_entry(
        project_key="gh_sase-org__sase",
        agent_name="reader",
        row=_row(
            source="agent:reader",
            relation="read",
            target="plan:doc.md",
            origin="read",
        ),
    )
    monkeypatch.setattr(
        "sase.sdd.artifact_link_outbox._agent_is_published",
        lambda _name: True,
    )
    before = _worktree_snapshot(plans)
    before_head = _git_output(plans, "rev-parse", "HEAD")

    report = drain_artifact_link_outbox(
        store=store,
        agent_name="reader",
        drop_stale_terminal=False,
        push_after_commit=False,
    )

    assert report.drained == 0
    assert report.committed is False
    assert report.skip_diagnostics
    assert any("not machine-writable" in item for item in report.skip_diagnostics)
    assert len(_read_artifact_link_outbox_entries("gh_sase-org__sase")) == 1
    assert _worktree_snapshot(plans) == before
    assert _git_output(plans, "rev-parse", "HEAD") == before_head


def test_referenced_by_refresh_skips_primary_owned_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _primary, plans, _research = _primary_owned_sidecars(tmp_path, monkeypatch)
    document = plans / "202608" / "example.md"
    document.parent.mkdir(parents=True)
    document.write_text("# Example\n\nBody\n", encoding="utf-8")
    store = SddStore("sidecar_repos", plans, plans)
    before = document.read_bytes()

    report = refresh_referenced_by(
        store,
        role="plans",
        requests=(_plan_request(),),
        write=True,
    )

    assert not report.ok
    assert report.committed is False
    assert report.changed_files == ()
    assert report.issues[0].code == "not-machine-writable"
    assert "not machine-writable" in report.issues[0].message
    assert "resolves to primary #0" in report.issues[0].message
    assert document.read_bytes() == before
    assert not list(plans.joinpath("links").rglob("*.json"))


def test_persist_graph_mutation_defaults_to_user_origin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _store(tmp_path, monkeypatch)
    seen: list[dict[str, object]] = []

    def _commit(*_args: object, **kwargs: object) -> SimpleNamespace:
        seen.append(kwargs)
        return SimpleNamespace(publication_error=None, committed=True)

    monkeypatch.setattr(
        "sase.sdd._artifact_link_commit.commit_artifact_link_indexes",
        _commit,
    )

    persist_artifact_link_graph_mutation(
        store,
        changed_indexes=(tmp_path / "plans" / "links" / "a.json",),
        beads_changed=False,
    )

    assert seen[0]["mutation_origin"] == "user"
