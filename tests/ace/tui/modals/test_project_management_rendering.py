"""Unit tests for Projects sub-tab current-project rendering."""

from __future__ import annotations

from sase.ace.tui.modals.project_management_rendering import (
    column_header_text,
    detail_text,
    record_label,
    summary_text,
)
from sase.current_project import CurrentProject

from .project_management_modal_test_helpers import make_project_record

_ACCENT = "#C5547D"


def _project(
    *,
    project_key: str = "sase",
    display_name: str = "sase",
    origin: str = "project",
    origin_ref: str | None = None,
    workflow_type: str = "gh",
) -> CurrentProject:
    return CurrentProject(
        project_key=project_key,
        display_name=display_name,
        origin=origin,  # type: ignore[arg-type]
        origin_ref=origin_ref or project_key,
        workflow_type=workflow_type,
    )


def _spans(text: object) -> list[tuple[str, str]]:
    return [
        (text.plain[span.start : span.end], str(span.style))  # type: ignore[union-attr]
        for span in text.spans  # type: ignore[union-attr]
    ]


def test_column_header_inserts_cur_between_mark_and_name() -> None:
    header = column_header_text().plain

    assert header.startswith("MARK CUR NAME")
    assert header.index("CUR") < header.index("NAME")


def test_record_label_marks_only_the_current_row_with_accent() -> None:
    current = make_project_record("sase")
    other = make_project_record("bob-cli")

    current_row = record_label(
        current,
        set(),
        current_project_key="sase",
        current_project_accent=_ACCENT,
    )
    other_row = record_label(
        other,
        set(),
        current_project_key="sase",
        current_project_accent=_ACCENT,
    )

    assert current_row.plain[5:9] == "+   "
    assert other_row.plain[5:9] == "    "
    assert ("+   ", f"bold {_ACCENT}") in _spans(current_row)
    assert any(
        fragment.startswith("sase") and style == f"bold {_ACCENT}"
        for fragment, style in _spans(current_row)
    )
    assert any(
        fragment.startswith("bob-cli") and style == "bold"
        for fragment, style in _spans(other_row)
    )


def test_record_label_can_be_both_marked_and_current() -> None:
    record = make_project_record("sase")
    row = record_label(
        record,
        {"sase"},
        current_project_key="sase",
        current_project_accent=_ACCENT,
    )

    assert row.plain.startswith("[✓]")
    assert row.plain[5:9] == "+   "


def test_summary_text_dim_ellipsis_before_resolve() -> None:
    text = summary_text([], "", "", set(), current_project_loaded=False)

    assert "current:…" in text.plain
    assert ("…", "dim") in _spans(text)


def test_summary_text_none_after_empty_resolve() -> None:
    text = summary_text([], "", "", set(), current_project_loaded=True)

    assert "current:none" in text.plain
    assert ("none", "dim") in _spans(text)


def test_summary_text_renders_chip_for_resolved_name() -> None:
    text = summary_text(
        [],
        "",
        "",
        set(),
        current_project_key="gh_sase-org__sase",
        current_project_name="sase",
        current_project_accent=_ACCENT,
        current_project_loaded=True,
    )

    assert "current:+sase" in text.plain
    assert ("+", f"dim {_ACCENT}") in _spans(text)
    assert ("sase", f"bold {_ACCENT}") in _spans(text)


def test_summary_text_still_renders_when_project_is_not_in_records() -> None:
    records = [make_project_record("alpha")]
    text = summary_text(
        records,
        "",
        "",
        set(),
        current_project_key="ghost",
        current_project_name="ghost",
        current_project_accent=_ACCENT,
        current_project_loaded=True,
    )
    row = record_label(
        records[0],
        set(),
        current_project_key="ghost",
        current_project_accent=_ACCENT,
    )

    assert "current:+ghost" in text.plain
    assert row.plain[5:9] == "    "


def test_detail_text_current_via_project() -> None:
    record = make_project_record(
        "gh_sase-org__sase",
        display_name="sase",
    )
    project = _project(
        project_key="gh_sase-org__sase",
        display_name="sase",
        origin_ref="gh_sase-org__sase",
    )
    text = detail_text(
        record,
        set(),
        current_project=project,
        current_project_key=project.project_key,
        current_project_accent=_ACCENT,
    )

    assert "+CURRENT" in text.plain
    assert "Current project: yes  ·  via #gh:gh_sase-org__sase" in text.plain
    assert ("    +CURRENT", f"bold {_ACCENT}") in _spans(text)


def test_detail_text_current_via_patch() -> None:
    record = make_project_record("sase")
    project = _project(origin="patch", origin_ref="fix-flaky-retry")
    text = detail_text(
        record,
        set(),
        current_project=project,
        current_project_key=project.project_key,
        current_project_accent=_ACCENT,
    )

    assert (
        "Current project: yes  ·  via Patch fix-flaky-retry (#gh:fix-flaky-retry)"
        in text.plain
    )


def test_detail_text_eligible_row_names_the_set_key() -> None:
    record = make_project_record("bob-cli")
    text = detail_text(record, set(), current_project_key="sase")

    assert "Current project: no   ·  press c to make bob-cli current" in text.plain
    assert "+CURRENT" not in text.plain


def test_detail_text_disabled_row_names_enable() -> None:
    record = make_project_record(
        "widgets",
        state="disabled",
        launchable=False,
    )
    text = detail_text(record, set(), current_project_key="sase")

    assert "Current project: no   ·  enable widgets first (a), then press c" in (
        text.plain
    )


def test_detail_text_not_launchable_names_project_spec() -> None:
    record = make_project_record("widgets", launchable=False)
    text = detail_text(record, set(), current_project_key="sase")

    assert "Current project: no   ·  widgets has no launchable ProjectSpec" in (
        text.plain
    )
