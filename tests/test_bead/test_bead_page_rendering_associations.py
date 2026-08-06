"""Agent and commit association rendering on generated bead pages."""

from __future__ import annotations

from pathlib import Path
from types import MappingProxyType
from typing import cast

from sase.bead.project import BeadProject
from sase.bead_pages.associations import (
    BeadAgentAssociation,
    BeadAssociationIndex,
    BeadAssociations,
    BeadCommitAssociation,
    BeadCommitRepository,
)
from sase.bead_pages.rendering import render_bead_page
from tests.test_bead.bead_page_rendering_test_helpers import fixtures, render_page


def test_lists_are_visibly_bounded_at_the_shared_commit_cap() -> None:
    view, _root, phase, _index = fixtures()
    commits = tuple(
        BeadCommitAssociation(
            f"{number:07d}",
            None,
            phase.id,
            f"subject {number}",
            number,
            (number, "sase", f"{number:040d}"),
            f"{number:040d}",
        )
        for number in range(52)
    )
    index = BeadAssociationIndex(
        MappingProxyType({phase.id: BeadAssociations(commits=commits)})
    )

    rendered = render_page(view, phase, index)

    assert "… and 2 more commits" in rendered
    assert "subject 49" in rendered
    assert "subject 50" not in rendered


def test_unhosted_page_keeps_labels_and_omits_broken_urls() -> None:
    view, _root, phase, index = fixtures()
    hosted = index.for_bead(phase.id)
    unhosted = BeadAssociations(
        agents=tuple(
            BeadAgentAssociation(
                row.label,
                None,
                row.bead_id,
                row.commit_count,
                row.sort_key,
            )
            for row in hosted.agents
        ),
        commits=tuple(
            BeadCommitAssociation(
                row.label,
                None,
                row.bead_id,
                row.subject,
                row.committed_at,
                row.sort_key,
                row.sha,
                row.repository,
            )
            for row in hosted.commits
        ),
    )

    rendered = render_bead_page(
        cast(BeadProject, view),
        phase,
        BeadAssociationIndex(MappingProxyType({phase.id: unhosted})),
    )

    assert "alice.athena.sase-ai.1" in rendered
    assert "`9701511`" in rendered
    assert "202607/bead\\_pages.md" in rendered
    assert "https://" not in rendered


def test_commit_repo_is_rendered_in_its_own_column(
    tmp_path: Path,
) -> None:
    view, _root, phase, index = fixtures()
    original = index.for_bead(phase.id).commits[0]
    primary = BeadCommitAssociation(
        original.label,
        original.target,
        original.bead_id,
        original.subject,
        original.committed_at,
        original.sort_key,
        original.sha,
        BeadCommitRepository("sase", tmp_path / "sase", "primary", True),
    )
    linked = BeadCommitAssociation(
        original.label,
        original.target,
        original.bead_id,
        original.subject,
        original.committed_at,
        original.sort_key,
        original.sha,
        BeadCommitRepository(
            "sase-core",
            tmp_path / "sase-core",
            "linked",
            False,
        ),
    )

    original_page = render_page(view, phase, index)
    original_associations = index.for_bead(phase.id)
    primary_page = render_page(
        view,
        phase,
        BeadAssociationIndex(
            MappingProxyType(
                {
                    phase.id: BeadAssociations(
                        agents=original_associations.agents,
                        commits=(primary,),
                    )
                }
            )
        ),
    )
    linked_page = render_page(
        view,
        phase,
        BeadAssociationIndex(
            MappingProxyType(
                {
                    phase.id: BeadAssociations(
                        agents=original_associations.agents,
                        commits=(linked,),
                    )
                }
            )
        ),
    )

    assert primary_page == original_page
    assert "| sase | [`9701511`]" in primary_page
    assert "| sase-core | [`9701511`]" in linked_page
    assert "@9701511" not in primary_page
    assert "@9701511" not in linked_page
    assert primary_page.replace("| sase |", "| sase-core |") == linked_page


def test_commit_repo_column_has_unknown_fallback() -> None:
    view, _root, phase, index = fixtures()
    original = index.for_bead(phase.id).commits[0]
    unknown = BeadCommitAssociation(
        original.label,
        original.target,
        original.bead_id,
        original.subject,
        original.committed_at,
        original.sort_key,
        original.sha,
    )

    rendered = render_page(
        view,
        phase,
        BeadAssociationIndex(
            MappingProxyType({phase.id: BeadAssociations(commits=(unknown,))})
        ),
    )

    assert "| Repo | Commit | Subject | Bead | Committed |" in rendered
    assert "| — | [`9701511`]" in rendered
