"""Tests for the bead page address contract."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.bead.conflict_resolver import resolve_beads_dir
from sase.bead.model import IssueType
from sase.bead.project import (
    BEADS_DIRNAME,
    BEADS_DIRNAME_NON_VC,
    BEADS_DIRNAME_ROOT,
    BeadProject,
)
from sase.bead_pages.paths import (
    BEAD_PAGES_DIRNAME,
    bead_lineage_root,
    bead_page_path,
    bead_page_root,
)


@pytest.mark.parametrize(
    ("bead_id", "expected"),
    [
        ("sase-ag", "sase-ag"),
        ("sase-ag.1", "sase-ag"),
        ("sase-ag.land", "sase-ag"),
        ("sase-26.1.1", "sase-26"),
        ("  sase-ag.2  ", "sase-ag"),
    ],
)
def test_lineage_root_is_the_segment_before_the_first_dot(
    bead_id: str, expected: str
) -> None:
    assert bead_lineage_root(bead_id) == expected
    assert bead_page_root(bead_id) == f"{BEAD_PAGES_DIRNAME}/{expected}"


@pytest.mark.parametrize(
    ("bead_id", "expected"),
    [
        ("sase-ag", "pages/sase-ag/README.md"),
        ("sase-ag.1", "pages/sase-ag/sase-ag.1.md"),
        ("sase-ag.land", "pages/sase-ag/sase-ag.land.md"),
        ("sase-26.1.1", "pages/sase-26/sase-26.1.1.md"),
        ("  sase-ag.2  ", "pages/sase-ag/sase-ag.2.md"),
    ],
)
def test_page_path_gives_the_lineage_root_the_directory_readme(
    bead_id: str, expected: str
) -> None:
    assert bead_page_path(bead_id) == expected


@pytest.mark.parametrize(
    "bead_id",
    ["", "   ", "sase-ag/../escape", "sase ag", "sase-ag/1", "sase-ag.", ".sase-ag"],
)
def test_page_path_rejects_ids_that_cannot_address_a_file(bead_id: str) -> None:
    with pytest.raises(ValueError):
        bead_page_path(bead_id)


def test_pages_dirname_can_never_shadow_a_bead_store(tmp_path: Path) -> None:
    """A ``pages/`` directory must not make ``resolve_beads_dir`` ambiguous."""

    assert BEAD_PAGES_DIRNAME not in {
        BEADS_DIRNAME,
        BEADS_DIRNAME_NON_VC,
        BEADS_DIRNAME_ROOT,
    }

    sidecar = tmp_path / "sase--beads"
    sidecar.mkdir()
    with BeadProject.init(sidecar, beads_dirname=BEADS_DIRNAME_ROOT):
        pass
    (sidecar / BEAD_PAGES_DIRNAME / "sase-ag").mkdir(parents=True)
    (sidecar / BEAD_PAGES_DIRNAME / "sase-ag" / "README.md").write_text(
        "# Bead: sase-ag\n", encoding="utf-8"
    )

    assert resolve_beads_dir(sidecar) == sidecar.resolve()


def test_lexical_root_agrees_with_the_stored_parent_chain(tmp_path: Path) -> None:
    """Following ``parent_id`` must reach the same root the id spells out."""

    with BeadProject.init(tmp_path) as project:
        epic = project.create("Epic", IssueType.PLAN)
        phase = project.create("Phase", IssueType.PHASE, parent_id=epic.id)
        grandchild = project.create("Nested", IssueType.PHASE, parent_id=phase.id)

        for issue in (epic, phase, grandchild):
            walked = issue
            seen = {walked.id}
            while walked.parent_id and walked.parent_id not in seen:
                seen.add(walked.parent_id)
                walked = project.show(walked.parent_id)
            assert bead_lineage_root(issue.id) == walked.id
