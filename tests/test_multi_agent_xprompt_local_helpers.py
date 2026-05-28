"""Tests for local helper xprompts in multi-agent expansion."""

from __future__ import annotations

from pathlib import Path

from sase.agent.multi_agent_xprompt import expand_multi_agent_xprompts
from sase.xprompt.loader import load_xprompt_from_file
from sase.xprompt.models import InputArg, InputType, XPrompt
from sase.xprompt.processor import process_xprompt_references_with_catalog

from tests._multi_agent_xprompt_helpers import patch_catalog, xp


def test_expand_local_xprompts_resolve() -> None:
    """Locally-defined xprompts (frontmatter) participate in expansion."""
    local = {
        "_local_three": xp("_local_three", "alpha\n---\nbeta\n---\ngamma"),
    }
    with patch_catalog({}):  # No global xprompts
        out = expand_multi_agent_xprompts(["#!_local_three"], local_xprompts=local)
    assert out == ["alpha", "beta", "gamma"]


def test_expand_local_xprompts_bare_reference() -> None:
    local = {
        "_local_three": xp("_local_three", "alpha\n---\nbeta\n---\ngamma"),
    }
    with patch_catalog({}):
        out = expand_multi_agent_xprompts(["#_local_three"], local_xprompts=local)
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


def test_multi_agent_xprompt_expands_local_helpers_before_splitting() -> None:
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
        out = expand_multi_agent_xprompts(["#reads(episodic memory)"])

    assert out == [
        "%name:a\nFind long articles about episodic memory.",
        "%name:b\nFind long articles about episodic memory.",
    ]


def test_checked_in_reads_xprompt_uses_direct_local_helper() -> None:
    reads_path = Path(__file__).resolve().parents[1] / "xprompts" / "reads.md"
    source = reads_path.read_text(encoding="utf-8")

    assert '#{{ "_" }}article_search_agent' not in source
    assert source.count("#_article_search_agent") == 3

    reads = load_xprompt_from_file(reads_path)
    assert reads is not None
    assert "_article_search_agent" in reads.local_xprompts

    with patch_catalog({"reads": reads}):
        out = expand_multi_agent_xprompts(["#reads(episodic agent memory)"])

    assert len(out) == 4
    assert all("#_article_search_agent" not in segment for segment in out)
    research_segments = out[:3]
    assert all(
        "Can you recommend recent, medium-to-long articles" in segment
        for segment in research_segments
    )
    assert all(
        "Treat every URL and title already present" in segment
        for segment in research_segments
    )
    assert all("episodic agent memory" in segment for segment in out)


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
        out = expand_multi_agent_xprompts(["#outer(episodic memory)"])

    assert out == [
        "first episodic memory",
        "second episodic memory",
        "third episodic memory",
    ]
