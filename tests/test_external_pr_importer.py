"""Two-file external PR importer coverage."""

from __future__ import annotations

from pathlib import Path

from sase.ace.patch.importer import external_pr_import_batch, project_patch_files
from sase.ace.patch.parser import parse_project_file
from sase.axe.patch_filtering import filter_axe_candidate_patches
from sase.core.external_pr_wire import (
    ACTION_ADOPT,
    ACTION_REFRESH,
    ACTION_REPAIR_ORIGIN,
    DESTINATION_ACTIVE,
    DESTINATION_ARCHIVE,
    PR_ORIGIN_EXTERNAL,
    PR_ORIGIN_SASE,
    REASON_ALREADY_OWNED,
    REASON_MARKER_ORPHAN,
    REASON_MARKER_REPAIR,
    REASON_RACED_ALREADY_OWNED,
    REASON_UNMARKED,
    ExternalPrImportPlanWire,
)


def _plan(
    *,
    action: str = ACTION_ADOPT,
    reason: str = REASON_UNMARKED,
    patch_name: str | None = None,
    name_base: str | None = "feature",
    pr_origin: str = PR_ORIGIN_EXTERNAL,
    status: str = "Mailed",
    destination: str = DESTINATION_ACTIVE,
    description: str = "Feature title\n\nBody",
    pr_url: str = "https://github.com/acme/widget/pull/5",
) -> ExternalPrImportPlanWire:
    return ExternalPrImportPlanWire(
        action=action,
        reason=reason,
        patch_name=patch_name,
        name_base=name_base,
        pr_origin=pr_origin,
        status=status,
        destination=destination,
        description=description,
        canonical_pr_url=pr_url,
    )


def _write_project(project: str, content: str) -> tuple[str, str]:
    active_file, archive_file = project_patch_files(project)
    Path(active_file).parent.mkdir(parents=True, exist_ok=True)
    Path(active_file).write_text(content, encoding="utf-8")
    return active_file, archive_file


def _apply_plan(project: str, plan: ExternalPrImportPlanWire):
    with external_pr_import_batch(project) as batch:
        return batch.apply(plan)


def test_crash_window_repairs_reserved_patch_and_second_pass_skips() -> None:
    active_file, _ = _write_project(
        "proj",
        "NAME: proj_feature_1\nSTATUS: Reserved\n",
    )
    plan = _plan(
        action=ACTION_REPAIR_ORIGIN,
        reason=REASON_MARKER_REPAIR,
        patch_name="proj_feature_1",
        name_base=None,
        pr_origin=PR_ORIGIN_SASE,
    )

    outcome = _apply_plan("proj", plan)
    assert outcome.action_taken == "repaired"
    patches = parse_project_file(active_file)
    assert [patch.name for patch in patches] == ["proj_feature_1"]
    assert patches[0].pr_url == "https://github.com/acme/widget/pull/5"
    assert patches[0].pr_origin == "sase"
    assert patches[0].status == "Mailed"

    second = _apply_plan("proj", plan)
    assert second.action_taken == "skipped"
    assert [patch.name for patch in parse_project_file(active_file)] == [
        "proj_feature_1"
    ]


def test_merged_pr_is_written_directly_to_archive() -> None:
    active_file, archive_file = _write_project("proj", "")
    outcome = _apply_plan(
        "proj",
        _plan(
            name_base="merged_pr",
            status="Submitted",
            destination=DESTINATION_ARCHIVE,
        ),
    )

    assert outcome.action_taken == "created"
    assert parse_project_file(active_file) == []
    archived = parse_project_file(archive_file)
    assert [patch.status for patch in archived] == ["Submitted"]


def test_repaired_merged_marker_patch_moves_to_archive() -> None:
    active_file, archive_file = _write_project(
        "proj",
        "NAME: proj_feature_1\nSTATUS: Reserved\n",
    )

    outcome = _apply_plan(
        "proj",
        _plan(
            action=ACTION_REPAIR_ORIGIN,
            reason=REASON_MARKER_REPAIR,
            patch_name="proj_feature_1",
            name_base=None,
            pr_origin=PR_ORIGIN_SASE,
            status="Submitted",
            destination=DESTINATION_ARCHIVE,
        ),
    )

    assert outcome.action_taken == "repaired"
    assert outcome.destination_file == archive_file
    assert parse_project_file(active_file) == []
    archived = parse_project_file(archive_file)
    assert [patch.name for patch in archived] == ["proj_feature_1"]
    assert [patch.status for patch in archived] == ["Submitted"]


def test_name_uniqueness_spans_active_and_archive_files() -> None:
    _, archive_file = _write_project(
        "proj",
        "NAME: feature_1\nSTATUS: WIP\n",
    )
    Path(archive_file).write_text(
        "NAME: feature_2\nSTATUS: Archived\n", encoding="utf-8"
    )

    outcome = _apply_plan("proj", _plan(name_base="feature"))

    assert outcome.patch_name == "feature_3"


def test_url_variant_idempotency_does_not_duplicate() -> None:
    active_file, _ = _write_project(
        "proj",
        "NAME: owned\nDESCRIPTION:\n  Existing\n"
        "PR: http://www.GITHUB.com/ACME/WIDGET.git/pulls/5/\n"
        "STATUS: Mailed\n",
    )

    outcome = _apply_plan("proj", _plan(name_base="feature"))

    assert outcome.action_taken == "skipped"
    assert [patch.name for patch in parse_project_file(active_file)] == ["owned"]


def test_external_adoption_is_excluded_from_axe_candidates() -> None:
    active_file, _ = _write_project("proj", "")
    _apply_plan("proj", _plan(name_base="feature"))

    patches = parse_project_file(active_file)
    assert [patch.pr_origin for patch in patches] == ["external"]
    assert filter_axe_candidate_patches(patches) == []


def test_external_adoption_with_blank_run_is_idempotent() -> None:
    active_file, _ = _write_project("proj", "")
    plan = _plan(
        description=(
            "chore(master): release 1.2.3\n\n"
            "---\n\n\n"
            ":robot: Body text after a blank run."
        )
    )

    first = _apply_plan("proj", plan)
    second = _apply_plan("proj", plan)

    assert first.action_taken == "created"
    assert second.action_taken == "skipped"
    assert Path(active_file).read_text(encoding="utf-8").count("NAME: feature_1") == 1
    patches = parse_project_file(active_file)
    assert [patch.pr_url for patch in patches] == [
        "https://github.com/acme/widget/pull/5"
    ]


def test_marker_orphan_uses_marker_name_verbatim() -> None:
    active_file, _ = _write_project("proj", "")
    outcome = _apply_plan(
        "proj",
        _plan(
            reason=REASON_MARKER_ORPHAN,
            patch_name="proj_marker_7",
            name_base=None,
            pr_origin=PR_ORIGIN_SASE,
        ),
    )

    assert outcome.patch_name == "proj_marker_7"
    assert [patch.name for patch in parse_project_file(active_file)] == [
        "proj_marker_7"
    ]


def _refresh_plan(*, status: str, destination: str) -> ExternalPrImportPlanWire:
    return _plan(
        action=ACTION_REFRESH,
        reason=REASON_ALREADY_OWNED,
        patch_name="proj_pr_5",
        name_base=None,
        pr_origin=PR_ORIGIN_EXTERNAL,
        status=status,
        destination=destination,
    )


def _external_owned_patch(status: str) -> str:
    return (
        "NAME: proj_pr_5\nDESCRIPTION:\n  Widget change\n"
        "PR: https://github.com/acme/widget/pull/5\n"
        f"PR_ORIGIN: external\nSTATUS: {status}\n"
    )


def test_refresh_moves_merged_external_patch_from_active_to_archive() -> None:
    active_file, archive_file = _write_project("proj", _external_owned_patch("Mailed"))

    outcome = _apply_plan(
        "proj",
        _refresh_plan(status="Submitted", destination=DESTINATION_ARCHIVE),
    )

    assert outcome.action_taken == "refreshed"
    assert outcome.destination_file == archive_file
    assert parse_project_file(active_file) == []
    archived = parse_project_file(archive_file)
    assert [patch.name for patch in archived] == ["proj_pr_5"]
    assert [patch.status for patch in archived] == ["Submitted"]
    assert archived[0].pr_origin == "external"
    assert archived[0].description == "Widget change"


def test_refresh_maps_closed_unmerged_patch_to_archived() -> None:
    active_file, archive_file = _write_project("proj", _external_owned_patch("Mailed"))

    outcome = _apply_plan(
        "proj",
        _refresh_plan(status="Archived", destination=DESTINATION_ARCHIVE),
    )

    assert outcome.action_taken == "refreshed"
    assert parse_project_file(active_file) == []
    archived = parse_project_file(archive_file)
    assert [patch.status for patch in archived] == ["Archived"]


def test_refresh_guards_against_raced_ownership_change() -> None:
    active_file, _ = _write_project(
        "proj",
        "NAME: proj_pr_5\nDESCRIPTION:\n  Widget change\n"
        "PR: https://github.com/acme/widget/pull/5\n"
        "PR_ORIGIN: sase\nSTATUS: Mailed\n",
    )

    outcome = _apply_plan(
        "proj",
        _refresh_plan(status="Submitted", destination=DESTINATION_ARCHIVE),
    )

    assert outcome.action_taken == "skipped"
    assert outcome.reason == REASON_RACED_ALREADY_OWNED
    patches = parse_project_file(active_file)
    assert [patch.status for patch in patches] == ["Mailed"]
    assert [patch.pr_origin for patch in patches] == ["sase"]
