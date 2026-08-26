from __future__ import annotations

from pathlib import Path

from sase.artifact_links.derive import DerivableDocument, derive_plan_implements_bead


def _plan(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "202608" / "example.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


def test_implements_a_bead_named_in_frontmatter(tmp_path: Path) -> None:
    path = _plan(
        tmp_path,
        "---\ntier: tale\nbead_id: sase-xx\n---\n\nbody\n",
    )
    document = DerivableDocument(ref="plan:202608/example.md", path=path)

    candidates = derive_plan_implements_bead(document, known_bead_ids={"sase-xx"})

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.source_ref == "plan:202608/example.md"
    assert candidate.relation == "implements"
    assert candidate.target_ref == "bead:sase-xx"
    assert candidate.origin == "derived"


def test_skips_a_plan_with_no_bead_field(tmp_path: Path) -> None:
    path = _plan(tmp_path, "---\ntier: tale\n---\n\nbody\n")
    document = DerivableDocument(ref="plan:202608/example.md", path=path)

    assert derive_plan_implements_bead(document, known_bead_ids={"sase-xx"}) == ()


def test_skips_a_bead_id_that_does_not_resolve(tmp_path: Path) -> None:
    path = _plan(tmp_path, "---\ntier: tale\nbead_id: sase-zz\n---\n\nbody\n")
    document = DerivableDocument(ref="plan:202608/example.md", path=path)

    assert derive_plan_implements_bead(document, known_bead_ids={"sase-xx"}) == ()


def test_skips_a_blank_bead_field(tmp_path: Path) -> None:
    path = _plan(tmp_path, '---\ntier: tale\nbead_id: ""\n---\n\nbody\n')
    document = DerivableDocument(ref="plan:202608/example.md", path=path)

    assert derive_plan_implements_bead(document, known_bead_ids={"sase-xx"}) == ()


def test_skips_proposing_agent_bead_without_plan_bead_id(tmp_path: Path) -> None:
    path = _plan(tmp_path, "---\ntier: tale\nbead: sase-xx\n---\n\nbody\n")
    document = DerivableDocument(ref="plan:202608/example.md", path=path)

    assert derive_plan_implements_bead(document, known_bead_ids={"sase-xx"}) == ()


def test_skips_invalid_frontmatter(tmp_path: Path) -> None:
    path = _plan(tmp_path, "---\ntier: [unterminated\nbody\n")
    document = DerivableDocument(ref="plan:202608/example.md", path=path)

    assert derive_plan_implements_bead(document, known_bead_ids={"sase-xx"}) == ()


def test_skips_a_non_plan_ref(tmp_path: Path) -> None:
    path = _plan(tmp_path, "---\ntier: tale\nbead_id: sase-xx\n---\n\nbody\n")
    document = DerivableDocument(ref="research:202608/example.md", path=path)

    assert derive_plan_implements_bead(document, known_bead_ids={"sase-xx"}) == ()
