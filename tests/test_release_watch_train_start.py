"""Train start at a fresh tag: reader facts, generation-0 abandonment, and walk.

This module is a facade preserving the original import path. The tests
now live in :mod:`tests.test_release_watch_train_start_fresh`,
:mod:`tests.test_release_watch_train_start_abandonment`, and
:mod:`tests.test_release_watch_train_start_walk`; shared builders live
in :mod:`tests._release_watch_train_start_helpers`. Only public names are
re-exported here, never ``_``-private helpers.
"""

from __future__ import annotations

# The re-exported tests must not be collected twice: pytest collects
# this module (zero tests) and each home module (the real tests).
__test__ = False

from tests.test_release_watch_train_start_abandonment import (
    test_gen0_abandonment_recovers_after_upload_crash,
    test_gen0_abandonment_writes_observation_and_prefixes_title,
)
from tests.test_release_watch_train_start_fresh import (
    test_fresh_tag_head_mismatch_stays_mismatch,
    test_fresh_tag_with_burned_observation_is_abandoned,
    test_fresh_tag_with_foreign_abandoned_observation_is_not_abandoned,
    test_fresh_tag_with_pypi_files_stays_mismatch,
    test_fresh_tag_without_draft_release_stays_mismatch,
    test_fresh_tag_without_merged_head_knowledge_is_still_fresh,
    test_fresh_unsealed_tag_is_its_own_fact,
)
from tests.test_release_watch_train_start_walk import (
    test_walk_drives_one_train_from_releasable_to_released,
)

__all__ = [
    "test_fresh_tag_head_mismatch_stays_mismatch",
    "test_fresh_tag_with_burned_observation_is_abandoned",
    "test_fresh_tag_with_foreign_abandoned_observation_is_not_abandoned",
    "test_fresh_tag_with_pypi_files_stays_mismatch",
    "test_fresh_tag_without_draft_release_stays_mismatch",
    "test_fresh_tag_without_merged_head_knowledge_is_still_fresh",
    "test_fresh_unsealed_tag_is_its_own_fact",
    "test_gen0_abandonment_recovers_after_upload_crash",
    "test_gen0_abandonment_writes_observation_and_prefixes_title",
    "test_walk_drives_one_train_from_releasable_to_released",
]
