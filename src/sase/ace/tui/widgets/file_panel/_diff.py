"""VCS diff fetching for the file panel.

Phase 6 of the TUI perf overhaul adds dedupe + caching at this layer:

- ``_compute_diff_cache_key`` derives a stable key from the agent identity,
  workspace path, VCS provider, a worktree fingerprint (``.git/index``
  mtime/size, when present), and a TTL bucket.
- A module-level ``_diff_cache`` stores recent results so re-selecting the
  same active agent within a TTL window does not re-call
  ``diff_with_untracked``.

The TTL bucket is the **primary** invalidation signal because the underlying
call (``git diff HEAD`` + untracked walk) reflects the working tree, which
``.git/index`` does not track — the index only mutates on plumbing operations
like ``git add``/``git commit``. Without a TTL bucket the cache would stay
permanently warm while a running agent edits files in its workspace. The
``.git/index`` signature still acts as a secondary discriminator so a
stage/commit during a TTL window invalidates immediately.
"""

from __future__ import annotations

import os
import time
from datetime import datetime
from pathlib import Path
from threading import Lock

from sase.config.core import load_merged_config
from sase.vcs_provider import (
    VCSProvider,
    VCSProviderNotFoundError,
    get_vcs_provider,
)
from sase.agent.status_buckets import (
    ACTIVE_PLAN_HANDOFF_STATUSES,
    agent_status_bucket,
)
from sase.workspace_provider.store import WorkspaceStore
from sase.workspace_provider.utils import parse_workspace_dir

from ...models.agent import Agent
from ...models._agent_status_family_core import is_root_plan_workflow
from ...models._agent_status_roles import is_coder_followup_suffix

# Primary invalidation signal for the diff cache. ``git diff HEAD`` reflects
# the working tree and ``.git/index`` does not change on working-tree edits,
# so we must time-bucket cache entries to ever surface fresh edits made by a
# running agent. ~1 s is fast enough that new edits appear within a heartbeat
# and slow enough to absorb sub-second j/k navigation bursts.
DIFF_CACHE_TTL_SECONDS = 1.0

DiffCacheKey = tuple[
    tuple[object, ...],  # agent.identity
    str,  # workspace_dir
    str,  # vcs provider name
    tuple[int, int] | None,  # .git/index (mtime_ns, size)
    int,  # TTL bucket (always present)
]


_diff_cache: dict[DiffCacheKey, str | None] = {}
_diff_cache_lock = Lock()

# Constructing a ``WorkspaceStore`` may shell out (``git remote``) to derive
# the project key, so we memoize one per primary workspace dir to keep diff
# fetches cheap.  Resolution itself is pure (creates no directories).  Mirrors
# the ``_diff_cache`` locking discipline above.
_workspace_store_cache: dict[str, WorkspaceStore] = {}
_workspace_store_cache_lock = Lock()

# Resolving a VCS provider scans ``importlib.metadata`` entry points and runs
# ``git`` detection subprocesses; both are pure functions of the workspace
# path for a session.  Memoizing one provider per workspace dir keeps the
# deferred live-hint batch (one probe per active agent) from re-running that
# discovery for every row.  Mirrors the ``_workspace_store_cache`` discipline:
# provider instances are stateless dispatchers, so caching one per workspace
# for the process lifetime is safe (a mid-session ``SASE_VCS_PROVIDER`` /
# config change is as rare as the workspace-store cache already tolerates).
_vcs_provider_cache: dict[str, VCSProvider] = {}
_vcs_provider_cache_lock = Lock()


class _DiffProbeUnknown:
    """Sentinel for a live diff probe that failed without proving cleanliness."""


_DIFF_PROBE_UNKNOWN = _DiffProbeUnknown()
type _DiffProbeResult = str | None | _DiffProbeUnknown


def _resolve_vcs_provider_cached(workspace_dir: str) -> VCSProvider:
    """Return a cached :class:`VCSProvider` for *workspace_dir*.

    Resolves through the module-level ``get_vcs_provider`` (so tests that
    patch it still take effect on a cache miss) and stores only successful
    resolutions; :class:`VCSProviderNotFoundError` propagates uncached.
    """
    with _vcs_provider_cache_lock:
        cached = _vcs_provider_cache.get(workspace_dir)
    if cached is not None:
        return cached
    provider = get_vcs_provider(workspace_dir)
    with _vcs_provider_cache_lock:
        return _vcs_provider_cache.setdefault(workspace_dir, provider)


def resolve_vcs_provider_for_live_diff(workspace_dir: str) -> VCSProvider:
    """Return the cached VCS provider used by live diff helpers."""
    return _resolve_vcs_provider_cached(workspace_dir)


_ACTIVE_DIFF_SOURCE_STATUSES = frozenset(
    {
        "STARTING",
        "WAITING",
        "QUEUED",
        "RUNNING",
        *ACTIVE_PLAN_HANDOFF_STATUSES,
    }
)


def _agent_launch_time(agent: Agent) -> datetime:
    return agent.run_start_time or agent.start_time or datetime.min


def _resolve_agent_diff_source(agent: Agent) -> Agent:
    """Return the agent whose workspace should provide live diff content."""
    if not is_root_plan_workflow(agent):
        return agent

    active_coder_children = [
        child
        for child in agent.followup_agents
        if is_coder_followup_suffix(child.role_suffix)
        and child.status in _ACTIVE_DIFF_SOURCE_STATUSES
    ]
    if not active_coder_children:
        return agent

    return max(active_coder_children, key=_agent_launch_time)


def resolve_agent_diff_source(agent: Agent) -> Agent:
    """Return the agent whose workspace provides this row's diff content.

    Public wrapper around :func:`_resolve_agent_diff_source` so the Agents-tab
    badge and the deferred live-hint scan resolve the diff source through the
    exact same rule the detail panel uses. Stays cheap: it only inspects
    in-memory plan/follow-up relationships and statuses (no filesystem, VCS, or
    diff reads).
    """
    return _resolve_agent_diff_source(agent)


def diff_badge_uses_live_hint(agent: Agent) -> bool:
    """Return whether the row's primary badge uses active-workspace precedence.

    Active workspaces are fresh and win when dirty, even when a persisted
    primary fallback exists. Terminal rows remain persistence-only because a
    released workspace may already belong to another agent. Root Plan/Tale
    rows follow the status of their resolved active coder source.
    """
    source = _resolve_agent_diff_source(agent)
    return agent_status_bucket(source) not in {"Done", "Failed"}


def _git_index_signature(workspace_dir: str) -> tuple[int, int] | None:
    git_index = os.path.join(workspace_dir, ".git", "index")
    try:
        st = os.stat(git_index)
    except OSError:
        return None
    return (st.st_mtime_ns, st.st_size)


def git_index_signature_for_live_diff(workspace_dir: str) -> tuple[int, int] | None:
    """Return the ``.git/index`` fingerprint used by live diff caches."""
    return _git_index_signature(workspace_dir)


def _existing_workspace_dir(workspace_dir: str | None) -> str | None:
    if not workspace_dir:
        return None
    expanded = os.path.expanduser(workspace_dir)
    if not os.path.isdir(expanded):
        return None
    # Normalize so a trailing slash (the ``WorkspaceStore`` checkout
    # convention and how some agent_meta.json paths are stored) does not
    # produce a distinct diff-cache key from the same workspace reached via
    # ``agent.workspace_dir``.
    return os.path.normpath(expanded)


def _get_workspace_store(primary_workspace_dir: str) -> WorkspaceStore:
    """Return a cached ``WorkspaceStore`` for *primary_workspace_dir*."""
    with _workspace_store_cache_lock:
        cached = _workspace_store_cache.get(primary_workspace_dir)
    if cached is not None:
        return cached
    store = WorkspaceStore(primary_workspace_dir, config=load_merged_config())
    with _workspace_store_cache_lock:
        return _workspace_store_cache.setdefault(primary_workspace_dir, store)


def _resolve_managed_workspace_dir(
    primary_workspace_dir: str,
    workspace_num: int | None,
) -> str | None:
    """Resolve a workspace checkout via the canonical ``WorkspaceStore``.

    Delegates to the same resolver the runner/CLI use so the TUI honors the
    configured ``workspace.root`` policy (``xdg-state`` default, ``adjacent``
    legacy, absolute / ``SASE_WORKSPACE_ROOT`` override) and can never drift
    from a private heuristic again.  Resolution is pure: it never clones or
    materializes a workspace just to render a diff.
    """
    if workspace_num is None:
        return primary_workspace_dir
    if workspace_num == 1:
        # Legacy metadata uses 0 and 1 interchangeably for the primary
        # checkout; the runner-side resolvers normalize 1 -> 0 the same way.
        workspace_num = 0
    try:
        store = _get_workspace_store(primary_workspace_dir)
        return store.resolve(workspace_num).checkout_dir
    except Exception:
        return None


def _resolve_workspace_dir(agent: Agent) -> str | None:
    if agent.workspace_dir:
        return _existing_workspace_dir(agent.workspace_dir)

    primary_workspace = parse_workspace_dir(agent.project_file)
    if primary_workspace is None:
        return None

    derived_workspace = _resolve_managed_workspace_dir(
        primary_workspace,
        agent.workspace_num,
    )
    return _existing_workspace_dir(derived_workspace)


def _compute_diff_cache_key(agent: Agent) -> DiffCacheKey | None:
    """Build the diff cache key for an agent, or None if not derivable.

    The TTL bucket is always included — it is the primary invalidation signal
    because ``.git/index`` does not change on working-tree edits, so an agent
    actively editing files would otherwise produce a permanently warm cache.
    The ``.git/index`` (mtime_ns, size) fingerprint is included as a
    secondary discriminator so a stage/commit during a TTL window
    invalidates the cached result immediately.
    """
    diff_source = _resolve_agent_diff_source(agent)
    workspace_dir = _resolve_workspace_dir(diff_source)
    if workspace_dir is None:
        return None
    try:
        provider = _resolve_vcs_provider_cached(workspace_dir)
    except VCSProviderNotFoundError:
        return None
    provider_name = type(provider).__name__
    fingerprint = _git_index_signature(workspace_dir)
    ttl_bucket = int(time.time() // DIFF_CACHE_TTL_SECONDS)
    return (diff_source.identity, workspace_dir, provider_name, fingerprint, ttl_bucket)


def live_agent_file_change_hint(agent: Agent) -> bool | None:
    """Classify an active agent's live workspace edits for the Agents-tab badge.

    Mirrors the detail pane's live-diff path so a running agent's row shows the
    pencil badge as soon as its primary workspace or linked workspaces have
    real edits, even before a ``diff_path`` is persisted at finalization.

    Returns ``None`` when the live signal does not apply because the agent is
    terminal, or when a live probe fails and no persisted fallback exists.
    Otherwise returns whether the live-primary-first diff or linked diff
    touches non-bookkeeping paths, using the same exclusion as
    :func:`diff_has_real_edits`.
    """
    diff_source = _resolve_agent_diff_source(agent)
    if agent_status_bucket(diff_source) in {"Done", "Failed"}:
        return None

    diff_result = _get_agent_diff(agent, unknown_on_probe_failure=True)
    if isinstance(diff_result, _DiffProbeUnknown):
        return None
    diff_text = diff_result
    primary_hint = False
    if not diff_text:
        # No resolvable workspace or a genuinely clean working tree both
        # collapse to "no live edits": fail closed so the row badge stays
        # stable rather than guessing a pencil.
        primary_hint = False
    else:
        from ...models._diff_badge import diff_text_has_real_edits

        primary_hint = diff_text_has_real_edits(diff_text)

    from ._linked_deltas import linked_agent_file_change_hint

    linked_hint = linked_agent_file_change_hint(agent)
    if primary_hint or linked_hint is True:
        return True
    if linked_hint is False:
        return False
    return primary_hint


def get_agent_diff(agent: Agent) -> str | None:
    """Get diff output for an agent.

    Terminal agents only read their persisted primary diff. Active agents
    resolve and probe the existing primary workspace first, caching by
    ``_compute_diff_cache_key``; a dirty live workspace wins, while a clean or
    unresolvable workspace falls back to the persisted primary diff.

    Args:
        agent: The agent to get diff for.

    Returns:
        Diff output string, or None if unavailable.
    """
    result = _get_agent_diff(agent, unknown_on_probe_failure=False)
    if isinstance(result, _DiffProbeUnknown):
        return None
    return result


def _get_agent_diff(
    agent: Agent,
    *,
    unknown_on_probe_failure: bool,
) -> _DiffProbeResult:
    """Internal diff fetcher with an optional live-probe failure sentinel."""
    diff_source = _resolve_agent_diff_source(agent)

    persisted_diff: str | None = None
    if diff_source.diff_path:
        try:
            text = Path(diff_source.diff_path).read_text(encoding="utf-8")
            persisted_diff = text if text.strip() else None
        except (OSError, UnicodeDecodeError):
            # Unreadable or non-UTF-8 (e.g. malformed historical metadata that
            # promoted a binary PNG path into diff_path): treat as no persisted
            # diff rather than crashing the TUI.
            pass

    # Finalized primary diffs are authoritative for terminal agents. Their
    # workspace may have been released and reused, so never probe it.
    if agent_status_bucket(diff_source) in {"Done", "Failed"}:
        return persisted_diff

    key = _compute_diff_cache_key(diff_source)
    if key is None:
        return persisted_diff

    with _diff_cache_lock:
        if key in _diff_cache:
            return _diff_cache[key] or persisted_diff

    workspace_dir = key[1]
    try:
        provider = _resolve_vcs_provider_cached(workspace_dir)
    except VCSProviderNotFoundError:
        return persisted_diff

    try:
        ok, diff_text = provider.diff_with_untracked(workspace_dir, timeout=10)
    except Exception:
        if unknown_on_probe_failure:
            return _DIFF_PROBE_UNKNOWN
        return persisted_diff
    if not ok:
        if unknown_on_probe_failure:
            return _DIFF_PROBE_UNKNOWN
        return persisted_diff
    result = diff_text if diff_text else None

    with _diff_cache_lock:
        _diff_cache[key] = result
    return result or persisted_diff
