"""Tests for best-effort hosted GitHub links for plans, agents, and commits."""

from __future__ import annotations

from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

from sase.agents_sync.models import ProjectTarget, TargetSelection
from sase.core.agent_identity_facade import AgentIdentitySnapshot, AgentOwnerIdentity
from sase.sdd.hosted_links import (
    HostedLinkResolver,
    hosted_link_resolver,
    resolve_hosted_branch,
)
from sase.sdd.store import SddStore

_GITHUB_BEADS_REMOTE = "git@github.com:sase-org/sase--beads.git"
_GITHUB_PLANS_REMOTE = "git@github.com:sase-org/sase--plans.git"
_GITHUB_AGENTS_REMOTE = "git@github.com:sase-org/sase--agents.git"
_GITHUB_PRIMARY_REMOTE = "git@github.com:sase-org/sase.git"


class _FakeGit:
    """Deterministic git boundary that records every invocation."""

    def __init__(
        self,
        *,
        branches: dict[Path, str] | None = None,
        remotes: dict[Path, str] | None = None,
    ) -> None:
        self.branches = branches or {}
        self.remotes = remotes or {}
        self.calls: list[tuple[Path, tuple[str, ...]]] = []

    def __call__(
        self,
        cwd: Path,
        args: list[str],
        *,
        network: bool = False,
        op: str = "",
    ) -> subprocess.CompletedProcess[str]:
        del network, op
        self.calls.append((Path(cwd), tuple(args)))
        if args[:3] == ["symbolic-ref", "--quiet", "--short"]:
            if args[3] == "HEAD":
                branch = self.branches.get(Path(cwd))
                if branch:
                    return subprocess.CompletedProcess(args, 0, f"{branch}\n", "")
            return subprocess.CompletedProcess(args, 1, "", "")
        if args[:2] == ["remote", "get-url"]:
            remote = self.remotes.get(Path(cwd))
            if remote:
                return subprocess.CompletedProcess(args, 0, f"{remote}\n", "")
            return subprocess.CompletedProcess(args, 1, "", "")
        raise AssertionError(args)


def _plans_store(
    root: Path, *, remote_url: str | None = _GITHUB_PLANS_REMOTE
) -> SddStore:
    root.mkdir(parents=True, exist_ok=True)
    return SddStore(
        "sidecar_repos",
        root,
        root,
        provider="github" if remote_url else None,
        remote_url=remote_url,
    )


def _beads_store(
    root: Path, *, remote_url: str | None = _GITHUB_BEADS_REMOTE
) -> SddStore:
    """Return a sidecar store whose beads clone lives beside the plans one."""

    plans = root / "plans"
    beads = root / "beads"
    plans.mkdir(parents=True, exist_ok=True)
    beads.mkdir(parents=True, exist_ok=True)
    return SddStore(
        "sidecar_repos",
        plans,
        plans,
        provider="github",
        remote_url=_GITHUB_PLANS_REMOTE,
        beads_dir=beads if remote_url else None,
        beads_remote_url=remote_url,
    )


def _agents_target(primary: Path, sidecar: Path, remote: str) -> ProjectTarget:
    (sidecar / ".git").mkdir(parents=True, exist_ok=True)
    return ProjectTarget(
        "sase",
        "sase",
        primary,
        (primary.resolve(),),
        sidecar,
        remote,
    )


def test_plan_url_resolves_logical_reference_to_blob_url(tmp_path: Path) -> None:
    plans = tmp_path / "plans"
    store = _plans_store(plans)
    git = _FakeGit(branches={plans: "main"})

    resolver = HostedLinkResolver(store, primary_root=tmp_path, git_runner=git)

    assert resolver.plan_url("plans:202607/plan_header_provenance.md") == (
        "https://github.com/sase-org/sase--plans/blob/main/"
        "202607/plan_header_provenance.md"
    )


def test_plan_url_accepts_legacy_repo_relative_reference(tmp_path: Path) -> None:
    plans = tmp_path / "plans"
    store = _plans_store(plans)
    git = _FakeGit(branches={plans: "feature/plan-links"})

    resolver = HostedLinkResolver(store, primary_root=tmp_path, git_runner=git)

    assert resolver.plan_url("202607/a plan #1.md") == (
        "https://github.com/sase-org/sase--plans/blob/"
        "feature%2Fplan-links/202607/a%20plan%20%231.md"
    )


def test_plan_url_rejects_reference_outside_the_plans_repository(
    tmp_path: Path,
) -> None:
    store = _plans_store(tmp_path / "plans")
    git = _FakeGit(branches={tmp_path / "plans": "main"})

    resolver = HostedLinkResolver(store, primary_root=tmp_path, git_runner=git)

    assert resolver.plan_url(str(tmp_path / "elsewhere" / "202607/plan.md")) is None


@pytest.mark.parametrize(
    "store_factory",
    [
        lambda root: SddStore("in_tree", root / "sdd", root),
        lambda root: SddStore(
            "sidecar_repos",
            root / "plans",
            root / "plans",
            provider=None,
            remote_url=None,
        ),
    ],
)
def test_plan_url_degrades_without_a_hosted_remote(
    tmp_path: Path, store_factory
) -> None:
    store = store_factory(tmp_path)
    resolver = HostedLinkResolver(
        store,
        primary_root=tmp_path,
        git_runner=_FakeGit(),
    )

    assert resolver.plan_url("plans:202607/plan.md") is None


def test_plan_url_degrades_when_no_branch_resolves(tmp_path: Path) -> None:
    plans = tmp_path / "plans"
    store = _plans_store(plans)

    resolver = HostedLinkResolver(store, primary_root=tmp_path, git_runner=_FakeGit())

    assert resolver.plan_url("plans:202607/plan.md") is None


def test_agent_url_links_family_member_anchor(tmp_path: Path, monkeypatch) -> None:
    primary = tmp_path / "primary"
    primary.mkdir()
    sidecar = tmp_path / "agents"
    target = _agents_target(primary, sidecar, _GITHUB_AGENTS_REMOTE)
    monkeypatch.setattr(
        "sase.agents_sync.targets.resolve_sync_targets",
        lambda _projects: TargetSelection((target,), ()),
    )
    monkeypatch.setattr(
        AgentIdentitySnapshot,
        "current",
        classmethod(
            lambda _cls: AgentIdentitySnapshot(AgentOwnerIdentity("alice", "athena"))
        ),
    )
    git = _FakeGit(branches={sidecar: "main"})

    resolver = HostedLinkResolver(
        _plans_store(tmp_path / "plans"),
        project="sase",
        primary_root=primary,
        git_runner=git,
    )

    assert resolver.agent_url("foo.bar--code") == (
        "https://github.com/sase-org/sase--agents/blob/main/"
        "families/alice.athena.foo.bar.md#member-code"
    )


def test_agent_url_resolves_project_from_sidecar_anchor(
    tmp_path: Path,
    monkeypatch,
) -> None:
    primary = tmp_path / "primary"
    sidecar_checkout = primary / "sase" / "repos" / "plans"
    sidecar_checkout.mkdir(parents=True)
    agents_sidecar = tmp_path / "agents"
    target = _agents_target(primary, agents_sidecar, _GITHUB_AGENTS_REMOTE)
    monkeypatch.setattr(
        "sase.sdd.hosted_links.resolve_checkout_anchor",
        lambda path: (
            SimpleNamespace(primary_root=primary, project_name="sase")
            if path == sidecar_checkout
            else SimpleNamespace(primary_root=path, project_name=None)
        ),
    )
    monkeypatch.setattr(
        "sase.agents_sync.targets.resolve_sync_targets",
        lambda _projects: TargetSelection((target,), ()),
    )
    monkeypatch.setattr(
        AgentIdentitySnapshot,
        "current",
        classmethod(
            lambda _cls: AgentIdentitySnapshot(AgentOwnerIdentity("alice", "athena"))
        ),
    )
    git = _FakeGit(branches={agents_sidecar: "main"})

    resolver = HostedLinkResolver(
        _plans_store(tmp_path / "plans"),
        primary_root=sidecar_checkout,
        git_runner=git,
    )

    assert resolver.agent_url("foo.bar") == (
        "https://github.com/sase-org/sase--agents/blob/main/"
        "agents/alice.athena.foo.bar/README.md"
    )


def test_agent_url_degrades_for_a_non_hosted_sidecar(
    tmp_path: Path,
    monkeypatch,
) -> None:
    primary = tmp_path / "primary"
    primary.mkdir()
    sidecar = tmp_path / "agents"
    target = _agents_target(primary, sidecar, str(tmp_path / "remote.git"))
    monkeypatch.setattr(
        "sase.agents_sync.targets.resolve_sync_targets",
        lambda _projects: TargetSelection((target,), ()),
    )
    monkeypatch.setattr(
        AgentIdentitySnapshot,
        "current",
        classmethod(
            lambda _cls: AgentIdentitySnapshot(AgentOwnerIdentity("alice", "athena"))
        ),
    )

    resolver = HostedLinkResolver(
        _plans_store(tmp_path / "plans"),
        project="sase",
        primary_root=primary,
        git_runner=_FakeGit(branches={sidecar: "main"}),
    )

    assert resolver.agent_url("foo.bar") is None


def test_commit_url_uses_the_primary_checkout_origin(tmp_path: Path) -> None:
    primary = tmp_path / "primary"
    (primary / ".git").mkdir(parents=True)
    git = _FakeGit(remotes={primary: _GITHUB_PRIMARY_REMOTE})

    resolver = HostedLinkResolver(
        _plans_store(tmp_path / "plans"),
        primary_root=primary,
        git_runner=git,
    )

    sha = "699456a521e25e0aaa38f4e289db38e71a6488a6"
    assert resolver.commit_url(sha) == (
        f"https://github.com/sase-org/sase/commit/{sha}"
    )


def test_commit_url_uses_and_memoizes_each_repository_origin(
    tmp_path: Path,
) -> None:
    primary = tmp_path / "sase"
    linked = tmp_path / "sase-core"
    for root in (primary, linked):
        (root / ".git").mkdir(parents=True)
    git = _FakeGit(
        remotes={
            primary: _GITHUB_PRIMARY_REMOTE,
            linked: "git@github.com:sase-org/sase-core.git",
        }
    )
    resolver = HostedLinkResolver(
        _plans_store(tmp_path / "plans"),
        primary_root=primary,
        git_runner=git,
    )
    sha = "699456a521e25e0aaa38f4e289db38e71a6488a6"

    assert resolver.commit_url_for_repository(linked, sha) == (
        f"https://github.com/sase-org/sase-core/commit/{sha}"
    )
    assert resolver.commit_url_for_repository(linked, sha) == (
        f"https://github.com/sase-org/sase-core/commit/{sha}"
    )
    assert git.calls == [
        (linked, ("remote", "get-url", "origin")),
    ]


def test_commit_url_degrades_for_a_malformed_sha_and_missing_origin(
    tmp_path: Path,
) -> None:
    primary = tmp_path / "primary"
    (primary / ".git").mkdir(parents=True)
    hosted = HostedLinkResolver(
        _plans_store(tmp_path / "plans"),
        primary_root=primary,
        git_runner=_FakeGit(remotes={primary: _GITHUB_PRIMARY_REMOTE}),
    )
    assert hosted.commit_url("not-a-sha") is None

    unhosted = HostedLinkResolver(
        _plans_store(tmp_path / "plans"),
        primary_root=primary,
        git_runner=_FakeGit(),
    )
    assert unhosted.commit_url("699456a") is None


def test_bead_url_resolves_a_page_in_the_beads_sidecar(tmp_path: Path) -> None:
    store = _beads_store(tmp_path)
    git = _FakeGit(branches={tmp_path / "beads": "main"})

    resolver = HostedLinkResolver(store, primary_root=tmp_path, git_runner=git)

    assert resolver.bead_url("sase-ai") == (
        "https://github.com/sase-org/sase--beads/blob/main/pages/sase-ai/README.md"
    )
    assert resolver.bead_url("sase-ai.1") == (
        "https://github.com/sase-org/sase--beads/blob/main/pages/sase-ai/sase-ai.1.md"
    )


@pytest.mark.parametrize(
    "store_factory",
    [
        lambda root: _beads_store(root, remote_url=None),
        lambda root: SddStore("in_tree", root / "sdd", root),
    ],
)
def test_bead_url_degrades_without_a_hosted_beads_sidecar(
    tmp_path: Path, store_factory
) -> None:
    resolver = HostedLinkResolver(
        store_factory(tmp_path),
        primary_root=tmp_path,
        git_runner=_FakeGit(branches={tmp_path / "beads": "main"}),
    )

    assert resolver.bead_url("sase-ai.1") is None


def test_bead_url_degrades_when_no_branch_resolves(tmp_path: Path) -> None:
    resolver = HostedLinkResolver(
        _beads_store(tmp_path),
        primary_root=tmp_path,
        git_runner=_FakeGit(),
    )

    assert resolver.bead_url("sase-ai.1") is None


def test_bead_url_degrades_for_an_id_that_cannot_address_a_page(
    tmp_path: Path,
) -> None:
    resolver = HostedLinkResolver(
        _beads_store(tmp_path),
        primary_root=tmp_path,
        git_runner=_FakeGit(branches={tmp_path / "beads": "main"}),
    )

    assert resolver.bead_url("  ") is None
    assert resolver.bead_url("sase-ai/../escape") is None


def test_bead_resolution_is_cached_across_many_beads(tmp_path: Path) -> None:
    git = _FakeGit(branches={tmp_path / "beads": "main"})
    resolver = HostedLinkResolver(
        _beads_store(tmp_path),
        primary_root=tmp_path,
        git_runner=git,
    )

    for index in range(50):
        assert resolver.bead_url(f"sase-ai.{index}") is not None

    assert len(git.calls) == 1


def test_resolution_is_cached_across_many_plans(tmp_path: Path) -> None:
    plans = tmp_path / "plans"
    store = _plans_store(plans)
    git = _FakeGit(branches={plans: "main"})
    resolver = HostedLinkResolver(store, primary_root=tmp_path, git_runner=git)

    for index in range(50):
        assert resolver.plan_url(f"plans:202607/plan_{index}.md") is not None

    assert len(git.calls) == 1


def test_hosted_link_resolver_reuses_one_resolver_per_store(tmp_path: Path) -> None:
    store = _plans_store(tmp_path / "plans")

    first = hosted_link_resolver(store, project="sase", primary_root=tmp_path)
    second = hosted_link_resolver(store, project="sase", primary_root=tmp_path)

    assert first is second


def test_resolve_hosted_branch_falls_back_to_recorded_origin_head(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()

    def runner(
        cwd: Path,
        args: list[str],
        *,
        network: bool = False,
        op: str = "",
    ) -> subprocess.CompletedProcess[str]:
        del cwd, network, op
        if args[3] == "HEAD":
            return subprocess.CompletedProcess(args, 1, "", "")
        return subprocess.CompletedProcess(args, 0, "origin/trunk\n", "")

    assert resolve_hosted_branch(repo, git_runner=runner) == "trunk"


def test_resolve_hosted_branch_returns_none_without_any_branch(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()

    assert resolve_hosted_branch(repo, git_runner=_FakeGit()) is None
