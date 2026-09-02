"""Parser, roster, and validation coverage for strand supersession metadata."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.markdown_width import markdown_print_width
from sase.memory.web import (
    StrandSupersession,
    discover_memory_webs,
    format_roster_supersession_marker,
    parse_strand_supersession,
    render_strand_roster,
    validate_memory_webs,
)
from sase.memory.web.models import MemoryStrand


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _descriptor(*, roster: str = "inline", extra: str = "") -> str:
    return (
        "---\n"
        "web: true\n"
        f"roster: {roster}\n"
        "roster_label: TERMS\n"
        f"{extra}"
        "---\n\n"
        "Descriptor body.\n"
    )


def _strand(
    *,
    keyword: str = "Alpha Term",
    aliases: str = "aliases: [alpha]\n",
    summary: str = "summary: First term.\n",
    extra: str = "",
    body: str = "Strand body.\n",
) -> str:
    return f"---\nkeyword: {keyword}\n{aliases}{summary}{extra}---\n\n{body}"


def _strand_model(
    *,
    metadata: dict[str, object] | None = None,
    body: str = "Body.\n",
    web_slug: str = "terms",
    slug: str = "alpha",
) -> MemoryStrand:
    return MemoryStrand(
        root=Path("/"),
        memory_root=Path("/memory"),
        web_slug=web_slug,
        slug=slug,
        path=Path(f"/memory/{web_slug}/{slug}.md"),
        relative_path=f"sase/memory/{web_slug}/{slug}.md",
        keyword="Alpha",
        aliases=(),
        summary="Summary.",
        metadata={} if metadata is None else metadata,
        body=body,
        raw_text="",
        body_start=0,
        frontmatter={},
    )


def _seed_terms(
    tmp_path: Path,
    *,
    roster: str = "list",
    alpha_extra: str = "",
    alpha_body: str = "Strand body.\n",
    extra_strands: dict[str, str] | None = None,
    descriptor_extra: str = "",
) -> None:
    _write(
        tmp_path / "sase" / "memory" / "terms.md",
        _descriptor(roster=roster, extra=descriptor_extra),
    )
    _write(
        tmp_path / "sase" / "memory" / "terms" / "alpha.md",
        _strand(extra=alpha_extra, body=alpha_body),
    )
    for slug, content in (extra_strands or {}).items():
        _write(tmp_path / "sase" / "memory" / "terms" / f"{slug}.md", content)


@pytest.mark.parametrize(
    "metadata",
    [
        None,
        {},
        {"status": "accepted"},
        {"status": "accepted", "superseded_by": "terms/beta"},
        {"status": "superseded"},
        {"status": "superseded", "superseded_by": []},
        {"status": "superseded", "superseded_by": ""},
        {"status": "superseded", "superseded_by": [""]},
        {"status": "superseded", "superseded_by": [1]},
        {"status": "superseded", "superseded_by": {"target": "terms/beta"}},
        {"status": "superseded-in-part", "superseded_by": ["terms/beta", ""]},
        {"decided": "2026-08-24"},
    ],
)
def test_parse_strand_supersession_returns_none_for_absent_or_malformed(
    metadata: dict[str, object] | None,
) -> None:
    assert parse_strand_supersession(_strand_model(metadata=metadata)) is None


def test_parse_strand_supersession_accepts_string_and_list_targets() -> None:
    whole = parse_strand_supersession(
        _strand_model(metadata={"status": "superseded", "superseded_by": "terms/beta"})
    )
    assert whole == StrandSupersession(
        status="superseded",
        partial=False,
        superseded_by=("terms/beta",),
    )

    partial = parse_strand_supersession(
        _strand_model(
            metadata={
                "status": "superseded-in-part",
                "decided": "2026-08-24",
                "superseded_by": [
                    "decisions/webs-render-in-their-own-section",
                    "decisions/memory-links-are-authored",
                ],
            }
        )
    )
    assert partial == StrandSupersession(
        status="superseded-in-part",
        partial=True,
        superseded_by=(
            "decisions/webs-render-in-their-own-section",
            "decisions/memory-links-are-authored",
        ),
    )


def test_roster_marker_strips_same_web_slash_prefix_only() -> None:
    supersession = StrandSupersession(
        status="superseded-in-part",
        partial=True,
        superseded_by=("terms/beta", "other/gamma", "terms:delta"),
    )

    assert (
        format_roster_supersession_marker(supersession, web_slug="terms")
        == "_[partly superseded by `beta`, `other/gamma`, `terms:delta`]_"
    )
    assert (
        format_roster_supersession_marker(
            StrandSupersession(
                status="superseded", partial=False, superseded_by=("terms/beta",)
            ),
            web_slug="terms",
        )
        == "_[superseded by `beta`]_"
    )


def test_roster_list_inserts_marker_and_still_lists_the_strand(
    tmp_path: Path,
) -> None:
    _seed_terms(
        tmp_path,
        alpha_extra=(
            "metadata:\n"
            "  status: superseded-in-part\n"
            "  superseded_by:\n"
            "    - terms/beta\n"
            "    - other/gamma\n"
        ),
        extra_strands={
            "beta": _strand(
                keyword="Beta Term",
                aliases="",
                summary="summary: Successor.\n",
                body="Successor body.\n",
            )
        },
    )
    (web,) = discover_memory_webs(tmp_path).webs
    roster = render_strand_roster(web)

    assert "1. **Alpha Term** (`alpha`)" in roster
    assert "2. **Beta Term** (`beta`)" in roster
    assert "_[partly superseded by `beta`, `other/gamma`]_ First term." in roster
    assert all(len(line) <= markdown_print_width() for line in roster.splitlines())


def test_roster_inline_appends_bare_suffix(tmp_path: Path) -> None:
    _seed_terms(
        tmp_path,
        roster="inline",
        alpha_extra=("metadata:\n  status: superseded\n  superseded_by: terms/beta\n"),
        extra_strands={
            "beta": _strand(
                keyword="Beta Term",
                aliases="",
                summary="summary: Successor.\n",
            )
        },
    )
    (web,) = discover_memory_webs(tmp_path).webs
    roster = render_strand_roster(web)

    assert "Alpha Term (alpha) [superseded]" in roster
    assert "Beta Term" in roster
    assert "[partly superseded]" not in roster


def test_roster_inline_partial_suffix(tmp_path: Path) -> None:
    _seed_terms(
        tmp_path,
        roster="inline",
        alpha_extra=(
            "metadata:\n  status: superseded-in-part\n  superseded_by: terms/beta\n"
        ),
        extra_strands={
            "beta": _strand(keyword="Beta Term", aliases="", summary="summary: New.\n")
        },
    )
    (web,) = discover_memory_webs(tmp_path).webs

    assert "Alpha Term (alpha) [partly superseded]" in render_strand_roster(web)


def test_roster_list_accepted_and_missing_metadata_match_plain_entry(
    tmp_path: Path,
) -> None:
    expected = "1. **Alpha Term** (`alpha`) - First term."
    _seed_terms(tmp_path)
    (plain_web,) = discover_memory_webs(tmp_path).webs
    assert render_strand_roster(plain_web) == expected

    accepted_root = tmp_path / "accepted"
    _seed_terms(
        accepted_root,
        alpha_extra="metadata:\n  status: accepted\n  decided: 2026-08-24\n",
    )
    (accepted_web,) = discover_memory_webs(accepted_root).webs
    assert render_strand_roster(accepted_web) == expected
    assert render_strand_roster(plain_web) == render_strand_roster(accepted_web)


def _report_for(
    tmp_path: Path,
    *,
    alpha_extra: str,
    alpha_body: str = "Strand body.\n",
    extra_strands: dict[str, str] | None = None,
    descriptor_extra: str = "",
):
    _seed_terms(
        tmp_path,
        roster="inline",
        alpha_extra=alpha_extra,
        alpha_body=alpha_body,
        extra_strands=extra_strands,
        descriptor_extra=descriptor_extra,
    )
    return validate_memory_webs(discover_memory_webs(tmp_path))


def test_validation_rule_1_unresolved_successor_is_a_warning(tmp_path: Path) -> None:
    report = _report_for(
        tmp_path,
        alpha_extra=(
            "metadata:\n  status: superseded\n  superseded_by: missing-target\n"
        ),
    )

    assert report.blockers == ()
    assert len(report.warnings) == 1
    assert "alpha.md" in report.warnings[0]
    assert (
        "superseded_by target 'missing-target' does not resolve" in report.warnings[0]
    )


def test_validation_rule_2_missing_or_empty_superseded_by(tmp_path: Path) -> None:
    missing = _report_for(tmp_path, alpha_extra="metadata:\n  status: superseded\n")
    empty = _report_for(
        tmp_path / "empty",
        alpha_extra="metadata:\n  status: superseded-in-part\n  superseded_by: []\n",
    )

    assert missing.blockers == ()
    assert empty.blockers == ()
    assert any(
        "metadata.status 'superseded' requires a non-empty superseded_by" in warning
        for warning in missing.warnings
    )
    assert any(
        "metadata.status 'superseded-in-part' requires a non-empty superseded_by"
        in warning
        for warning in empty.warnings
    )


def test_validation_rule_3_superseded_by_without_supersession_status(
    tmp_path: Path,
) -> None:
    report = _report_for(
        tmp_path,
        alpha_extra=("metadata:\n  status: accepted\n  superseded_by: terms/beta\n"),
        extra_strands={
            "beta": _strand(keyword="Beta Term", aliases="", summary="summary: New.\n")
        },
    )

    assert report.blockers == ()
    assert any(
        "superseded_by is set but metadata.status is not superseded or "
        "superseded-in-part" in warning
        for warning in report.warnings
    )


def test_validation_rule_4_malformed_superseded_by(tmp_path: Path) -> None:
    report = _report_for(
        tmp_path,
        alpha_extra="metadata:\n  status: superseded\n  superseded_by: [1]\n",
    )

    assert report.blockers == ()
    assert any(
        "superseded_by must be a string or a list of non-empty strings" in warning
        for warning in report.warnings
    )
    assert not any(
        "requires a non-empty superseded_by" in warning for warning in report.warnings
    )


def test_validation_rule_5_requires_a_body_link_to_each_successor(
    tmp_path: Path,
) -> None:
    extra = {
        "beta": _strand(keyword="Beta Term", aliases="", summary="summary: New.\n"),
        "gamma": _strand(keyword="Gamma Term", aliases="", summary="summary: Other.\n"),
    }
    report = _report_for(
        tmp_path,
        alpha_extra=(
            "metadata:\n"
            "  status: superseded-in-part\n"
            "  superseded_by:\n"
            "    - terms/beta\n"
            "    - terms/gamma\n"
        ),
        alpha_body="See [[terms/beta]].\n",
        extra_strands=extra,
    )

    assert report.blockers == ()
    assert len(report.warnings) == 1
    assert (
        "no [[...]] link resolving to superseded_by target 'terms/gamma'"
        in (report.warnings[0])
    )


def test_validation_rule_5_accepts_keyword_or_alias_body_links(
    tmp_path: Path,
) -> None:
    report = _report_for(
        tmp_path,
        alpha_extra=("metadata:\n  status: superseded\n  superseded_by: terms/beta\n"),
        alpha_body="Retired by [[Beta Term]].\n",
        extra_strands={
            "beta": _strand(
                keyword="Beta Term",
                aliases="aliases: [beta successor]\n",
                summary="summary: New.\n",
            )
        },
    )

    assert report.blockers == ()
    assert report.warnings == ()


def test_validation_rule_5_skips_when_link_reference_is_none(tmp_path: Path) -> None:
    report = _report_for(
        tmp_path,
        descriptor_extra="link_reference: none\n",
        alpha_extra=("metadata:\n  status: superseded\n  superseded_by: terms/beta\n"),
        alpha_body="No authored link.\n",
        extra_strands={
            "beta": _strand(keyword="Beta Term", aliases="", summary="summary: New.\n")
        },
    )

    assert report.blockers == ()
    assert report.warnings == ()


def test_validation_accepts_partial_supersession_with_back_links(
    tmp_path: Path,
) -> None:
    report = _report_for(
        tmp_path,
        alpha_extra=(
            "metadata:\n"
            "  status: superseded-in-part\n"
            "  superseded_by:\n"
            "    - terms/beta\n"
            "    - terms/gamma\n"
        ),
        alpha_body="See [[terms/beta]] and [[terms:gamma]].\n",
        extra_strands={
            "beta": _strand(keyword="Beta Term", aliases="", summary="summary: New.\n"),
            "gamma": _strand(
                keyword="Gamma Term", aliases="", summary="summary: Other.\n"
            ),
        },
    )

    assert report.blockers == ()
    assert report.warnings == ()
