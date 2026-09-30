"""Phase fetch: lazy fetch, availability badges, and doctor (phase fetch).

Two temp ``SASE_HOME`` directories share one local bare remote through two
bare partial clones. Never the real project bead store or the real
``~/.sase`` attachment CAS. No network and no GitHub.

Split into focused modules; this module re-exports every test so the
original import path keeps working.
"""

from __future__ import annotations

from tests.test_bead._attachment_fetch_helpers import (
    fetch_remote as remote,
    fetch_work_dir as work_dir,
)
from tests.test_bead.test_attachment_fetch_basics import (
    test_auto_fetch_config_default_and_fail_open,
    test_badge_table,
    test_read_without_attachments_skips_store_discovery,
)
from tests.test_bead.test_attachment_fetch_doctor import (
    test_doctor_check_registered,
    test_doctor_ok_warn_and_skip,
    test_materialize_attachment_view_fetches_on_second_home,
    test_open_fetches_from_shared_store_on_second_home,
    test_open_without_store_fails_with_badge_error,
)
from tests.test_bead.test_attachment_fetch_homes import (
    test_concurrent_attaches_converge,
    test_corrupt_remote_blob_reports_corrupt,
    test_large_file_not_downloaded_until_explicit,
    test_read_fetches_small_file_cached,
)
from tests.test_bead.test_attachment_fetch_state import (
    test_fetch_mismatch_is_corrupt_and_not_installed,
    test_fetch_mode_auto_installs_under_cap,
    test_state_machine_remote_tombstone_is_purged,
    test_state_machine_with_store,
    test_state_machine_without_store_stays_two_state,
)

__test__ = False

__all__ = [
    "remote",
    "test_auto_fetch_config_default_and_fail_open",
    "test_badge_table",
    "test_concurrent_attaches_converge",
    "test_corrupt_remote_blob_reports_corrupt",
    "test_doctor_check_registered",
    "test_doctor_ok_warn_and_skip",
    "test_fetch_mismatch_is_corrupt_and_not_installed",
    "test_fetch_mode_auto_installs_under_cap",
    "test_large_file_not_downloaded_until_explicit",
    "test_materialize_attachment_view_fetches_on_second_home",
    "test_open_fetches_from_shared_store_on_second_home",
    "test_open_without_store_fails_with_badge_error",
    "test_read_fetches_small_file_cached",
    "test_read_without_attachments_skips_store_discovery",
    "test_state_machine_remote_tombstone_is_purged",
    "test_state_machine_with_store",
    "test_state_machine_without_store_stays_two_state",
    "work_dir",
]
