"""Tests for project ref ownership, conflicts, and validation."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.project_aliases import find_project_ref_owner
from tests._project_alias_services_helpers import _record
from tests.main.project_handler_helpers import (
    _write_project,
    projects_root,
)

__all__ = ["projects_root"]


def test_find_project_ref_owner_reports_display_name_and_alias_claims(
    projects_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gh_file = _write_project(
        projects_root,
        "gh_acme__sase",
        "PROJECT_NAME: sase\nPROJECT_ALIASES: widgets\n"
        "WORKSPACE_DIR: /tmp/gh\nNAME: g\n",
    )

    monkeypatch.setattr(
        "sase.project_aliases.list_project_records",
        lambda *_args, **_kwargs: [
            _record(
                "gh_acme__sase",
                project_file=gh_file,
                display_name="sase",
                aliases=["widgets"],
            ),
        ],
    )

    assert find_project_ref_owner("sase", projects_root) == "gh_acme__sase"
    assert find_project_ref_owner("widgets", projects_root) == "gh_acme__sase"
    assert find_project_ref_owner("gh_acme__sase", projects_root) is None
    assert find_project_ref_owner("unclaimed", projects_root) is None


def test_project_ref_conflicts_from_records_reports_directory_key_collision() -> None:
    from sase.project_alias_records import project_ref_conflicts_from_records

    stray = _record(
        "sase",
        archive_file="/tmp/projects/sase/sase.archive",
    )
    canonical = _record(
        "gh_acme__sase",
        archive_file="/tmp/projects/gh_acme__sase/gh_acme__sase.archive",
        display_name="sase",
        aliases=["widgets"],
    )

    conflicts = project_ref_conflicts_from_records([stray, canonical])

    assert len(conflicts) == 1
    conflict = conflicts[0]
    assert conflict.ref == "sase"
    assert conflict.kind == "PROJECT_NAME"
    assert conflict.claimant == "gh_acme__sase"
    assert conflict.occupant == "sase"
    assert conflict.claimant_workspace_dir == "/tmp/workspaces/gh_acme__sase"
    assert conflict.occupant_workspace_dir == "/tmp/workspaces/sase"


def test_project_ref_case_variant_collisions_are_rejected() -> None:
    from sase.project_alias_records import (
        project_alias_map_from_records,
        project_ref_conflicts_from_records,
        validate_project_aliases,
        validate_project_name,
    )

    occupied = _record(
        "sase",
        archive_file="/tmp/projects/sase/sase.archive",
    )

    with pytest.raises(ValueError, match="conflicts with a real project name"):
        validate_project_name(
            "gh_acme__sase",
            "Sase",
            [
                occupied,
                _record(
                    "gh_acme__sase",
                    archive_file="/tmp/projects/gh_acme__sase/gh_acme__sase.archive",
                ),
            ],
        )

    with pytest.raises(ValueError, match="conflicts with a real project name"):
        validate_project_aliases(
            "gh_acme__sase",
            ["SASE"],
            [
                occupied,
                _record(
                    "gh_acme__sase",
                    archive_file="/tmp/projects/gh_acme__sase/gh_acme__sase.archive",
                ),
            ],
        )

    with pytest.raises(ValueError, match="assigned to both"):
        project_alias_map_from_records(
            [
                _record(
                    "alpha",
                    archive_file="/tmp/projects/alpha/alpha.archive",
                    aliases=["Widgets"],
                ),
                _record(
                    "beta",
                    archive_file="/tmp/projects/beta/beta.archive",
                    aliases=["widgets"],
                ),
            ]
        )

    conflicts = project_ref_conflicts_from_records(
        [
            occupied,
            _record(
                "gh_acme__sase",
                archive_file="/tmp/projects/gh_acme__sase/gh_acme__sase.archive",
                display_name="SASE",
            ),
        ]
    )
    assert len(conflicts) == 1
    assert conflicts[0].ref == "SASE"
    assert conflicts[0].claimant == "gh_acme__sase"
    assert conflicts[0].occupant == "sase"


def test_project_ref_home_is_reserved() -> None:
    from sase.project_alias_records import (
        allocate_project_name,
        project_ref_conflicts_from_records,
        validate_project_aliases,
        validate_project_name,
    )

    records = [
        _record("alpha", archive_file="/tmp/projects/alpha/alpha.archive"),
    ]

    with pytest.raises(ValueError, match="reserved"):
        validate_project_name("alpha", "Home", records)
    with pytest.raises(ValueError, match="reserved"):
        validate_project_aliases("alpha", ["home"], records)
    assert allocate_project_name("home", records) == "home_1"

    conflicts = project_ref_conflicts_from_records(
        [
            _record(
                "alpha",
                archive_file="/tmp/projects/alpha/alpha.archive",
                aliases=["HOME"],
            ),
        ]
    )
    assert len(conflicts) == 1
    assert conflicts[0].ref == "HOME"
    assert conflicts[0].occupant == "home"


def test_project_ref_conflicts_reports_case_only_directory_keys() -> None:
    from sase.project_alias_records import project_ref_conflicts_from_records

    conflicts = project_ref_conflicts_from_records(
        [
            _record(
                "Widgets",
                archive_file="/tmp/projects/Widgets/Widgets.archive",
            ),
            _record(
                "widgets",
                archive_file="/tmp/projects/widgets/widgets.archive",
            ),
        ]
    )

    assert len(conflicts) == 1
    conflict = conflicts[0]
    assert conflict.ref == "widgets"
    assert conflict.kind == "directory key"
    assert conflict.claimant == "widgets"
    assert conflict.occupant == "Widgets"
    assert conflict.occupant_kind == "directory key"
    assert conflict.claimant_workspace_dir == "/tmp/workspaces/widgets"
    assert conflict.occupant_workspace_dir == "/tmp/workspaces/Widgets"


def test_project_ref_conflicts_reports_home_folded_directory_key() -> None:
    from sase.project_alias_records import project_ref_conflicts_from_records

    conflicts = project_ref_conflicts_from_records(
        [
            _record(
                "Home",
                archive_file="/tmp/projects/Home/Home.archive",
            ),
        ]
    )

    assert len(conflicts) == 1
    conflict = conflicts[0]
    assert conflict.ref == "Home"
    assert conflict.kind == "directory key"
    assert conflict.claimant == "Home"
    assert conflict.occupant == "home"


def test_project_ref_conflicts_marks_earlier_alias_claimant() -> None:
    from sase.project_alias_records import project_ref_conflicts_from_records

    conflicts = project_ref_conflicts_from_records(
        [
            _record(
                "alpha",
                archive_file="/tmp/projects/alpha/alpha.archive",
                aliases=["Widgets"],
            ),
            _record(
                "beta",
                archive_file="/tmp/projects/beta/beta.archive",
                aliases=["widgets"],
            ),
        ]
    )

    assert len(conflicts) == 1
    conflict = conflicts[0]
    assert conflict.kind == "project alias"
    assert conflict.claimant == "beta"
    assert conflict.occupant == "alpha"
    assert conflict.occupant_kind == "project alias"


def test_find_project_ref_owner_is_case_insensitive(
    projects_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gh_file = _write_project(
        projects_root,
        "gh_acme__sase",
        "PROJECT_NAME: sase\nPROJECT_ALIASES: widgets\n"
        "WORKSPACE_DIR: /tmp/gh\nNAME: g\n",
    )

    monkeypatch.setattr(
        "sase.project_aliases.list_project_records",
        lambda *_args, **_kwargs: [
            _record("sase", project_file=gh_file),
            _record(
                "gh_acme__sase",
                project_file=gh_file,
                display_name="sase",
                aliases=["widgets"],
            ),
        ],
    )

    assert find_project_ref_owner("Sase", projects_root) == "sase"
    assert find_project_ref_owner("WIDGETS", projects_root) == "gh_acme__sase"
    # Exact "home" keeps historical behavior (first-use auto-init); only
    # case-variants report the reserved owner.
    assert find_project_ref_owner("home", projects_root) is None
    assert find_project_ref_owner("HOME", projects_root) == "home"
    assert find_project_ref_owner("Home", projects_root) == "home"
