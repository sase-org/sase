"""Warm Archive candidates for the Node Finder remain exact light rows."""

from __future__ import annotations

from sase.ace.tui.actions.agents._node_finder_archive import (
    ArchiveNameCandidate,
    load_archive_name_candidates,
    search_archive_name_candidates,
)
from tests.ace.tui._agent_archive_column_helpers import ModelCorpus, light_row


def test_archive_name_loader_expands_containers_to_member_rows() -> None:
    container = "archive:alice.athena@clan-run"
    corpus = ModelCorpus(
        [
            light_row(
                "clan-run-a",
                name="clan.alpha",
                container_key=container,
            ),
            light_row(
                "clan-run-b",
                name="clan.beta",
                container_key=container,
            ),
            light_row("solo-run", name="solo.gamma"),
        ]
    )

    candidates = load_archive_name_candidates(corpus)

    assert {candidate.name for candidate in candidates} == {
        "clan.alpha",
        "clan.beta",
        "solo.gamma",
    }
    assert all(candidate.row.get("container") is not True for candidate in candidates)
    assert all(candidate.row.get("archive_key") for candidate in candidates)


def test_archive_name_search_keeps_best_five_fuzzy_matches() -> None:
    candidates = tuple(
        # The exact first row is ordered ahead of the other fuzzy matches.
        ArchiveNameCandidate(f"build.task-{index}")
        for index in range(7)
    )

    matches = search_archive_name_candidates(candidates, "build task")

    assert len(matches) == 5
    assert [candidate.name for candidate in matches] == [
        f"build.task-{index}" for index in range(5)
    ]
