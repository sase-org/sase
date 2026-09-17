"""End-to-end: machine writes land in the hidden clone, primary converges.

A rename repair applied in the resolved hidden machine clone is committed and
published there; the primary checkout's own nested sidecar clone (behind the
shared remote, never written to directly) then fast-forwards to that same
commit through the existing pull-based sidecar auto-sync with a clean
worktree. This is the phase's central invariant:
[[decisions/hidden-clone-machine-writes]] (once filed) -- machine link
maintenance never dirties the primary's nested clones.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import sase._sidecar_auto_sync as sidecar_auto_sync
from sase._linked_repo_config import _SIDECAR_REMOTE_URL_KEY, _SIDECAR_ROLE_KEY
from sase._sidecar_auto_sync import auto_sync_roles, sync_primary_sidecar_role
from sase.bead.model import IssueType
from sase.bead.project import BEADS_DIRNAME_ROOT, BeadProject
from sase.linked_repos import hidden_sidecar_clone_dir
from sase.sdd._artifact_link_commit import commit_artifact_link_indexes
from sase.sdd._artifact_link_renames import repair_historical_artifact_renames
from sase.sdd._artifact_link_store_support import sidecar_index_path
from sase.sdd.artifact_link_event_publisher import (
    artifact_link_derived_producer_id,
    artifact_link_machine_run_id,
)
from sase.sdd.artifact_link_outbox import (
    append_artifact_link_outbox_entry,
    drain_artifact_link_outbox,
)
from sase.sdd.artifact_link_store import resolve_machine_artifact_link_store
from sase.sdd.store import write_sdd_store_record
from tests.sdd_store._helpers import clone, commit_all, git, init_bare_repo

_PROJECT_KEY = "acme_widget"


def _entry(role: str, *, remote_url: str) -> dict[str, object]:
    return {
        _SIDECAR_ROLE_KEY: role,
        "auto_sync": True,
        "disabled": False,
        _SIDECAR_REMOTE_URL_KEY: remote_url,
    }


def _write_project_file(path: Path, *, primary: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"WORKSPACE_DIR: {primary}\nNAME: demo\nDESCRIPTION:\n  fixture\nSTATUS: Ready\n",
        encoding="utf-8",
    )
    return path


def _seeded_role_remote(tmp_path: Path, role: str) -> Path:
    """Seed a bare remote for *role* with a tracked README so it has history."""

    remote = tmp_path / f"{role}.git"
    seed = tmp_path / f"{role}-seed"
    init_bare_repo(remote)
    clone(remote, seed)
    (seed / "README.md").write_text(f"# {role}\n", encoding="utf-8")
    commit_all(seed, "seed")
    git(["push", "-u", "origin", "main"], seed)
    return remote


def _seeded_beads_remote(tmp_path: Path) -> tuple[Path, str]:
    """Seed a bare beads remote with one plan bead."""

    remote = tmp_path / "beads.git"
    seed = tmp_path / "beads-seed"
    init_bare_repo(remote)
    clone(remote, seed)
    with BeadProject.init(seed, beads_dirname=BEADS_DIRNAME_ROOT) as project:
        issue = project.create("Linked plan", IssueType.PLAN)
        issue_id = issue.id
    commit_all(seed, "seed beads")
    git(["push", "-u", "origin", "main"], seed)
    return remote, issue_id


def _write_link_index(
    repo: Path, artifact_ref: str, *, rows: list[dict[str, object]]
) -> Path:
    path = sidecar_index_path(repo, artifact_ref)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {"schema_version": 2, "artifact_ref": artifact_ref, "rows": rows},
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def _row() -> dict[str, object]:
    return {
        "schema_version": 2,
        "source_ref": "agent:planner.coder",
        "relation": "read",
        "target_ref": "research:202609/old.md",
        "description": "reads the fixture document",
        "origin": "read",
        "created_by": "sase",
        "created_at": "2026-09-06T00:00:00Z",
        "uses": 1,
    }


class TestHiddenCloneWritesConvergeToPrimaryViaAutoSync:
    def test_rename_repair_commits_in_the_hidden_clone_and_primary_fast_forwards(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SASE_HOME", str(tmp_path / "state"))

        plans_remote = _seeded_role_remote(tmp_path, "plans")
        research_remote = _seeded_role_remote(tmp_path, "research")

        # Seed the research artifact + link index directly on the remote, as
        # if a prior commit already landed it.
        research_seed = tmp_path / "research-seed"
        old_doc = research_seed / "202609" / "old.md"
        old_doc.parent.mkdir(parents=True)
        old_doc.write_text("# old\n", encoding="utf-8")
        _write_link_index(research_seed, "research:202609/old.md", rows=[_row()])
        commit_all(research_seed, "seed research artifact")
        git(["push"], research_seed)

        # A clean primary clone, behind the shared remote (never written to
        # directly by machine link maintenance).
        primary = tmp_path / "primary"
        primary.mkdir()
        write_sdd_store_record(
            primary,
            {
                "schema_version": 3,
                "storage": "sidecar_repos",
                "provider": "github",
                "sidecars": {
                    "plans": {
                        "repo": "acme/widget--plans",
                        "remote_url": str(plans_remote),
                    },
                    "research": {
                        "repo": "acme/widget--research",
                        "remote_url": str(research_remote),
                    },
                },
            },
        )
        primary_plans = primary / "sase" / "repos" / "plans"
        primary_research = primary / "sase" / "repos" / "research"
        clone(plans_remote, primary_plans)
        clone(research_remote, primary_research)
        assert (primary_research / "202609" / "old.md").is_file()

        # The ownership contract's hidden-sidecar recognition confirms a
        # role by resolving the project's primary checkout from its key.
        monkeypatch.setattr(
            "sase.bead.workspace.resolve_primary_workspace_for_project",
            lambda key: primary if key == _PROJECT_KEY else None,
        )

        # Resolve the hidden machine clone: freshly integrated from the
        # remote, entirely separate from the primary's own nested clone.
        hidden_store = resolve_machine_artifact_link_store(_PROJECT_KEY, primary)
        hidden_research = hidden_store.sidecar_roots["research"]
        assert hidden_research == Path(
            hidden_sidecar_clone_dir(_PROJECT_KEY, "research")
        )
        assert hidden_research != primary_research

        # A rename happens in the hidden clone (the machine lane).
        (hidden_research / "202609" / "old.md").rename(
            hidden_research / "202609" / "new.md"
        )
        git(["add", "-A"], hidden_research)
        git(["commit", "-m", "rename artifact"], hidden_research)

        report = repair_historical_artifact_renames(
            hidden_store, ("research:202609/old.md",)
        )
        assert [(r.old_ref, r.new_ref) for r in report.renames] == [
            ("research:202609/old.md", "research:202609/new.md")
        ]

        result = commit_artifact_link_indexes(
            report.changed_paths,
            store=hidden_store.sdd_store,
            repo_roots=tuple(hidden_store.sidecar_roots.values()),
            mutation_origin="machine",
            push_after_commit=True,
            verify_publication=False,
        )
        assert result.committed is True
        assert git(["status", "--short"], hidden_research).stdout == ""

        machine_head = git(["rev-parse", "HEAD"], hidden_research).stdout.strip()
        remote_head = git(["ls-remote", str(research_remote), "main"], tmp_path).stdout
        assert machine_head in remote_head

        # The primary's own nested clone was never touched directly...
        assert (primary_research / "202609" / "old.md").is_file()
        assert not (primary_research / "202609" / "new.md").exists()

        # ...it only converges through the existing pull-based auto-sync.
        project_file = _write_project_file(tmp_path / "demo.sase", primary=primary)
        monkeypatch.setattr(
            sidecar_auto_sync,
            "_resolved_sidecar_entries",
            lambda *_a, **_kw: [
                _entry("plans", remote_url=str(plans_remote)),
                _entry("research", remote_url=str(research_remote)),
            ],
        )

        sync_result = sync_primary_sidecar_role(
            "demo",
            "research",
            project_file=project_file,
            config={"workspace": {"root": "adjacent", "project_key": "demo"}},
        )

        assert sync_result.status == "refreshed"
        assert git(["rev-parse", "HEAD"], primary_research).stdout.strip() == (
            machine_head
        )
        assert (primary_research / "202609" / "new.md").is_file()
        assert not (primary_research / "202609" / "old.md").exists()
        assert git(["status", "--short"], primary_research).stdout == ""

        # Explicit coverage: plans and research are both included in
        # auto-sync role discovery, not just the role this test mutated.
        roles = auto_sync_roles(str(primary))
        assert "plans" in roles
        assert "research" in roles

    def test_derived_plan_bead_link_commits_hidden_beads_without_dirtying_primary(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SASE_HOME", str(tmp_path / "state"))

        plans_remote = _seeded_role_remote(tmp_path, "plans")
        beads_remote, bead_id = _seeded_beads_remote(tmp_path)
        plans_seed = tmp_path / "plans-seed"
        linked_plan = plans_seed / "202609" / "linked.md"
        linked_plan.parent.mkdir(parents=True)
        linked_plan.write_text(
            "---\ntier: tale\nbead_id: " + bead_id + "\n---\n\nbody\n",
            encoding="utf-8",
        )
        commit_all(plans_seed, "seed linked plan")
        git(["push"], plans_seed)

        primary = tmp_path / "primary"
        primary.mkdir()
        write_sdd_store_record(
            primary,
            {
                "schema_version": 3,
                "storage": "sidecar_repos",
                "provider": "github",
                "sidecars": {
                    "plans": {
                        "repo": "acme/widget--plans",
                        "remote_url": str(plans_remote),
                    },
                    "beads": {
                        "repo": "acme/widget--beads",
                        "remote_url": str(beads_remote),
                    },
                },
            },
        )
        primary_plans = primary / "sase" / "repos" / "plans"
        primary_beads = primary / "sase" / "repos" / "beads"
        clone(plans_remote, primary_plans)
        clone(beads_remote, primary_beads)
        primary_beads_head = git(["rev-parse", "HEAD"], primary_beads).stdout.strip()
        assert git(["status", "--short"], primary_beads).stdout == ""

        monkeypatch.setattr(
            "sase.bead.workspace.resolve_primary_workspace_for_project",
            lambda key: primary if key == _PROJECT_KEY else None,
        )

        hidden_store = resolve_machine_artifact_link_store(_PROJECT_KEY, primary)
        hidden_beads = hidden_store.beads_dir
        assert hidden_beads == Path(hidden_sidecar_clone_dir(_PROJECT_KEY, "beads"))
        assert hidden_beads != primary_beads
        assert hidden_beads is not None

        producer = artifact_link_derived_producer_id()
        append_artifact_link_outbox_entry(
            project_key=_PROJECT_KEY,
            agent_name=producer,
            run_id=artifact_link_machine_run_id(),
            row={
                "schema_version": 2,
                "source_ref": "plan:202609/linked.md",
                "relation": "implements",
                "target_ref": f"bead:{bead_id}",
                "description": ("derived from the plan's `bead_id:` frontmatter field"),
                "origin": "derived",
                "created_by": producer,
                "created_at": "1970-01-01T00:00:00Z",
                "uses": 1,
            },
        )

        report = drain_artifact_link_outbox(
            store=hidden_store,
            agent_name=producer,
            drop_stale_terminal=False,
            push_after_commit=True,
        )

        assert report.drained == 1
        assert report.publication_error is None
        assert report.skip_diagnostics == ()
        assert git(["status", "--short"], hidden_beads).stdout == ""
        hidden_beads_head = git(["rev-parse", "HEAD"], hidden_beads).stdout.strip()
        assert hidden_beads_head != primary_beads_head
        remote_head = git(["ls-remote", str(beads_remote), "main"], tmp_path).stdout
        assert hidden_beads_head in remote_head

        with BeadProject(hidden_beads, beads_dirname=BEADS_DIRNAME_ROOT) as project:
            linked = project.show(bead_id)
        assert {
            (link.target_ref, link.relation, link.direction) for link in linked.links
        } == {("plan:202609/linked.md", "implements", "in")}

        assert git(["rev-parse", "HEAD"], primary_beads).stdout.strip() == (
            primary_beads_head
        )
        assert git(["status", "--short"], primary_beads).stdout == ""
