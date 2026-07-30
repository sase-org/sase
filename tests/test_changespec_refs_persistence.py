"""Tests for atomic ChangeSpec REFS persistence."""

from pathlib import Path

from sase.ace.changespec.refs_persistence import (
    _apply_refs_update,
    update_changespec_refs_field,
)
from sase.ace.changespec.section_order import CHANGESPEC_SECTION_ORDER


def _spec() -> list[str]:
    return (
        "NAME: example\n"
        "DESCRIPTION:\n"
        "  Example\n"
        "STATUS: Draft\n"
        "COMMITS:\n"
        "  (1) Initial\n"
        "DELTAS:\n"
        "  ~ src/example.py\n"
        "HOOKS:\n"
        "  just check\n"
    ).splitlines(keepends=True)


def test_section_order_places_refs_between_status_and_commits() -> None:
    status = CHANGESPEC_SECTION_ORDER.index("STATUS:")
    refs = CHANGESPEC_SECTION_ORDER.index("REFS:")
    commits = CHANGESPEC_SECTION_ORDER.index("COMMITS:")

    assert refs == status + 1
    assert commits == refs + 1


def test_apply_refs_update_inserts_normalized_refs_in_canonical_position() -> None:
    updated = _apply_refs_update(
        _spec(),
        "example",
        [
            "research:202607/report.md",
            "research:202607/report.md",
            "plans:202607/plan.md",
        ],
    )
    rendered = "".join(updated)

    assert (
        "STATUS: Draft\n"
        "REFS:\n"
        "  research:202607/report.md\n"
        "  plans:202607/plan.md\n"
        "COMMITS:\n"
    ) in rendered
    assert rendered.count("research:202607/report.md") == 1
    assert "DELTAS:\n  ~ src/example.py\n" in rendered


def test_apply_refs_update_replaces_and_removes_existing_section() -> None:
    lines = _apply_refs_update(
        _spec(),
        "example",
        ["research:202607/old.md"],
    )
    replaced = _apply_refs_update(lines, "example", ["plans:202607/new.md"])
    removed = _apply_refs_update(replaced, "example", [])

    assert "research:202607/old.md" not in "".join(replaced)
    assert "  plans:202607/new.md\n" in replaced
    assert "REFS:" not in "".join(removed)
    assert "COMMITS:\n  (1) Initial\n" in "".join(removed)


def test_apply_refs_update_inserts_before_two_blank_line_end() -> None:
    lines = ("NAME: example\nSTATUS: Draft\n\n\nNAME: other\nSTATUS: WIP\n").splitlines(
        keepends=True
    )

    updated = "".join(
        _apply_refs_update(lines, "example", ["research:202607/report.md"])
    )

    assert (
        "STATUS: Draft\nREFS:\n  research:202607/report.md\n\n\nNAME: other\n"
    ) in updated


def test_update_changespec_refs_field_writes_under_atomic_helper(
    tmp_path: Path,
) -> None:
    project_file = tmp_path / "project.sase"
    project_file.write_text("".join(_spec()), encoding="utf-8")

    assert update_changespec_refs_field(
        str(project_file),
        "example",
        ["research:202607/report.md"],
    )

    assert "REFS:\n  research:202607/report.md\n" in project_file.read_text()
