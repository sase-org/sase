"""Backend for reverting commits associated with done agents.

Powers the Agents-tab leader ``,r`` action. Commits are associated with an
agent by the exact ``AGENT=<name>`` provenance tag written into commit messages
(see :mod:`sase.workflows.commit.runtime_tags`). This is git-only: non-git
workspaces fail with an explicit unsupported message rather than reusing
Patch prune/abandon semantics.

The flow is two-phase so the TUI can confirm before mutating anything:

1. :func:`preview_agent_revert` discovers candidate commits newest-first across
   the primary workspace and eligible linked workspaces.
2. :func:`execute_agent_revert` re-validates each repository, applies
   ``git revert --no-commit`` for that repo's previewed SHAs, creates one
   revert commit per repository, and pushes each repo when an ``origin`` remote
   and branch are available.

A parallel *bulk* path (:func:`preview_agents_revert` /
:func:`execute_agents_revert`) reverts the combined commit set of several
marked agents with the same per-repository transaction semantics.
"""

from __future__ import annotations

from sase.ace.revert_agent_discovery import (
    agent_tag_matches,
    discover_agent_commits,
    discover_bulk_commits,
)
from sase.ace.revert_agent_execute import (
    execute_agent_revert,
    execute_agents_revert,
)
from sase.ace.revert_agent_git import (
    commit_exists,
    commit_subject,
    current_head,
    is_git_worktree,
    run_git as _run_git,
    worktree_is_clean,
)
from sase.ace.revert_agent_marker import (
    _REVERT_RESULT_FILENAME,
    PushOutcome,
    agent_is_reverted,
    repo_outcome_payload,
    write_revert_result,
)
from sase.ace.revert_agent_models import (
    BulkRevertIntent,
    BulkRevertPreview,
    BulkRevertResult,
    RepoRevertOutcome,
    RepoRevertPlan,
    RevertCommit,
    RevertIntent,
    RevertPreview,
    RevertRepo,
    RevertResult,
    RevertTarget,
)
from sase.ace.revert_agent_preview import (
    preview_agent_revert,
    preview_agents_revert,
)
from sase.ace.revert_agent_resolution import (
    build_bulk_revert_execute_intent,
    build_bulk_revert_intent,
    build_revert_execute_intent,
    build_revert_intent,
    resolve_revert_agent_name,
    resolve_revert_family_base,
    resolve_revert_repos,
    resolve_revert_repos_for_agents,
    resolve_revert_workspace_dir,
)
from sase.ace.revert_agent_workspace import (
    RevertWorkspaceError,
    execute_agent_revert_intent,
    execute_agents_revert_intent,
    preview_agent_revert_intent,
    preview_agents_revert_intent,
)

_discover_agent_commits = discover_agent_commits
_discover_bulk_commits = discover_bulk_commits
_PushOutcome = PushOutcome
_repo_outcome_payload = repo_outcome_payload
_write_revert_result = write_revert_result

__all__ = [
    "BulkRevertIntent",
    "BulkRevertPreview",
    "BulkRevertResult",
    "RepoRevertOutcome",
    "RepoRevertPlan",
    "RevertCommit",
    "RevertIntent",
    "RevertPreview",
    "RevertRepo",
    "RevertResult",
    "RevertTarget",
    "RevertWorkspaceError",
    "agent_is_reverted",
    "build_bulk_revert_execute_intent",
    "build_bulk_revert_intent",
    "build_revert_execute_intent",
    "build_revert_intent",
    "execute_agent_revert",
    "execute_agent_revert_intent",
    "execute_agents_revert",
    "execute_agents_revert_intent",
    "preview_agent_revert",
    "preview_agent_revert_intent",
    "preview_agents_revert",
    "preview_agents_revert_intent",
    "resolve_revert_agent_name",
    "resolve_revert_family_base",
    "resolve_revert_repos",
    "resolve_revert_repos_for_agents",
    "resolve_revert_workspace_dir",
]
