"""Producer-to-consumer qualification transport integration tests.

Drives the real workflow command wiring (``fetch-evidence``, the bundle
collector, ``release_candidate qualify``/``evaluate``, and the draft attach
block from ``release.yml``) against a fake Actions transport: a ``gh``
executable on PATH serving canned jobs pages, run-scoped artifacts, evidence
zips, and a fake draft release.

Split into focused modules; this module re-exports every public name so the
original import path keeps working.
"""

from __future__ import annotations

from tests._qualification_transport_integration_helpers import (
    COLLECT_SCRIPT,
    CORE_VERSION,
    FAKE_GH,
    INVENTORY,
    RELEASE_SCRIPT,
    RELEASE_WORKFLOW,
    REPO,
    ROOT,
    RUN_ID,
    SHA,
    WRITE_SCRIPT,
    collect_tool_fixture as collect_tool,
    fake_gh_fixture as fake_gh,
    release_tool_fixture as release_tool,
    write_tool_fixture as write_tool,
)
from tests.test_qualification_transport_integration_attach import (
    test_draft_attach_uses_canonical_asset_bytes,
)
from tests.test_qualification_transport_integration_green import (
    test_green_run_with_failed_advisory_passes,
    test_probe_with_failed_setup_names_missing_bindings,
)
from tests.test_qualification_transport_integration_refuse import (
    test_api_failure_stays_typed_red_through_cli_and_steward,
    test_wrong_caller_and_duplicate_scoped_rows_stay_red,
)
from tests.test_qualification_transport_integration_retry import (
    test_failed_only_retry_stays_green,
)

__test__ = False

__all__ = [
    "COLLECT_SCRIPT",
    "CORE_VERSION",
    "FAKE_GH",
    "INVENTORY",
    "RELEASE_SCRIPT",
    "RELEASE_WORKFLOW",
    "REPO",
    "ROOT",
    "RUN_ID",
    "SHA",
    "WRITE_SCRIPT",
    "collect_tool",
    "fake_gh",
    "release_tool",
    "test_api_failure_stays_typed_red_through_cli_and_steward",
    "test_draft_attach_uses_canonical_asset_bytes",
    "test_failed_only_retry_stays_green",
    "test_green_run_with_failed_advisory_passes",
    "test_probe_with_failed_setup_names_missing_bindings",
    "test_wrong_caller_and_duplicate_scoped_rows_stay_red",
    "write_tool",
]
