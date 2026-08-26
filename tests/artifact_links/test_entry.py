from __future__ import annotations

from pathlib import Path

from sase.artifact_links.derive import DerivableDocument, derive_candidate_links


def test_aggregates_candidates_from_every_rule(tmp_path: Path) -> None:
    research_month = tmp_path / "research" / "202608" / "widget"
    research_month.mkdir(parents=True)
    lead = research_month / "widget.md"
    lead.write_text("# lead\n", encoding="utf-8")
    (research_month / "widget__a.md").write_text("# a\n", encoding="utf-8")

    plans_month = tmp_path / "plans" / "202608"
    plans_month.mkdir(parents=True)
    plan_path = plans_month / "example.md"
    plan_path.write_text(
        "---\ntier: tale\nbead_id: sase-xx\n---\n\nbody\n", encoding="utf-8"
    )

    documents = (
        DerivableDocument(ref="research:202608/widget/widget.md", path=lead),
        DerivableDocument(ref="plan:202608/example.md", path=plan_path),
    )

    candidates = derive_candidate_links(documents, known_bead_ids={"sase-xx"})

    relations = {(c.relation, c.target_ref) for c in candidates}
    assert relations == {
        ("derives-from", "research:202608/widget/widget__a.md"),
        ("implements", "bead:sase-xx"),
    }


def test_a_document_no_rule_recognizes_contributes_nothing(tmp_path: Path) -> None:
    path = tmp_path / "agent.md"
    path.write_text("hello\n", encoding="utf-8")
    document = DerivableDocument(ref="agent:some-agent", path=path)

    assert derive_candidate_links([document], known_bead_ids=set()) == ()


def test_empty_input_yields_no_candidates() -> None:
    assert derive_candidate_links([], known_bead_ids=set()) == ()
