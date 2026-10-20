"""Compatibility facade for release watch health tests.

The detailed cases live in cohesive modules; pytest and existing imports continue to
use this module path. The cases exercise ``tools/_release_watch_health.py`` and the
``ReleaseFactsReader`` accessors, plus a real-binding round trip.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from _release_watch_health_test_helpers import (  # noqa: E402
    CORE_REPO,
    CORE_SHA,
    HEAD,
    OBSERVED,
    OBSERVED_ISO,
    PIN,
    REPO,
    RUN_CREATED,
    WORKFLOW_YML,
    ReleaseFactsError,
    ReleaseFactsReader,
    ReleaseTransportError,
    ScriptedGithub,
    ScriptedPypi,
    b64,
    canary_payload,
    flat,
    job_row,
    make_facts,
    make_health,
    pypi_complete,
    run_row,
    transport_error,
    wf_pages,
)
from _release_watch_health import ReleaseHealthReader as ReleaseHealthReader  # noqa: E402
from release_watch_health_canary import (  # noqa: E402
    canary_world,
    test_canary_corrupt_json_is_unparsable_not_a_pass,
    test_canary_green_pair_is_pass,
    test_canary_identity_mismatch_is_flagged,
    test_canary_listing_failure_raises_transport_error,
    test_canary_prefers_newest_scheduled_over_manual_probe,
    test_canary_red_marks_fail_with_reason,
    test_canary_without_scheduled_run_is_empty_ready,
)
from release_watch_health_composition import (  # noqa: E402
    StubHealth,
    StubTrainReader,
    full_world,
    health_envelopes,
    stub_train,
    test_collect_snapshot_core_ensure_fails_closed_without_master,
    test_collect_snapshot_merges_sixteen_keys_in_wire_order,
    test_complete_snapshot_feeds_real_binding,
)
from release_watch_health_core import (  # noqa: E402
    core_base_reads,
    cut_world,
    test_cancelled_cut_needs_no_diagnostic,
    test_core_master_ci_absent_without_matching_run,
    test_core_master_ci_green_run_carries_jobs,
    test_core_release_pr_matches_release_plz_convention,
    test_core_release_pr_multiple_matches_are_inconsistent,
    test_cuts_keep_newest_twenty_completed_plus_in_flight,
    test_in_flight_cut_carries_pin_and_no_evidence,
    test_never_registered_cut_parses,
    test_red_cut_without_annotation_fails_closed,
    test_red_cut_with_typed_annotation_is_evidence,
)
from release_watch_health_issues import (  # noqa: E402
    comment_row,
    issue_row,
    issues_world,
    test_access_probe_failure_is_denied_not_unreadable,
    test_access_probe_reports_read_only_scope,
    test_issues_parse_markers_comments_and_closed_history,
    test_issues_skip_pull_requests,
    test_issues_without_markers_are_unknown,
    test_lineage_names_oldest_open_marker,
)
from release_watch_health_readers import (  # noqa: E402
    core_compare_reads,
    release_raw,
    revision_reads,
    test_core_ensure_compare_outage_is_an_error_variant,
    test_core_ensure_error_is_a_ready_variant_not_an_outage,
    test_core_ensure_falls_back_to_master_pin,
    test_core_ensure_lag_reports_newest_complete,
    test_core_ensure_prefers_pr_pin_over_master_pin,
    test_git_file_decodes_wrapped_base64,
    test_read_jobs_validates_arguments,
    test_read_ref_sha_validates_shape,
    test_read_releases_accepts_flattened_array_pages,
    test_read_repository_uses_slashless_path,
    test_read_source_pin_reads_remote_identity,
)
