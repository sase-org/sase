"""Regression tests for ProjectSpec blank-run parsing and duplicate repair."""

from __future__ import annotations

from pathlib import Path

from sase.ace.patch.duplicate_blocks import dedupe_patch_blocks
from sase.ace.patch.duplicate_repair import (
    apply_duplicate_block_repairs,
    plan_duplicate_block_repairs,
)
from sase.ace.patch.parser import parse_project_file
from sase.ace.patch.raw_text import get_raw_patch_text
from sase.ace.patch.storage import format_patch_block
from sase.ace.timestamps.recording import add_timestamp_entry_atomic


def test_release_description_round_trips_through_writer(tmp_path: Path) -> None:
    project_file = tmp_path / "proj.sase"
    project_file.write_text(
        format_patch_block(
            name="release_blank_run_1",
            description="chore(master): release 1.2.3\n\n---\n\n\nBody text",
            pr_url="https://example.test/repo/pull/123",
            pr_origin="external",
            status="Submitted",
        ),
        encoding="utf-8",
    )

    patches = parse_project_file(str(project_file))

    assert len(patches) == 1
    patch = patches[0]
    assert patch.name == "release_blank_run_1"
    assert patch.pr_url == "https://example.test/repo/pull/123"
    assert patch.pr_origin == "external"
    assert patch.status == "Submitted"


def test_writer_collapses_description_blank_runs() -> None:
    block = format_patch_block(
        name="blank_run",
        description="before\n\n \n\n  \nafter",
        status="WIP",
    )
    description_section = block.split("DESCRIPTION:\n", 1)[1].split("STATUS:", 1)[0]

    assert "  before\n  \n  after\n" == description_section
    assert "\n\n" not in description_section


def test_indented_blank_run_is_content_but_true_blank_separator_ends_record(
    tmp_path: Path,
) -> None:
    project_file = tmp_path / "proj.sase"
    project_file.write_text(
        "NAME: release_blank_run_1\n"
        "DESCRIPTION:\n"
        "  chore(master): release 1.2.3\n"
        "  \n"
        "  Body text after one indented blank.\n"
        "  \n"
        "  \n"
        "  Body text after two indented blanks.\n"
        "PR: https://example.test/repo/pull/123\n"
        "PR_ORIGIN: external\n"
        "STATUS: Submitted\n"
        "\n"
        "\n"
        "NAME: second\n"
        "STATUS: WIP\n",
        encoding="utf-8",
    )

    patches = parse_project_file(str(project_file))

    assert [patch.name for patch in patches] == ["release_blank_run_1", "second"]
    assert patches[0].pr_url == "https://example.test/repo/pull/123"
    assert patches[0].pr_origin == "external"
    assert patches[0].status == "Submitted"
    assert (
        patches[0].description == "chore(master): release 1.2.3\n\n"
        "Body text after one indented blank.\n\n\n"
        "Body text after two indented blanks."
    )


def test_raw_patch_text_keeps_indented_blank_run(tmp_path: Path) -> None:
    project_file = tmp_path / "proj.sase"
    project_file.write_text(
        "NAME: release_blank_run_1\n"
        "DESCRIPTION:\n"
        "  first\n"
        "  \n"
        "  \n"
        "  second\n"
        "PR: https://example.test/repo/pull/123\n"
        "STATUS: Submitted\n",
        encoding="utf-8",
    )
    patch = parse_project_file(str(project_file))[0]

    raw = get_raw_patch_text(patch)

    assert raw is not None
    assert "  \n  \n  second\n" in raw
    assert "PR: https://example.test/repo/pull/123" in raw
    assert raw.endswith("STATUS: Submitted")


def test_timestamp_section_is_appended_after_blank_run_description(
    tmp_path: Path,
) -> None:
    project_file = tmp_path / "proj.sase"
    project_file.write_text(
        "NAME: release_blank_run_1\n"
        "DESCRIPTION:\n"
        "  first\n"
        "  \n"
        "  \n"
        "  second\n"
        "PR: https://example.test/repo/pull/123\n"
        "STATUS: Submitted\n",
        encoding="utf-8",
    )

    assert add_timestamp_entry_atomic(
        str(project_file), "release_blank_run_1", "STATUS", "Submitted -> Archived"
    )
    updated = project_file.read_text(encoding="utf-8")

    assert updated.index("TIMESTAMPS:\n") > updated.index("STATUS: Submitted\n")
    assert updated.index("TIMESTAMPS:\n") > updated.index("  \n  \n  second\n")


def test_dedupe_patch_blocks_is_idempotent_and_keeps_last_named_block() -> None:
    clean = (
        "PROJECT_NAME: demo\n\n\nNAME: one\nSTATUS: WIP\n\n\nNAME: two\nSTATUS: Ready\n"
    )
    deduped, scan = dedupe_patch_blocks(clean)
    assert deduped == clean
    assert scan.dropped_blocks == 0

    duplicate = (
        "PROJECT_NAME: demo\n"
        "\n"
        "\n"
        "NAME: one\n"
        "STATUS: WIP\n"
        "\n"
        "\n"
        "NAME: two\n"
        "STATUS: Ready\n"
        "\n"
        "\n"
        "NAME: one\n"
        "STATUS: Submitted\n"
    )
    deduped, scan = dedupe_patch_blocks(duplicate)
    assert deduped == (
        "PROJECT_NAME: demo\n"
        "\n"
        "\n"
        "NAME: two\n"
        "STATUS: Ready\n"
        "\n"
        "\n"
        "NAME: one\n"
        "STATUS: Submitted\n"
    )
    assert scan.duplicate_names == ("one",)
    assert scan.dropped_blocks == 1
    assert scan.reclaimable_bytes == len("\n\nNAME: one\nSTATUS: WIP\n")

    headed = (
        "\n\n## Patch\nNAME: same\nSTATUS: WIP\n\n## Patch\nNAME: same\nSTATUS: Ready\n"
    )
    deduped, scan = dedupe_patch_blocks(headed)
    assert deduped == "\n## Patch\nNAME: same\nSTATUS: Ready\n"
    assert scan.dropped_blocks == 1

    empty_name = "NAME: \nSTATUS: WIP\n\nNAME: \nSTATUS: Ready\n"
    deduped, scan = dedupe_patch_blocks(empty_name)
    assert deduped == empty_name
    assert scan.dropped_blocks == 0


def test_duplicate_block_repair_driver_rewrites_both_files_once(
    tmp_path: Path,
) -> None:
    projects_root = tmp_path / "projects"
    project_dir = projects_root / "proj"
    project_dir.mkdir(parents=True)
    active_file = project_dir / "proj.sase"
    archive_file = project_dir / "proj-archive.sase"
    active_file.write_text(
        "PROJECT_NAME: Demo\n\n\n"
        "NAME: one\nSTATUS: WIP\n\n\n"
        "NAME: one\nSTATUS: Ready\n",
        encoding="utf-8",
    )
    archive_file.write_text(
        "NAME: archived\nSTATUS: Archived\n\n\nNAME: archived\nSTATUS: Submitted\n",
        encoding="utf-8",
    )
    clean_dir = projects_root / "clean"
    clean_dir.mkdir()
    (clean_dir / "clean.sase").write_text(
        "NAME: clean\nSTATUS: WIP\n", encoding="utf-8"
    )

    previews = plan_duplicate_block_repairs(projects_root=projects_root)
    assert [preview.project_key for preview in previews] == ["proj"]
    assert previews[0].active_scan.dropped_blocks == 1
    assert previews[0].archive_scan.dropped_blocks == 1

    results = apply_duplicate_block_repairs(previews)
    assert len(results) == 1
    assert results[0].error is None
    assert results[0].dropped_blocks == 2
    assert "STATUS: WIP" not in active_file.read_text(encoding="utf-8")
    assert "STATUS: Archived" not in archive_file.read_text(encoding="utf-8")

    assert plan_duplicate_block_repairs(projects_root=projects_root) == ()
    second_results = apply_duplicate_block_repairs(previews)
    assert second_results[0].dropped_blocks == 0
    assert clean_dir.joinpath("clean.sase").read_text(encoding="utf-8") == (
        "NAME: clean\nSTATUS: WIP\n"
    )
