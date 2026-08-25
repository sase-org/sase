from __future__ import annotations

from pathlib import Path

from sase.artifact_links.derive import DerivableDocument, derive_research_swarm_lineage


def test_derives_from_both_siblings_when_present(tmp_path: Path) -> None:
    month_dir = tmp_path / "202608" / "widget"
    month_dir.mkdir(parents=True)
    lead = month_dir / "widget.md"
    lead.write_text("# lead\n", encoding="utf-8")
    (month_dir / "widget__a.md").write_text("# a\n", encoding="utf-8")
    (month_dir / "widget__b.md").write_text("# b\n", encoding="utf-8")

    document = DerivableDocument(ref="research:202608/widget/widget.md", path=lead)
    candidates = derive_research_swarm_lineage(document)

    assert {candidate.target_ref for candidate in candidates} == {
        "research:202608/widget/widget__a.md",
        "research:202608/widget/widget__b.md",
    }
    for candidate in candidates:
        assert candidate.source_ref == "research:202608/widget/widget.md"
        assert candidate.relation == "derives-from"
        assert candidate.origin == "derived"


def test_derives_from_only_the_sibling_that_exists(tmp_path: Path) -> None:
    month_dir = tmp_path / "202608" / "widget"
    month_dir.mkdir(parents=True)
    lead = month_dir / "widget.md"
    lead.write_text("# lead\n", encoding="utf-8")
    (month_dir / "widget__a.md").write_text("# a\n", encoding="utf-8")

    document = DerivableDocument(ref="research:202608/widget/widget.md", path=lead)
    candidates = derive_research_swarm_lineage(document)

    assert len(candidates) == 1
    assert candidates[0].target_ref == "research:202608/widget/widget__a.md"


def test_skips_lead_with_no_siblings_on_disk(tmp_path: Path) -> None:
    month_dir = tmp_path / "202608" / "widget"
    month_dir.mkdir(parents=True)
    lead = month_dir / "widget.md"
    lead.write_text("# lead\n", encoding="utf-8")

    document = DerivableDocument(ref="research:202608/widget/widget.md", path=lead)
    assert derive_research_swarm_lineage(document) == ()


def test_skips_a_swarm_source_document_even_with_a_sibling_present(
    tmp_path: Path,
) -> None:
    month_dir = tmp_path / "202608" / "widget"
    month_dir.mkdir(parents=True)
    source = month_dir / "widget__a.md"
    source.write_text("# a\n", encoding="utf-8")
    (month_dir / "widget__b.md").write_text("# b\n", encoding="utf-8")

    document = DerivableDocument(ref="research:202608/widget/widget__a.md", path=source)
    assert derive_research_swarm_lineage(document) == ()


def test_skips_a_non_research_ref(tmp_path: Path) -> None:
    month_dir = tmp_path / "202608" / "widget"
    month_dir.mkdir(parents=True)
    lead = month_dir / "widget.md"
    lead.write_text("# lead\n", encoding="utf-8")
    (month_dir / "widget__a.md").write_text("# a\n", encoding="utf-8")

    document = DerivableDocument(ref="plan:202608/widget/widget.md", path=lead)
    assert derive_research_swarm_lineage(document) == ()
