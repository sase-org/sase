"""Tests for local helper xprompts in multi-agent expansion."""

from __future__ import annotations

from pathlib import Path

from sase.agent.xprompt_swarm import expand_xprompt_swarms_with_metadata
from sase.xprompt.loader import load_xprompt_from_file
from sase.xprompt.models import InputArg, InputType, XPrompt
from sase.xprompt.processor import process_xprompt_references_with_catalog

from tests._xprompt_swarm_helpers import patch_catalog, xp


def expand_xprompt_swarms(segments: list[str], **kwargs) -> list[str]:
    return [
        segment.prompt
        for segment in expand_xprompt_swarms_with_metadata(segments, **kwargs)
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


def test_expand_local_xprompts_resolve() -> None:
    """Locally-defined xprompts (frontmatter) participate in expansion."""
    local = {
        "_local_three": xp("_local_three", "alpha\n---\nbeta\n---\ngamma"),
    }
    with patch_catalog({}):  # No global xprompts
        out = expand_xprompt_swarms(["#!_local_three"], local_xprompts=local)
    assert out == ["alpha", "beta", "gamma"]


def test_expand_local_xprompts_bare_reference() -> None:
    local = {
        "_local_three": xp("_local_three", "alpha\n---\nbeta\n---\ngamma"),
    }
    with patch_catalog({}):
        out = expand_xprompt_swarms(["#_local_three"], local_xprompts=local)
    assert out == ["alpha", "beta", "gamma"]


def test_markdown_xprompt_local_helper_expands_without_global_leak() -> None:
    outer = XPrompt(
        name="outer",
        content="Do #_helper for {{ topic }}.",
        inputs=[InputArg(name="topic", type=InputType.TEXT)],
        local_xprompts={
            "_helper": XPrompt(name="_helper", content="focused work on {{ topic }}")
        },
    )
    catalog = {"outer": outer}

    out = process_xprompt_references_with_catalog(
        "#outer(episodic memory)",
        catalog,
        aliases_resolved=True,
    )

    assert out == "Do focused work on episodic memory for episodic memory."
    assert "_helper" not in catalog


def test_xprompt_swarm_expands_local_helpers_before_splitting() -> None:
    catalog = {
        "reads": XPrompt(
            name="reads",
            content="%name:a\n#_article\n---\n%name:b\n#_article",
            inputs=[InputArg(name="topic", type=InputType.TEXT)],
            local_xprompts={
                "_article": XPrompt(
                    name="_article",
                    content="Find long articles about {{ topic }}.",
                )
            },
        )
    }
    with patch_catalog(catalog):
        out = expand_xprompt_swarms(["#reads(episodic memory)"])

    assert out == [
        "%name:a\nFind long articles about episodic memory.",
        "%name:b\nFind long articles about episodic memory.",
    ]


def test_checked_in_reads_xprompt_uses_direct_local_helper() -> None:
    reads_path = Path(__file__).resolve().parents[1] / "sase" / "xprompts" / "reads.md"
    source = reads_path.read_text(encoding="utf-8")

    assert '#{{ "_" }}article_search_agent' not in source
    assert source.count("#_article_search_agent") == 3
    assert "%model:agy/flash35h" not in source
    assert '%model("agy/Gemini 3.5 Flash (High)")' in source

    reads = load_xprompt_from_file(reads_path)
    assert reads is not None
    assert "_article_search_agent" in reads.local_xprompts
    assert reads.get_input_by_name("notes") is None
    reference_query = reads.get_input_by_name("reference_query")
    assert reference_query is not None
    assert reference_query.default.rstrip() == DEFAULT_READS_REFERENCE_QUERY

    with patch_catalog({"reads": reads}):
        out = expand_xprompt_swarms(["#reads(episodic agent memory)"])

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
        "outer": XPrompt(
            name="outer",
            content="#_fanout\n---\nthird {{ topic }}",
            inputs=[InputArg(name="topic", type=InputType.TEXT)],
            local_xprompts={
                "_fanout": XPrompt(
                    name="_fanout",
                    content="first {{ topic }}\n---\nsecond {{ topic }}",
                )
            },
        )
    }
    with patch_catalog(catalog):
        out = expand_xprompt_swarms(["#outer(episodic memory)"])

    assert out == [
        "first episodic memory",
        "second episodic memory",
        "third episodic memory",
    ]
