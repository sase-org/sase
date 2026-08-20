"""Rendering coverage for the FlagTriage gate's Markdown preview and note."""

from __future__ import annotations

from sase.bead._flag_gate_preview import (
    flag_triage_presentation_note,
    render_flag_triage_preview,
)
from sase.bead.flag_fields import FlagFields
from sase.feature_flags.references import FlagCallSite

_FLAG = FlagFields(
    key="prettier_enabled",
    kind="sunset",
    remove_by_date="2026-08-01",
    remove_by_release="0.16.0",
)


def _render(**overrides: object) -> str:
    fields: dict[str, object] = {
        "bead_id": "sase-flag.1",
        "title": "Remove the prettier_enabled flag",
        "description": "Roll out the new formatter by default.",
        "notes": "",
        "flag": _FLAG,
        "due_as_of": "2026-08-01",
        "release": "0.16.0",
        "definition": {"kind": "sunset", "description": "Routes prettier formatting."},
        "created_by": "",
        "created_at": "",
        "size": None,
    }
    fields.update(overrides)
    return render_flag_triage_preview(**fields)  # type: ignore[arg-type]


def test_registered_definition_renders_kind_and_description() -> None:
    preview = _render()

    assert "**Kind:** `sunset`" in preview
    assert "## What this flag does" in preview
    assert "Routes prettier formatting." in preview
    assert "## Call sites" in preview
    assert "_No call sites were found when this gate was created._" in preview


def test_populated_call_sites_render_deterministically() -> None:
    preview = _render(
        call_sites=(
            FlagCallSite(path="b.py", line=2, text="enabled('demo')"),
            FlagCallSite(path="a.py", line=10, text="FeatureFlag.demo"),
        )
    )

    call_sites_block = preview.split("## Call sites", 1)[1].split("## Description", 1)[
        0
    ]
    assert "`a.py:10`" in call_sites_block
    assert "`b.py:2`" in call_sites_block
    assert "_No call sites were found when this gate was created._" not in preview


def test_unregistered_definition_renders_warning_callout() -> None:
    preview = _render(definition=None)

    assert "**Kind:**" not in preview
    assert "## What this flag does" not in preview
    assert "No registry definition names this key." in preview
    assert "tools/check_feature_flags" in preview


def test_blank_notes_omit_notes_section() -> None:
    preview = _render(notes="")

    assert "## Notes" not in preview


def test_nonblank_notes_render_notes_section() -> None:
    preview = _render(notes="Extra context for reviewers.")

    assert "## Notes" in preview
    assert "Extra context for reviewers." in preview


def test_backticks_in_definition_kind_are_escaped() -> None:
    preview = _render(definition={"kind": "sun`set", "description": "…"})

    assert "**Kind:** `sun\\`set`" in preview


def test_countdown_text_comes_from_pinned_due_as_of_and_release() -> None:
    due_today = _render(due_as_of="2026-08-01", release="0.16.0")
    assert "DUE ⧗ +0d (as of 2026-08-01, release v0.16.0)" in due_today

    overdue = _render(due_as_of="2026-08-16", release="0.16.0")
    assert "DUE ⧗ +15d (as of 2026-08-16, release v0.16.0)" in overdue

    live = _render(
        flag=FlagFields(
            key="prettier_enabled",
            kind="sunset",
            remove_by_date="2026-12-01",
            remove_by_release="0.20.0",
        ),
        due_as_of="2026-08-01",
        release="0.16.0",
    )
    assert "as of 2026-08-01, release v0.16.0" in live
    assert "DUE" not in live.split("**Status:**")[1].splitlines()[0]


def test_preview_renders_prose_fields_and_d2_answers() -> None:
    preview = _render(
        kind="sunset",
        task_type="flag",
        task_type_fields={
            "key": "prettier_enabled",
            "kind": "sunset",
            "when_enabled": "Format Markdown with prettier.",
            "when_disabled": "Skip prettier.",
            "remove_when": "No escape hatch remains.",
            "remove_by_date": "2026-08-01",
            "remove_by_release": "0.16.0",
        },
    )

    assert "## Feature flag `prettier_enabled` · sunset" in preview
    assert "Format Markdown with prettier." in preview
    assert "Skip prettier." in preview
    assert "No escape hatch remains." in preview
    assert "**Remove** deletes the Off branch" in preview
    assert "**Extend** pushes both thresholds out." in preview
    assert "**Keep** means the behavior is permanent" in preview
    assert "**Close** abandons the removal." in preview


def test_presentation_note_matches_the_preview_countdown() -> None:
    note = flag_triage_presentation_note(
        "sase-flag.1",
        "Remove the prettier_enabled flag",
        _FLAG,
        due_as_of="2026-08-01",
        release="0.16.0",
    )

    assert note == (
        "sase-flag.1 [⚑ prettier_enabled] — Remove the prettier_enabled flag "
        "· DUE ⧗ +0d"
    )
