"""Rendering coverage for the BeadStaleCleanup gate's Markdown preview and note."""

from __future__ import annotations

from types import SimpleNamespace

from sase.bead._stale_cleanup_gate_preview import (
    bead_stale_cleanup_presentation_note,
    render_bead_stale_cleanup_preview,
)

from .stale_cleanup_gate_test_helpers import DEFAULT_STALE_AS_OF, stale_cleanup_bead


def _payload(**overrides: object) -> SimpleNamespace:
    fields: dict[str, object] = {
        "beads": [stale_cleanup_bead()],
        "omitted_count": 0,
        "min_plus_ones": 1,
        "stale_after_days": 7,
        "stale_cleanup_min_beads": 10,
        "stale_as_of": DEFAULT_STALE_AS_OF,
    }
    fields.update(overrides)
    return SimpleNamespace(**fields)


def test_preview_is_byte_identical_across_two_renders_of_the_same_payload() -> None:
    payload = _payload(omitted_count=3)
    assert render_bead_stale_cleanup_preview(
        payload
    ) == render_bead_stale_cleanup_preview(payload)


def test_preview_ages_derive_from_stale_as_of_not_the_wall_clock() -> None:
    early = render_bead_stale_cleanup_preview(
        _payload(stale_as_of="2026-08-08T09:14:02-04:00")
    )
    later = render_bead_stale_cleanup_preview(
        _payload(stale_as_of="2026-08-17T11:00:00-04:00")
    )

    assert "| sase-task.1 | sase | 7d |" in early
    assert "| sase-task.1 | sase | 16d |" in later
    assert "7d" not in later.split("sase-task.1", 1)[1].splitlines()[0]


def test_preview_renders_display_names_never_project_spec_keys(
    monkeypatch: object,
) -> None:
    def _label(project: str) -> str:
        return "sase" if project == "gh_sase-org__sase" else project

    monkeypatch.setattr(  # type: ignore[attr-defined]
        "sase.bead._stale_cleanup_gate_preview.stale_cleanup_project_label",
        _label,
    )
    preview = render_bead_stale_cleanup_preview(
        _payload(beads=[stale_cleanup_bead(project="gh_sase-org__sase")])
    )

    assert "gh_sase-org__sase" not in preview
    assert "| sase-task.1 | sase |" in preview


def test_omitted_footer_appears_only_when_omitted_count_is_positive() -> None:
    without = render_bead_stale_cleanup_preview(_payload(omitted_count=0))
    with_omitted = render_bead_stale_cleanup_preview(_payload(omitted_count=12))

    assert "omitted" not in without
    assert "12 additional stale task beads were omitted from this roster." in (
        with_omitted
    )


def test_presentation_note_names_count_and_thresholds() -> None:
    note = bead_stale_cleanup_presentation_note(
        _payload(
            beads=[stale_cleanup_bead(), stale_cleanup_bead(bead_id="sase-task.2")]
        )
    )

    assert note == "2 stale task beads · no +1 after 7 days"
