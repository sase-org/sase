"""Tests for the typed plan-header block adapter."""

from sase.sdd.plan_header_block import (
    PlanHeaderDisposition,
    PlanHeaderEntry,
    PlanHeaderSection,
    PlanHeaderSectionKind,
    parse_plan_header_block,
    render_plan_header_block,
    upsert_plan_header_section,
)


def test_parse_preserves_wrapped_logical_content() -> None:
    document = """- **PROMPT:** [202607/prompts/example.md](prompts/example.md)
- **COMMITS:**
  - [699456a](https://github.com/sase-org/sase/commit/699456a521e25e0aaa38f4e289db38e71a6488a6) — fix(parser):
    preserve logical content

# Plan
"""
    parsed = parse_plan_header_block(document)
    assert parsed.disposition is PlanHeaderDisposition.CANONICAL
    assert parsed.sections[1].entries == (
        PlanHeaderEntry(
            label="699456a",
            target=(
                "https://github.com/sase-org/sase/commit/"
                "699456a521e25e0aaa38f4e289db38e71a6488a6"
            ),
            trailing_text="fix(parser): preserve logical content",
        ),
    )


def test_typed_mutations_preserve_other_sections() -> None:
    prompt = PlanHeaderSection(
        kind=PlanHeaderSectionKind.PROMPT,
        label="202607/prompts/example.md",
        target="prompts/example.md",
    )
    agents = PlanHeaderSection(
        kind=PlanHeaderSectionKind.AGENTS,
        entries=(PlanHeaderEntry(label="alice.athena.agent"),),
    )
    document = f"{render_plan_header_block((agents, prompt))}\n\n# Plan\n"

    parent = PlanHeaderSection(
        kind=PlanHeaderSectionKind.PARENT,
        label="202607/epic.md",
        target=("https://github.com/sase-org/sase--plans/blob/main/202607/epic.md"),
    )
    updated = upsert_plan_header_section(
        document,
        parent,
        remove_legacy=False,
    )
    parsed = parse_plan_header_block(updated)
    assert tuple(section.kind for section in parsed.sections) == (
        PlanHeaderSectionKind.PROMPT,
        PlanHeaderSectionKind.PARENT,
        PlanHeaderSectionKind.AGENTS,
    )


def test_empty_list_is_omitted_and_cap_is_visible() -> None:
    empty = PlanHeaderSection(kind=PlanHeaderSectionKind.AGENTS)
    commits = PlanHeaderSection(
        kind=PlanHeaderSectionKind.COMMITS,
        entries=tuple(PlanHeaderEntry(label=f"{index:07}") for index in range(53)),
    )
    rendered = render_plan_header_block((empty, commits))
    assert "AGENTS" not in rendered
    assert "… and 3 more" in rendered
