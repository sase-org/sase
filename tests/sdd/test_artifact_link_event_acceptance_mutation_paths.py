"""Acceptance coverage for public artifact-link mutation callers.

The audit found that manual ``link add``/``rm`` and the plan inlet passed
the checkout-resolved store straight to ``publish_artifact_link_events``,
never switching to a hidden machine clone. These tests exercise the real
public entry points -- ``add_artifact_link``/``remove_artifact_link`` from
``artifact_cli/link_ops.py`` -- against genuinely separate agent-checkout
and hidden-machine store instances, each backed by its own real git clone,
so a regression that dirties the agent's checkout is caught.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from sase.artifact_cli.link_ops import add_artifact_link, remove_artifact_link
from sase.bead._sync_publication import PushOutcome
from sase.sdd.artifact_link_inlet import (
    parse_plan_artifact_link_inlet,
    publish_plan_artifact_link_inlet,
)
from sase.sdd.artifact_link_store import ArtifactLinkStore
from sase.sdd.store import SddStore
from tests._conftest_environment import redirect_sase_home
from tests.sdd._artifact_link_store_helpers import allow_machine_sidecar_writes
from tests.sdd_store._helpers import clone, commit_all, git, init_bare_repo

PROJECT_KEY = "gh_sase-org__sase"


def test_cli_add_and_rm_route_through_hidden_store_leaving_agent_checkout_clean(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    allow_machine_sidecar_writes(monkeypatch)
    plans_remote = _seed_remote(tmp_path, "plans", "202609/a.md")

    agent_checkout = tmp_path / "agent-checkout" / "plans"
    hidden_clone = tmp_path / "hidden-clone" / "plans"
    clone(plans_remote, agent_checkout)
    clone(plans_remote, hidden_clone)

    checkout_store = ArtifactLinkStore(
        project_key=PROJECT_KEY,
        sidecar_roots={"plan": agent_checkout},
    )
    hidden_store = _pushable_store(hidden_clone, remote=plans_remote)
    monkeypatch.setattr(
        "sase.artifact_cli.link_ops.resolve_artifact_link_store",
        lambda: checkout_store,
    )
    monkeypatch.setattr(
        "sase.artifact_cli.link_ops.resolve_machine_artifact_link_store",
        lambda _project_key, _cwd: hidden_store,
    )
    monkeypatch.setattr(
        "sase.artifact_cli.link_ops._created_by",
        lambda: "bbugyi200.athena.y2",
    )
    monkeypatch.setattr(
        "sase.artifact_cli.link_ops._created_at",
        lambda: "2026-09-10T00:00:00Z",
    )

    outcome = add_artifact_link(
        source_ref="plan:202609/a.md",
        relation="implements",
        target_ref="plan:202609/b.md",
        why="acceptance coverage for hidden-store routing",
    )

    assert outcome["kind"] == "added"
    assert _git_status(agent_checkout) == ""
    assert not (agent_checkout / "link-events").exists()
    assert _git_status(hidden_clone) == ""
    [installed] = hidden_clone.glob("link-events/v1/**/*.json")
    assert installed.exists()

    remote_head = git(["rev-parse", "main"], plans_remote).stdout.strip()
    assert git(["rev-parse", "HEAD"], hidden_clone).stdout.strip() == remote_head

    fresh = tmp_path / "fresh" / "plans"
    clone(plans_remote, fresh)
    fresh_store = ArtifactLinkStore(
        project_key=PROJECT_KEY, sidecar_roots={"plan": fresh}
    )
    [row] = fresh_store.load_durable_rows()
    assert row["source_ref"] == "plan:202609/a.md"
    assert row["target_ref"] == "plan:202609/b.md"
    assert row["relation"] == "implements"

    remove_outcome = remove_artifact_link(
        source_ref="plan:202609/a.md",
        target_ref="plan:202609/b.md",
    )

    assert [row["relation"] for row in remove_outcome["rows"]] == ["implements"]
    assert _git_status(agent_checkout) == ""
    assert not (agent_checkout / "link-events").exists()
    assert _git_status(hidden_clone) == ""


def test_cli_already_absent_rm_retry_publishes_failed_remove_commit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    allow_machine_sidecar_writes(monkeypatch)
    plans_remote = _seed_remote(tmp_path, "plans", "202609/a.md")

    agent_checkout = tmp_path / "agent-checkout" / "plans"
    hidden_clone = tmp_path / "hidden-clone" / "plans"
    clone(plans_remote, agent_checkout)
    clone(plans_remote, hidden_clone)

    checkout_store = ArtifactLinkStore(
        project_key=PROJECT_KEY,
        sidecar_roots={"plan": agent_checkout},
    )
    hidden_store = _pushable_store(hidden_clone, remote=plans_remote)
    monkeypatch.setattr(
        "sase.artifact_cli.link_ops.resolve_artifact_link_store",
        lambda: checkout_store,
    )
    monkeypatch.setattr(
        "sase.artifact_cli.link_ops.resolve_machine_artifact_link_store",
        lambda _project_key, _cwd: hidden_store,
    )
    monkeypatch.setattr(
        "sase.artifact_cli.link_ops._created_by",
        lambda: "bbugyi200.athena.y2",
    )
    monkeypatch.setattr(
        "sase.artifact_cli.link_ops._created_at",
        lambda: "2026-09-10T00:00:00Z",
    )
    refs = {
        "source_ref": "plan:202609/a.md",
        "target_ref": "plan:202609/b.md",
    }

    add_artifact_link(
        **refs,
        relation="implements",
        why="seed edge for absent-remove publication retry",
    )

    def _reject_push(
        _repo_root: Path,
        *,
        worker_lock_wait: float = 0.0,
        deadline: float | None = None,
    ) -> PushOutcome:
        return PushOutcome(
            pushed=False,
            skipped_no_remote=False,
            error="simulated remove publication failure",
        )

    with monkeypatch.context() as patch:
        patch.setattr("sase.bead.sync.push_bead_work_launch", _reject_push)
        with pytest.raises(RuntimeError, match="NOT published"):
            remove_artifact_link(**refs)

    assert (
        git(["rev-list", "--count", "origin/main..HEAD"], hidden_clone).stdout.strip()
        == "1"
    )
    retry = remove_artifact_link(**refs)

    assert retry["rows"] == ()
    assert _git_status(agent_checkout) == ""
    assert not (agent_checkout / "link-events").exists()
    assert _git_status(hidden_clone) == ""
    assert (
        git(["rev-parse", "HEAD"], hidden_clone).stdout.strip()
        == git(
            ["rev-parse", "origin/main"],
            hidden_clone,
        ).stdout.strip()
    )

    fresh = tmp_path / "fresh" / "plans"
    clone(plans_remote, fresh)
    fresh_store = ArtifactLinkStore(
        project_key=PROJECT_KEY,
        sidecar_roots={"plan": fresh},
    )
    assert fresh_store.load_durable_rows() == ()


def test_cli_add_with_an_unresolvable_owner_stays_pending_and_mutates_nothing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    allow_machine_sidecar_writes(monkeypatch)
    plans_remote = _seed_remote(tmp_path, "plans", "202609/a.md")

    agent_checkout = tmp_path / "agent-checkout" / "plans"
    hidden_clone = tmp_path / "hidden-clone" / "plans"
    clone(plans_remote, agent_checkout)
    clone(plans_remote, hidden_clone)

    checkout_store = ArtifactLinkStore(
        project_key=PROJECT_KEY,
        sidecar_roots={"plan": agent_checkout, "research": agent_checkout},
    )
    # The hidden store cannot resolve a "research" owner: its owner can
    # never be confirmed durable, so the mutation must stay pending rather
    # than falsely acknowledging a write nobody can see.
    hidden_store = replace(
        _pushable_store(hidden_clone, remote=plans_remote),
        unresolved_document_kinds={"research": "research hidden clone is unavailable"},
    )
    monkeypatch.setattr(
        "sase.artifact_cli.link_ops.resolve_artifact_link_store",
        lambda: checkout_store,
    )
    monkeypatch.setattr(
        "sase.artifact_cli.link_ops.resolve_machine_artifact_link_store",
        lambda _project_key, _cwd: hidden_store,
    )
    monkeypatch.setattr(
        "sase.artifact_cli.link_ops._created_by",
        lambda: "bbugyi200.athena.y2",
    )
    monkeypatch.setattr(
        "sase.artifact_cli.link_ops._created_at",
        lambda: "2026-09-10T00:00:00Z",
    )

    with pytest.raises(RuntimeError):
        add_artifact_link(
            source_ref="plan:202609/a.md",
            relation="related",
            target_ref="research:202609/unresolved.md",
            why="acceptance coverage for unresolved owner rejection",
        )

    assert _git_status(agent_checkout) == ""
    assert not (agent_checkout / "link-events").exists()
    # The resolvable "plan" side may durably record the event object -- the
    # audited repair is that this must never be mistaken for a completed,
    # acknowledged operation while the "research" owner stays unresolved.
    assert _git_status(hidden_clone) == ""
    assert hidden_store.load_aggregate().get("rows", []) == []


def test_plan_link_inlet_routes_events_through_hidden_store(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    allow_machine_sidecar_writes(monkeypatch)
    plans_remote = _seed_remote(
        tmp_path,
        "plans",
        "202609/linked.md",
        "202609/target.md",
    )

    agent_checkout = tmp_path / "agent-checkout" / "plans"
    hidden_clone = tmp_path / "hidden-clone" / "plans"
    archive = tmp_path / "archive" / "202609" / "linked.md"
    clone(plans_remote, agent_checkout)
    clone(plans_remote, hidden_clone)
    archive.parent.mkdir(parents=True)
    archive.write_text(
        "---\n"
        "links:\n"
        "  - ref: plan:202609/target.md\n"
        "    relation: related\n"
        "    description: plan inlet hidden-store publication\n"
        "---\n"
        "# Linked plan\n",
        encoding="utf-8",
    )

    checkout_store = ArtifactLinkStore.from_sdd_store(
        SddStore(
            "sidecar_repos",
            agent_checkout,
            agent_checkout,
            provider="github",
            remote_url=str(plans_remote),
        ),
        PROJECT_KEY,
    )
    hidden_store = _pushable_store(hidden_clone, remote=plans_remote)
    monkeypatch.setattr(
        "sase.sdd.artifact_link_inlet._created_by",
        lambda: "bbugyi200.athena.y2",
    )
    monkeypatch.setattr(
        "sase.sdd.artifact_link_inlet._created_at",
        lambda: "2026-09-10T00:00:00Z",
    )
    inlet = parse_plan_artifact_link_inlet(archive.read_text(encoding="utf-8"))

    [row] = publish_plan_artifact_link_inlet(
        archive,
        source_ref="plan:202609/linked.md",
        inlet=inlet,
        store=checkout_store,
        publication_store=hidden_store,
    )

    assert row["target_ref"] == "plan:202609/target.md"
    assert "<!-- sase:links:start -->" in archive.read_text(encoding="utf-8")
    assert _git_status(agent_checkout) == ""
    assert not (agent_checkout / "link-events").exists()
    assert not (agent_checkout / "links").exists()
    assert _git_status(hidden_clone) == ""
    [installed] = hidden_clone.glob("link-events/v1/**/*.json")
    assert installed.exists()

    fresh = tmp_path / "fresh-inlet" / "plans"
    clone(plans_remote, fresh)
    fresh_store = ArtifactLinkStore(
        project_key=PROJECT_KEY,
        sidecar_roots={"plan": fresh},
    )
    [durable] = fresh_store.load_durable_rows()
    assert durable["source_ref"] == "plan:202609/linked.md"
    assert durable["relation"] == "related"
    assert durable["target_ref"] == "plan:202609/target.md"


def _seed_remote(tmp_path: Path, role: str, *documents: str) -> Path:
    remote = tmp_path / "remotes" / f"{role}.git"
    seed = tmp_path / "seeds" / role
    init_bare_repo(remote)
    clone(remote, seed)
    for relpath in documents:
        path = seed / relpath
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"# {relpath}\n", encoding="utf-8")
    commit_all(seed, f"seed {role}")
    git(["push", "-u", "origin", "main"], seed)
    return remote


def _pushable_store(root: Path, *, remote: Path) -> ArtifactLinkStore:
    sdd_store = SddStore(
        "sidecar_repos",
        root,
        root,
        provider="github",
        remote_url=str(remote),
    )
    return ArtifactLinkStore.from_sdd_store(sdd_store, PROJECT_KEY)


def _git_status(repo: Path) -> str:
    return git(["status", "--porcelain=v1", "--untracked-files=all"], repo).stdout
