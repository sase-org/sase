"""Constants shared by ACE TUI event refresh handlers."""

from __future__ import annotations

from sase.agent.status_buckets import (
    ACTIVE_PLAN_HANDOFF_STATUSES,
    PENDING_PLAN_REVIEW_STATUSES,
)

# Slow sanity-refresh floor: even when the inotify watcher is active and
# every dirty flag is clear we still reconcile every minute as a safety
# net for missed events (NFS, container bind-mount edge cases, etc.).
FULL_SANITY_REFRESH_SECONDS = 60.0
PROMPT_INPUT_DEFER_SECONDS = 0.25
# Minimum spacing between successive ``_load_agents_async`` calls from the
# auto-refresh tick. The loader is the dominant cost on every refresh, so
# this floor caps the worst case to one load per window regardless of how
# often the dirty flag is re-armed by inotify. Sanity refreshes bypass it.
AGENTS_LOAD_MIN_INTERVAL_SECONDS = 5.0
AGENT_ARTIFACT_DELTA_QUEUE_LIMIT = 64
EXPECTED_AGENT_ARTIFACT_DELETION_TTL_SECONDS = 30.0

_AGENTS_RELEVANT_ARTIFACT_MARKERS = frozenset(
    {
        "agent_meta.json",
        "done.json",
        "running.json",
        "waiting.json",
        "pending_question.json",
        "workflow_state.json",
        "plan_path.json",
        "retry_state.json",
    }
)

_LIVE_FILE_REFRESH_STATUSES = frozenset(
    {
        "RUNNING",
        "WAITING",
        "QUEUED",
        "WAITING INPUT",
        *PENDING_PLAN_REVIEW_STATUSES,
        *ACTIVE_PLAN_HANDOFF_STATUSES,
        "QUESTION",
        "ANSWERED",
        "RETRYING",
    }
)
