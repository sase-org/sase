"""Warm Archive candidates for the Node Finder remain exact light rows."""

from __future__ import annotations

from types import SimpleNamespace

from sase.ace.tui.actions.agents._node_finder_archive import (
    ArchiveNameCandidate,
    _load_archive_name_candidates,
    archive_name_loader_for_owner,
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

    candidates = _load_archive_name_candidates(corpus)

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


def test_archive_name_candidates_are_cached_for_the_corpus_generation() -> None:
    corpus = ModelCorpus([light_row("solo", name="solo.gamma")])
    owner = SimpleNamespace(
        _agents_archive_controller=SimpleNamespace(
            corpus=corpus,
            profile=None,
            status="warm",
        )
    )

    first_loader = archive_name_loader_for_owner(owner)
    second_loader = archive_name_loader_for_owner(owner)
    assert first_loader is not None and second_loader is not None
    first = first_loader()
    second = second_loader()

    assert second == first
    assert corpus.summary_calls == 1
    assert len(corpus.rows_calls) == 1
