"""Public collection and import facade for publication-step tests."""

from __future__ import annotations

import pytest

from tests._commit_workflow_fixtures import (
    no_commit_hooks,  # noqa: F401 (imported for fixture discovery, re-used below)
)
from tests._test_commit_workflow_publication_step_background import (
    test_background_enqueue_failure_keeps_commit_resumable,
    test_background_resume_enqueues_legacy_prompt_checkpoint_revision,
    test_live_background_publisher_enqueues_without_draining_sidecars,
)
from tests._test_commit_workflow_publication_step_inline import (
    test_background_publication_requires_mode_axe_and_live_publisher,
    test_commit_publishes_every_sidecar_inline_in_order,
    test_fully_tagged_commit_and_resume_publish_each_sidecar_once,
    test_legacy_checkpoint_without_prompt_archive_publishes_commit_sha,
    test_publication_step_records_release_evidence_for_this_run,
    test_resumed_legacy_checkpoint_keeps_prompt_archive_revision_for_hood,
)
from tests._test_commit_workflow_publication_step_linked import (
    test_background_evidence_write_error_keeps_commit_resumable,
    test_background_linked_checkout_keys_evidence_enqueue_and_hint_alike,
    test_background_resume_after_evidence_failure_finishes_without_new_commit,
    test_background_unmappable_repository_skips_without_resumable_failure,
    test_inline_linked_checkout_drains_outbox_against_host_project,
    test_resolver_falls_back_to_marker_then_project_file,
    test_resolver_prefers_inventory_over_marker_and_project_file,
    test_resolver_returns_none_when_nothing_maps,
)


@pytest.fixture(autouse=True)
def _no_commit_hooks(no_commit_hooks):  # type: ignore[no-untyped-def]  # noqa: F811
    yield


@pytest.fixture(autouse=True)
def _inline_publication_unless_a_test_selects_background(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("sase.axe._process_probe.is_axe_running", lambda: False)


__all__ = [
    "test_background_enqueue_failure_keeps_commit_resumable",
    "test_background_evidence_write_error_keeps_commit_resumable",
    "test_background_linked_checkout_keys_evidence_enqueue_and_hint_alike",
    "test_background_publication_requires_mode_axe_and_live_publisher",
    "test_background_resume_after_evidence_failure_finishes_without_new_commit",
    "test_background_resume_enqueues_legacy_prompt_checkpoint_revision",
    "test_background_unmappable_repository_skips_without_resumable_failure",
    "test_commit_publishes_every_sidecar_inline_in_order",
    "test_fully_tagged_commit_and_resume_publish_each_sidecar_once",
    "test_inline_linked_checkout_drains_outbox_against_host_project",
    "test_legacy_checkpoint_without_prompt_archive_publishes_commit_sha",
    "test_live_background_publisher_enqueues_without_draining_sidecars",
    "test_publication_step_records_release_evidence_for_this_run",
    "test_resolver_falls_back_to_marker_then_project_file",
    "test_resolver_prefers_inventory_over_marker_and_project_file",
    "test_resolver_returns_none_when_nothing_maps",
    "test_resumed_legacy_checkpoint_keeps_prompt_archive_revision_for_hood",
]
