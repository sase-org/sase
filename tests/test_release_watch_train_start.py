"""Train start at a fresh tag: reader facts, generation-0 abandonment, and walk.

Split into focused modules; this module re-exports every public name so the
original import path keeps working.
"""

from __future__ import annotations

from tests._release_watch_train_start_helpers import CANDIDATE
from tests._release_watch_train_start_helpers import REPO
from tests._release_watch_train_start_helpers import ROOT
from tests._release_watch_train_start_helpers import SEALED_SHA
from tests._release_watch_train_start_helpers import SHA
from tests._release_watch_train_start_helpers import TAG
from tests._release_watch_train_start_helpers import VERSION
from tests._release_watch_train_start_helpers import FakeGithub
from tests.test_release_watch_train_start_abandon import FakePypi
from tests.test_release_watch_train_start_abandon import FakeRunner
from tests.test_release_watch_train_start_abandon import MemoryGithub
from tests.test_release_watch_train_start_abandon import SimulatedCrash
from tests.test_release_watch_train_start_abandon import (
    test_gen0_abandonment_recovers_after_upload_crash,
)
from tests.test_release_watch_train_start_abandon import (
    test_gen0_abandonment_writes_observation_and_prefixes_title,
)
from tests.test_release_watch_train_start_fresh import (
    test_fresh_tag_head_mismatch_stays_mismatch,
)
from tests.test_release_watch_train_start_fresh import (
    test_fresh_tag_with_burned_observation_is_abandoned,
)
from tests.test_release_watch_train_start_fresh import (
    test_fresh_tag_with_foreign_abandoned_observation_is_not_abandoned,
)
from tests.test_release_watch_train_start_fresh import (
    test_fresh_tag_with_pypi_files_stays_mismatch,
)
from tests.test_release_watch_train_start_fresh import (
    test_fresh_tag_without_draft_release_stays_mismatch,
)
from tests.test_release_watch_train_start_fresh import (
    test_fresh_tag_without_merged_head_knowledge_is_still_fresh,
)
from tests.test_release_watch_train_start_fresh import (
    test_fresh_unsealed_tag_is_its_own_fact,
)
from tests.test_release_watch_train_start_walk import (
    test_walk_drives_one_train_from_releasable_to_released,
)


__test__ = False

__all__ = [
    "CANDIDATE",
    "REPO",
    "ROOT",
    "SEALED_SHA",
    "SHA",
    "TAG",
    "VERSION",
    "FakeGithub",
    "FakePypi",
    "FakeRunner",
    "MemoryGithub",
    "SimulatedCrash",
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
