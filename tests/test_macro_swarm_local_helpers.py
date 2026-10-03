"""Tests for local helper macros in multi-agent expansion."""

from __future__ import annotations

from pathlib import Path

from sase.agent.macro_swarm import expand_macro_swarms_with_metadata
from sase.macro.loader import load_macro_from_file
from sase.macro.models import InputArg, InputType, Macro
from sase.macro.processor import process_macro_references_with_catalog

from tests._macro_swarm_helpers import patch_catalog, xp


def expand_macro_swarms(segments: list[str], **kwargs) -> list[str]:
    return [
        segment.prompt
        for segment in expand_macro_swarms_with_metadata(segments, **kwargs)
    ]


DEFAULT_READS_REFERENCE_QUERY = """LIST WITHOUT ID title + " (" + url + ")"
FROM "ref"
WHERE
  source_path AND url AND (
    parent = [[ai_ref]]
    OR parent.parent = [[ai_ref]]
    OR parent.parent.parent = [[ai_ref]]
    OR parent.parent.parent.parent = [[ai_ref]]
    OR parent.parent.parent.parent.parent = [[ai_ref]]
  )
SORT title"""

OLD_READS_NOTE_DEFAULT = """- ~/bob/agent_ref.md
- ~/bob/ai_ref.md
- ~/bob/claude_code_ref.md
- ~/bob/gemini_cli_ref.md
- ~/bob/xprompt_ref.md"""


def test_expand_local_macros_resolve() -> None:
    """Locally-defined macros (frontmatter) participate in expansion."""
    local = {
        "_local_three": xp("_local_three", "alpha\n---\nbeta\n---\ngamma"),
    }
    with patch_catalog({}):  # No global macros
        out = expand_macro_swarms(["#!_local_three"], local_macros=local)
    assert out == ["alpha", "beta", "gamma"]


def test_expand_local_macros_bare_reference() -> None:
    local = {
        "_local_three": xp("_local_three", "alpha\n---\nbeta\n---\ngamma"),
    }
    with patch_catalog({}):
        out = expand_macro_swarms(["#_local_three"], local_macros=local)
    assert out == ["alpha", "beta", "gamma"]


def test_markdown_macro_local_helper_expands_without_global_leak() -> None:
    outer = Macro(
        name="outer",
        content="Do #_helper for {{ topic }}.",
        inputs=[InputArg(name="topic", type=InputType.TEXT)],
        local_macros={
            "_helper": Macro(name="_helper", content="focused work on {{ topic }}")
        },
    )
    catalog = {"outer": outer}

    out = process_macro_references_with_catalog(
        "#outer(episodic memory)",
        catalog,
        aliases_resolved=True,
    )

    assert out == "Do focused work on episodic memory for episodic memory."
    assert "_helper" not in catalog


def test_macro_swarm_expands_local_helpers_before_splitting() -> None:
    catalog = {
        "reads": Macro(
            name="reads",
            content="%id:a\n#_article\n---\n%id:b\n#_article",
            inputs=[InputArg(name="topic", type=InputType.TEXT)],
            local_macros={
                "_article": Macro(
                    name="_article",
                    content="Find long articles about {{ topic }}.",
                )
            },
        )
    }
    with patch_catalog(catalog):
        out = expand_macro_swarms(["#reads(episodic memory)"])

    assert out == [
        "%id:a\nFind long articles about episodic memory.",
        "%id:b\nFind long articles about episodic memory.",
    ]


def test_checked_in_reads_macro_uses_direct_local_helper() -> None:
    reads_path = Path(__file__).resolve().parents[1] / "sase" / "xprompts" / "reads.md"
    source = reads_path.read_text(encoding="utf-8")

    assert '#{{ "_" }}article_search_agent' not in source
    assert source.count("#_article_search_agent") == 3
    assert "%model:agy/flash35h" not in source
    assert "%model:agy/gemini-3.7-flash-high" in source
    assert "%model:codex/gpt-6.1-sol" in source
    assert "%model:codex/gpt-5.6-sol" not in source

    reads = load_macro_from_file(reads_path)
    assert reads is not None
    assert "_article_search_agent" in reads.local_macros
    assert reads.get_input_by_name("notes") is None
    reference_query = reads.get_input_by_name("reference_query")
    assert reference_query is not None
    assert reference_query.default.rstrip() == DEFAULT_READS_REFERENCE_QUERY

    with patch_catalog({"reads": reads}):
        out = expand_macro_swarms(["#reads(episodic agent memory)"])

    assert len(out) == 4
    assert all("#_article_search_agent" not in segment for segment in out)
    research_segments = out[:3]
    assert all(
        "Can you recommend recent, medium-to-long articles" in segment
        for segment in research_segments
    )
    assert not any(
        "Treat every URL and title already present" in segment
        for segment in research_segments
    )
    assert all("/bob_query" in segment for segment in research_segments)
    assert all(
        DEFAULT_READS_REFERENCE_QUERY in segment for segment in research_segments
    )
    assert all(OLD_READS_NOTE_DEFAULT not in segment for segment in out)
    assert all("episodic agent memory" in segment for segment in out)
    final_segment = out[3]
    assert "reference Dataview query" in final_segment
    assert "reference notes" not in final_segment
    assert "reference table" in final_segment


def test_multi_agent_local_helper_separators_split_with_owner() -> None:
    catalog = {
        "outer": Macro(
            name="outer",
            content="#_fanout\n---\nthird {{ topic }}",
            inputs=[InputArg(name="topic", type=InputType.TEXT)],
            local_macros={
                "_fanout": Macro(
                    name="_fanout",
                    content="first {{ topic }}\n---\nsecond {{ topic }}",
                )
            },
        )
    }
    with patch_catalog(catalog):
        out = expand_macro_swarms(["#outer(episodic memory)"])

    assert out == [
        "first episodic memory",
        "second episodic memory",
        "third episodic memory",
    ]
