"""Public facade for publication job tests."""

from __future__ import annotations

import multiprocessing
import os
from pathlib import Path
import signal
import time
from types import SimpleNamespace

import pytest

from sase.agents_sync import _commit_publication_queue as publication_queue
from sase.agents_sync import publication_doorbell, publication_job
from sase.agents_sync._commit_publication_types import CommitPublicationOutcome
from sase.agents_sync.git_sync_ops import bounded_agents_lock
from sase.agents_sync.models import ProjectTarget
from sase.agents_sync.publication_outbox import (
    AgentPublicationOutboxItem,
    enqueue_agent_publication,
    list_agent_publications,
)
from tests._conftest_environment import redirect_sase_home
from tests.agents_sync._publication_job_doorbell import (
    test_doorbell_hint_claim_recovers_after_interrupted_pass,
    test_publication_hint_can_be_persisted_without_ringing_doorbell,
    test_heartbeat_round_trip_and_liveness,
    test_hinted_hood_requests_are_drained_before_the_oldest_backlog,
    test_item_error_does_not_starve_unhinted_ready_requests,
    test_repository_failure_stops_and_retains_only_unattempted_hints,
    test_hint_claim_compacts_multiple_files_into_one,
    test_deadline_retains_unattempted_hinted_requests,
    test_retained_link_rows_finish_the_hint_without_ringing_again,
    test_deferred_or_raised_link_drain_keeps_hint_and_rings_again,
)
from tests.agents_sync._publication_job_referenced_by import (
    test_publisher_converts_fenced_referenced_by_requests_without_sidecar_refresh,
    test_publisher_keeps_unfenced_referenced_by_refresh_path,
    test_fenced_conversion_failure_quarantines_without_re_ring,
)
from tests.agents_sync._publication_job_lifecycle import (
    test_new_publication_waits_for_done_marker_or_ten_minute_grace,
    test_publication_job_leaves_young_request_queued_until_done_marker,
    test_busy_agents_lock_rings_again_without_charging_requests,
    test_budget_defers_projects_without_starting_a_drain,
    test_sigkilled_publisher_leaves_request_active_and_releases_locks,
)

__all__ = [
    "multiprocessing",
    "os",
    "Path",
    "signal",
    "time",
    "SimpleNamespace",
    "pytest",
    "publication_queue",
    "publication_doorbell",
    "publication_job",
    "CommitPublicationOutcome",
    "bounded_agents_lock",
    "ProjectTarget",
    "AgentPublicationOutboxItem",
    "enqueue_agent_publication",
    "list_agent_publications",
    "redirect_sase_home",
    "test_doorbell_hint_claim_recovers_after_interrupted_pass",
    "test_publication_hint_can_be_persisted_without_ringing_doorbell",
    "test_heartbeat_round_trip_and_liveness",
    "test_hinted_hood_requests_are_drained_before_the_oldest_backlog",
    "test_item_error_does_not_starve_unhinted_ready_requests",
    "test_repository_failure_stops_and_retains_only_unattempted_hints",
    "test_hint_claim_compacts_multiple_files_into_one",
    "test_deadline_retains_unattempted_hinted_requests",
    "test_retained_link_rows_finish_the_hint_without_ringing_again",
    "test_deferred_or_raised_link_drain_keeps_hint_and_rings_again",
    "test_publisher_converts_fenced_referenced_by_requests_without_sidecar_refresh",
    "test_publisher_keeps_unfenced_referenced_by_refresh_path",
    "test_fenced_conversion_failure_quarantines_without_re_ring",
    "test_new_publication_waits_for_done_marker_or_ten_minute_grace",
    "test_publication_job_leaves_young_request_queued_until_done_marker",
    "test_busy_agents_lock_rings_again_without_charging_requests",
    "test_budget_defers_projects_without_starting_a_drain",
    "test_sigkilled_publisher_leaves_request_active_and_releases_locks",
]
