"""Resume and rollback coverage for plan-file ``sase bead work``.

Facade preserving the original module's public import path. Test bodies live in
:mod:`test_cli_work_from_plan_resume_links`,
:mod:`test_cli_work_from_plan_resume_rollback`, and
:mod:`test_cli_work_from_plan_resume_relocation`.
"""

from __future__ import annotations

import pytest

from .test_cli_work_from_plan_resume_links import (
    test_plan_file_rejects_linked_non_epic_bead,
    test_plan_file_replaces_missing_linked_bead,
    test_plan_file_resume_reuses_linked_epic,
    test_retrying_original_file_preserves_archived_bead_link,
)
from .test_cli_work_from_plan_resume_relocation import (
    test_plan_file_relocation_rollback_publication_failure_stops_retrying,
    test_plan_file_retries_relocated_creation_and_launches_second_attempt,
    test_plan_file_stops_after_three_relocated_attempts,
    test_resume_relinks_plan_to_moved_epic,
)
from .test_cli_work_from_plan_resume_rollback import (
    test_plan_file_launch_failure_resume_command_preserves_capacity,
    test_plan_file_launch_failure_rolls_back_for_resume,
    test_stale_link_replacement_launch_failure_restores_stale_link,
    test_zero_spawn_after_publication_commits_and_publishes_rollback,
)


@pytest.fixture(autouse=True)
def stable_resume_plan_formatting(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "sase.file_references.format_with_prettier",
        lambda content: content,
    )


__all__ = [
    "test_plan_file_launch_failure_resume_command_preserves_capacity",
    "test_plan_file_launch_failure_rolls_back_for_resume",
    "test_plan_file_rejects_linked_non_epic_bead",
    "test_plan_file_relocation_rollback_publication_failure_stops_retrying",
    "test_plan_file_replaces_missing_linked_bead",
    "test_plan_file_retries_relocated_creation_and_launches_second_attempt",
    "test_plan_file_resume_reuses_linked_epic",
    "test_plan_file_stops_after_three_relocated_attempts",
    "test_resume_relinks_plan_to_moved_epic",
    "test_retrying_original_file_preserves_archived_bead_link",
    "test_stale_link_replacement_launch_failure_restores_stale_link",
    "test_zero_spawn_after_publication_commits_and_publishes_rollback",
]
