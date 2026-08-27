"""Best-effort hosted GitHub URLs for plans, agents, commits, and beads.

Resolution composes the existing remote sanitizers, sidecar target
resolution, and agent link targets rather than re-deriving any of them. It is
local-only, never raises, and returns ``None`` instead of guessing, so a store
without an authoritative hosted remote degrades to an unlinked label instead
of a broken URL.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import os
from pathlib import Path
from typing import TYPE_CHECKING

from sase._git_remote import github_blob_url, github_commit_url
from sase.sdd.checkout_anchor import resolve_checkout_anchor

if TYPE_CHECKING:
    from sase.agents_sync.git import GitRunner
    from sase.core.agent_identity_facade import AgentIdentitySnapshot
    from sase.sdd.store import SddStore

_BRANCH_OP = "sdd.hosted_links.branch"
_ORIGIN_BRANCH_OP = "sdd.hosted_links.origin_branch"
_REMOTE_OP = "sdd.hosted_links.remote"


def resolve_hosted_branch(
    repo: Path,
    *,
    git_runner: GitRunner | None = None,
) -> str | None:
    """Return the branch that hosted links into *repo* should point at.

    The checked-out branch wins. A detached clone falls back to the recorded
    ``origin/HEAD`` default so a bare fetch still links somewhere real; a repo
    with neither resolves to ``None`` rather than an invented ``main``.
    """

    runner = git_runner or _default_git_runner()
    current = _symbolic_ref(repo, "HEAD", runner, op=_BRANCH_OP)
    if current:
        return current.removeprefix("refs/heads/")
    origin = _symbolic_ref(
        repo,
        "refs/remotes/origin/HEAD",
        runner,
        op=_ORIGIN_BRANCH_OP,
    )
    if not origin:
        return None
    if origin.startswith("refs/remotes/"):
        origin = origin[len("refs/remotes/") :]
    return origin.removeprefix("origin/") or None


def resolve_origin_remote_url(
    repo: Path,
    *,
    git_runner: GitRunner | None = None,
) -> str | None:
    """Return *repo*'s ``origin`` remote URL, or ``None`` when unresolvable."""

    return _origin_remote_url(repo, git_runner or _default_git_runner())


@dataclass(frozen=True, slots=True)
class _RemoteCoordinates:
    """One repository's remote, provider, and — for blob links — branch."""

    remote_url: str
    provider: str | None
    branch: str | None = None


class HostedLinkResolver:
    """Resolve plan, agent, commit, and bead identities to GitHub URLs.

    One resolver serves an entire tree-wide refresh: every remote, provider,
    and branch lookup is memoized, so resolving thousands of plans or beads
    shells out to git a constant number of times.
    """

    def __init__(
        self,
        store: SddStore,
        *,
        project: str | None = None,
        primary_root: Path | str | None = None,
        git_runner: GitRunner | None = None,
    ) -> None:
        self._store = store
        self._project = project
        self._primary_root = Path(
            primary_root if primary_root is not None else os.getcwd()
        ).resolve(strict=False)
        self._git_runner = git_runner or _default_git_runner()
        self._remotes: dict[str, _RemoteCoordinates | None] = {}
        self._identity: AgentIdentitySnapshot | None = None
        self._identity_resolved = False
        self._agents_sidecar_path: Path | None = None
        self._reserved_family_names: frozenset[str] | None = None

    def snapshot_agent_name_registry(self) -> None:
        """Refresh family-name state once for a batch of agent-link lookups.

        This is a rendering read: the answer only shapes a URL, so it takes
        the display-tier registry load. The reservation-tier load would force
        a rebuild whenever the registry looks stale, and that rebuild holds
        the name-allocation flock long enough to stall a concurrent launch.
        """

        try:
            from sase.agent.names import get_reserved_family_names_for_display

            self._reserved_family_names = frozenset(
                get_reserved_family_names_for_display()
            )
        except Exception:
            self._reserved_family_names = frozenset()

    def plan_url(self, plan_ref: str) -> str | None:
        """Return the plans sidecar blob URL for *plan_ref*."""

        path = _plan_repo_relative_path(self._store, plan_ref)
        if path is None:
            return None
        coordinates = self._plans_remote()
        if coordinates is None or coordinates.branch is None:
            return None
        return github_blob_url(
            coordinates.remote_url,
            provider=coordinates.provider,
            branch=coordinates.branch,
            path=path,
        )

    def prompt_url(self, prompt_ref: str) -> str | None:
        """Return the agents-sidecar blob URL for one archived prompt."""

        path = _prompt_repo_relative_path(prompt_ref)
        if path is None:
            return None
        coordinates = self._agents_remote()
        if coordinates is None or coordinates.branch is None:
            return None
        return github_blob_url(
            coordinates.remote_url,
            provider=coordinates.provider,
            branch=coordinates.branch,
            path=path,
        )

    def agent_url(self, agent_name: str) -> str | None:
        """Return the agents sidecar page URL for *agent_name*."""

        from sase.core.agent_identity_facade import (
            AgentFamilyNameKind,
            agent_link_target,
            normalize_owned_agent_name,
            parse_agent_family_name,
        )
        from sase.sase_agent import sase_agent_page_path, sase_agent_ref_for_name

        snapshot = self._agent_identity()
        owner = None if snapshot is None else snapshot.owner
        if owner is None:
            return None
        coordinates = self._agents_remote()
        if coordinates is None or coordinates.branch is None:
            return None
        try:
            local_name = normalize_owned_agent_name(agent_name, snapshot)
            parsed = parse_agent_family_name(local_name)
            if parsed.kind is AgentFamilyNameKind.MEMBER:
                link_target = agent_link_target(local_name, owner)
                path = link_target.path
            else:
                agent_ref = sase_agent_ref_for_name(
                    local_name,
                    snapshot,
                    reserved_family_names=self._reserved_family_names,
                )
                path = sase_agent_page_path(agent_ref, owner)
                family_path = f"families/{agent_ref.global_name}.md"
                if (
                    not agent_ref.is_family
                    and self._agents_sidecar_path is not None
                    and (self._agents_sidecar_path / family_path).is_file()
                ):
                    path = family_path
        except Exception:
            return None
        return github_blob_url(
            coordinates.remote_url,
            provider=coordinates.provider,
            branch=coordinates.branch,
            path=path,
        )

    def bead_url(self, bead_id: str) -> str | None:
        """Return the beads sidecar page URL for *bead_id*."""

        from sase.bead_pages.paths import bead_page_path

        try:
            path = bead_page_path(bead_id)
        except ValueError:
            return None
        coordinates = self._beads_remote()
        if coordinates is None or coordinates.branch is None:
            return None
        return github_blob_url(
            coordinates.remote_url,
            provider=coordinates.provider,
            branch=coordinates.branch,
            path=path,
        )

    def commit_url(self, sha: str) -> str | None:
        """Return the primary repository's commit URL for *sha*."""

        return self.commit_url_for_repository(self._primary_root, sha)

    def commit_url_for_repository(
        self,
        repository_root: Path | str,
        sha: str,
    ) -> str | None:
        """Return *sha*'s URL against the owning repository's remote."""

        root = Path(repository_root).expanduser().resolve(strict=False)
        coordinates = self._repository_remote(root)
        if coordinates is None:
            return None
        return github_commit_url(
            coordinates.remote_url,
            provider=coordinates.provider,
            sha=sha.strip().casefold(),
        )

    def blob_url_for_repository(
        self,
        repository_root: Path | str,
        revision: str,
        path: str,
    ) -> str | None:
        """Return an immutable hosted blob URL for one repository path."""

        root = Path(repository_root).expanduser().resolve(strict=False)
        coordinates = self._repository_remote(root)
        if coordinates is None:
            return None
        return github_blob_url(
            coordinates.remote_url,
            provider=coordinates.provider,
            branch=revision.strip(),
            path=path,
        )

    def _plans_remote(self) -> _RemoteCoordinates | None:
        return self._memoized("plans", self._resolve_plans_remote)

    def _beads_remote(self) -> _RemoteCoordinates | None:
        return self._memoized("beads", self._resolve_beads_remote)

    def _agents_remote(self) -> _RemoteCoordinates | None:
        return self._memoized("agents", self._resolve_agents_remote)

    def _primary_remote(self) -> _RemoteCoordinates | None:
        return self._repository_remote(self._primary_root)

    def _repository_remote(self, root: Path) -> _RemoteCoordinates | None:
        return self._memoized(
            f"commit:{root}",
            lambda: self._resolve_repository_remote(root),
        )

    def _memoized(
        self,
        key: str,
        resolve: Callable[[], _RemoteCoordinates | None],
    ) -> _RemoteCoordinates | None:
        if key not in self._remotes:
            try:
                self._remotes[key] = resolve()
            except Exception:
                self._remotes[key] = None
        return self._remotes[key]

    def _resolve_plans_remote(self) -> _RemoteCoordinates | None:
        store = self._store
        if store.is_in_tree or not store.remote_url:
            return None
        repo_root = store.repo_root_for_kind("plans")
        branch = resolve_hosted_branch(repo_root, git_runner=self._git_runner)
        if branch is None:
            return None
        return _RemoteCoordinates(store.remote_url, store.provider, branch)

    def _resolve_beads_remote(self) -> _RemoteCoordinates | None:
        store = self._store
        if store.beads_dir is None or not store.beads_remote_url:
            return None
        repo_root = store.repo_root_for_kind("beads")
        branch = resolve_hosted_branch(repo_root, git_runner=self._git_runner)
        if branch is None:
            return None
        return _RemoteCoordinates(store.beads_remote_url, store.provider, branch)

    def _resolve_agents_remote(self) -> _RemoteCoordinates | None:
        from sase.agents_sync.links import hosted_provider
        from sase.agents_sync.targets import resolve_sync_targets

        anchor = resolve_checkout_anchor(self._primary_root)
        project = self._project or anchor.project_name
        if not project:
            return None
        selection = resolve_sync_targets((project,))
        if len(selection.targets) != 1:
            return None
        target = selection.targets[0]
        if target.primary_roots and not any(
            anchor.primary_root == root or anchor.primary_root.is_relative_to(root)
            for root in target.primary_roots
        ):
            return None
        if not (target.sidecar_path / ".git").exists():
            return None
        self._agents_sidecar_path = target.sidecar_path
        branch = resolve_hosted_branch(
            target.sidecar_path,
            git_runner=self._git_runner,
        )
        if branch is None:
            return None
        return _RemoteCoordinates(
            target.remote_url,
            hosted_provider(target.remote_url),
            branch,
        )

    def _resolve_repository_remote(
        self,
        root: Path,
    ) -> _RemoteCoordinates | None:
        from sase.agents_sync.links import hosted_provider

        remote = _origin_remote_url(root, self._git_runner)
        if not remote:
            return None
        # Commit URLs name an immutable object, so no branch is resolved.
        return _RemoteCoordinates(remote, hosted_provider(remote))

    def _agent_identity(self) -> AgentIdentitySnapshot | None:
        if not self._identity_resolved:
            from sase.core.agent_identity_facade import AgentIdentitySnapshot

            self._identity_resolved = True
            try:
                self._identity = AgentIdentitySnapshot.current()
            except Exception:
                self._identity = None
        return self._identity


_RESOLVERS: dict[tuple[str, str, str], HostedLinkResolver] = {}


def hosted_link_resolver(
    store: SddStore,
    *,
    project: str | None = None,
    primary_root: Path | str | None = None,
) -> HostedLinkResolver:
    """Return the process-cached resolver for one store and checkout.

    Callers that resolve links for many plans must go through this factory so
    the remote, provider, and branch lookups happen once per process run.
    """

    root = Path(primary_root if primary_root is not None else os.getcwd()).resolve(
        strict=False
    )
    key = (str(store.repo_root), project or "", str(root))
    resolver = _RESOLVERS.get(key)
    if resolver is None:
        resolver = HostedLinkResolver(store, project=project, primary_root=root)
        _RESOLVERS[key] = resolver
    return resolver


def _plan_repo_relative_path(store: SddStore, plan_ref: str) -> str | None:
    """Return *plan_ref* as a path relative to the owning plans repository."""

    from sase.sdd.plan_refs import PLAN_REFERENCE_KIND, parse_plan_reference

    raw = plan_ref.strip()
    if not raw:
        return None
    try:
        parsed = parse_plan_reference(raw)
    except Exception:
        return None
    if parsed.kind != PLAN_REFERENCE_KIND or not parsed.path.strip():
        return None

    if not parsed.legacy:
        candidate = store.kind_root("plans") / parsed.path
    else:
        candidate = Path(parsed.path).expanduser()
        if not candidate.is_absolute():
            # Legacy tag values are already relative to the owning repository.
            return Path(parsed.path).as_posix()
    repo_root = store.repo_root_for_kind("plans").expanduser().resolve(strict=False)
    resolved = candidate.resolve(strict=False)
    if not resolved.is_relative_to(repo_root):
        return None
    return resolved.relative_to(repo_root).as_posix()


def _prompt_repo_relative_path(prompt_ref: str) -> str | None:
    """Normalize one canonical ``prompts/<YYYYMM>/<name>.md`` reference."""

    from sase.agents_sync.prompt_archive.paths import prompt_document_path

    raw = prompt_ref.strip().removeprefix("agents:").removeprefix("./")
    parts = Path(raw).parts
    if len(parts) != 3 or parts[0] != "prompts":
        return None
    try:
        expected = prompt_document_path(Path("."), parts[1], parts[2])
    except ValueError:
        return None
    normalized = expected.relative_to(Path(".")).as_posix()
    return normalized if normalized == Path(raw).as_posix() else None


def _default_git_runner() -> GitRunner:
    """Load the agents-sync git boundary after this module is initialized."""

    from sase.agents_sync.git import run_git

    return run_git


def _origin_remote_url(repo: Path, git_runner: GitRunner) -> str | None:
    if not (repo / ".git").exists():
        return None
    try:
        result = git_runner(
            repo,
            ["remote", "get-url", "origin"],
            op=_REMOTE_OP,
        )
    except Exception:
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def _symbolic_ref(
    repo: Path,
    ref: str,
    git_runner: GitRunner,
    *,
    op: str,
) -> str | None:
    try:
        result = git_runner(
            repo,
            ["symbolic-ref", "--quiet", "--short", ref],
            op=op,
        )
    except Exception:
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


__all__ = [
    "HostedLinkResolver",
    "hosted_link_resolver",
    "resolve_hosted_branch",
    "resolve_origin_remote_url",
]
