from __future__ import annotations

from pathlib import Path

from sase.artifact_links.derive import DerivableDocument, derive_agent_cites_plan
from sase.sdd.plan_header_block import (
    PlanHeaderEntry,
    PlanHeaderSection,
    PlanHeaderSectionKind,
    render_plan_header_block,
)


def _plan_with_prompt(tmp_path: Path, prompt_label: str) -> Path:
    prompt_section = PlanHeaderSection(
        kind=PlanHeaderSectionKind.PROMPT,
        label=prompt_label,
        target="https://example.test/prompt",
    )
    document = f"{render_plan_header_block((prompt_section,))}\n\n# Plan\n"
    path = tmp_path / "plans" / "202608" / "example.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(document, encoding="utf-8")
    return path


def _archive_prompt(
    agents_root: Path, month: str, name: str, agents: tuple[str, ...]
) -> None:
    agents_section = PlanHeaderSection(
        kind=PlanHeaderSectionKind.AGENTS,
        entries=tuple(PlanHeaderEntry(label=label) for label in agents),
    )
    document = f"{render_plan_header_block((agents_section,))}\n\n# Prompt\n"
    prompt_path = agents_root / "prompts" / month / f"{name}.md"
    prompt_path.parent.mkdir(parents=True, exist_ok=True)
    prompt_path.write_text(document, encoding="utf-8")


def test_emits_a_row_per_published_agent_and_skips_the_unpublished_one(
    tmp_path: Path,
) -> None:
    agents_root = tmp_path / "agents"
    plan_path = _plan_with_prompt(tmp_path, "prompts/202608/example.md")
    _archive_prompt(
        agents_root,
        "202608",
        "example",
        ("alice.athena.worker", "bob.athena.worker", "carol.athena.worker"),
    )
    document = DerivableDocument(ref="plan:202608/example.md", path=plan_path)
    published = {"alice.athena.worker", "bob.athena.worker"}

    candidates = derive_agent_cites_plan(
        document,
        agents_sidecar_root=agents_root,
        is_agent_published=lambda name: name in published,
    )

    assert {candidate.source_ref for candidate in candidates} == {
        "agent:alice.athena.worker",
        "agent:bob.athena.worker",
    }
    for candidate in candidates:
        assert candidate.relation == "cites"
        assert candidate.target_ref == "plan:202608/example.md"
        assert candidate.origin == "derived"


def test_skips_when_no_agent_resolves_as_published(tmp_path: Path) -> None:
    agents_root = tmp_path / "agents"
    plan_path = _plan_with_prompt(tmp_path, "prompts/202608/example.md")
    _archive_prompt(agents_root, "202608", "example", ("alice.athena.worker",))
    document = DerivableDocument(ref="plan:202608/example.md", path=plan_path)

    candidates = derive_agent_cites_plan(
        document,
        agents_sidecar_root=agents_root,
        is_agent_published=lambda _name: False,
    )

    assert candidates == ()


def test_skips_when_there_is_no_agents_sidecar_clone(tmp_path: Path) -> None:
    plan_path = _plan_with_prompt(tmp_path, "prompts/202608/example.md")
    document = DerivableDocument(ref="plan:202608/example.md", path=plan_path)

    candidates = derive_agent_cites_plan(
        document,
        agents_sidecar_root=None,
        is_agent_published=lambda _name: True,
    )

    assert candidates == ()


def test_skips_a_plan_with_no_prompt_section(tmp_path: Path) -> None:
    agents_root = tmp_path / "agents"
    path = tmp_path / "plans" / "202608" / "example.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("# Plan\n", encoding="utf-8")
    document = DerivableDocument(ref="plan:202608/example.md", path=path)

    candidates = derive_agent_cites_plan(
        document,
        agents_sidecar_root=agents_root,
        is_agent_published=lambda _name: True,
    )

    assert candidates == ()


def test_skips_when_the_archived_prompt_is_missing(tmp_path: Path) -> None:
    agents_root = tmp_path / "agents"
    plan_path = _plan_with_prompt(tmp_path, "prompts/202608/example.md")
    document = DerivableDocument(ref="plan:202608/example.md", path=plan_path)

    candidates = derive_agent_cites_plan(
        document,
        agents_sidecar_root=agents_root,
        is_agent_published=lambda _name: True,
    )

    assert candidates == ()


def test_skips_a_non_plan_ref(tmp_path: Path) -> None:
    agents_root = tmp_path / "agents"
    plan_path = _plan_with_prompt(tmp_path, "prompts/202608/example.md")
    _archive_prompt(agents_root, "202608", "example", ("alice.athena.worker",))
    document = DerivableDocument(ref="research:202608/example.md", path=plan_path)

    candidates = derive_agent_cites_plan(
        document,
        agents_sidecar_root=agents_root,
        is_agent_published=lambda _name: True,
    )

    assert candidates == ()
