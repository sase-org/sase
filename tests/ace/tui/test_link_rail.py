"""Read-only LinkRail rendering tests (bead:sase-ug.6)."""

from __future__ import annotations

from rich.cells import cell_len

from sase.ace.tui.relations.link_index import LinkChip
from sase.ace.tui.widgets.link_rail import _render_link_rail
from sase.core.artifact_entry_target import ArtifactEntryTarget

_DEFAULT_TARGET = ArtifactEntryTarget(
    "ref:plan",
    ("", "archive", "202608/link_rail.md"),
)


def _chip(
    *,
    relation: str = "cites",
    label: str = "cites",
    directed: bool = True,
    this_is_source: bool = True,
    neighbor_ref: str = "plan:202608/link_rail.md",
    neighbor_target: ArtifactEntryTarget | None = _DEFAULT_TARGET,
    accent: str = "#00D7AF",
    icon: str = "✎",
    why: str = "lands the approved rail surface",
    origin: str = "manual",
    uses: int = 1,
    created_by: str = "tester",
) -> LinkChip:
    return LinkChip(
        relation=relation,
        label=label,
        directed=directed,
        this_is_source=this_is_source,
        neighbor_ref=neighbor_ref,
        neighbor_target=neighbor_target,
        accent=accent,
        icon=icon,
        why=why,
        origin=origin,
        uses=uses,
        created_by=created_by,
        created_at="2026-08-26T00:00:00Z",
        writable=origin != "projected",
    )


def test_no_links_render_no_rail() -> None:
    assert _render_link_rail(()) is None


def test_single_link_uses_double_dollar_and_omits_count() -> None:
    text = _render_link_rail((_chip(),), width=120)

    assert text is not None
    plain = text.plain
    assert "LINKS 1" not in plain
    assert "$$" in plain
    assert "$1" not in plain
    assert "$0 all" in plain
    assert "cites" in plain


def test_trailing_links_use_relation_sigils() -> None:
    text = _render_link_rail(
        (
            _chip(relation="implements", label="implements"),
            _chip(
                relation="related",
                label="related",
                directed=False,
                neighbor_ref="bead:sase-ug",
                neighbor_target=ArtifactEntryTarget("beads", ("", "epic", "sase-ug")),
                icon="◈",
                why="",
            ),
        ),
        width=160,
    )

    assert text is not None
    plain = text.plain
    assert "$1 → implements" in plain
    assert "$2 ↔ rel" in plain


def test_width_pressure_drops_tail_without_renumbering_visible_chips() -> None:
    chips = tuple(
        _chip(
            neighbor_ref=f"plan:202608/link_rail_{index}.md",
            why="a deliberately long reason that drops before keys move",
        )
        for index in range(1, 5)
    )

    text = _render_link_rail(chips, width=82)

    assert text is not None
    plain = text.plain
    assert cell_len(plain) <= 82
    assert "$1" in plain
    assert "$0 +" in plain


def test_projected_same_rule_same_kind_edges_collapse_to_counted_chip() -> None:
    chips = tuple(
        _chip(
            relation="implements",
            label="implemented-by",
            this_is_source=False,
            neighbor_ref=f"stitch:sase@0123456789abcdef0123456789abcde{index:03d}",
            neighbor_target=ArtifactEntryTarget(
                "stitches",
                ("sase", f"0123456789abcdef0123456789abcde{index:03d}"),
            ),
            origin="projected",
            created_by="projection:stitch-bead",
            icon="◆",
            why="",
        )
        for index in range(12)
    )

    text = _render_link_rail(chips, width=120)

    assert text is not None
    plain = text.plain
    assert "$1 ← implemented-by" in plain
    assert "12 stitches" in plain
    assert "$2" not in plain
    assert "$0 all" in plain


def test_dangling_link_stays_visible_and_marks_missing_target() -> None:
    text = _render_link_rail(
        (
            _chip(
                neighbor_ref="plan:202608/missing.md",
                neighbor_target=None,
            ),
        ),
        width=120,
    )

    assert text is not None
    plain = text.plain
    assert "⊘" in plain
    assert "(missing)" in plain


def test_chop_neighbor_without_artifact_target_is_not_missing() -> None:
    text = _render_link_rail(
        (
            _chip(
                relation="launched",
                label="launched-by",
                this_is_source=False,
                neighbor_ref="chop:hooks/build",
                neighbor_target=None,
                icon="⚒",
            ),
        ),
        width=120,
    )

    assert text is not None
    plain = text.plain
    assert "hooks/build" in plain
    assert "(missing)" not in plain
