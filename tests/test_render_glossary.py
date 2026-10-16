"""Tests for the generated glossary page and tooltip abbreviations.

Phase sase-1le.8 renders ``docs/reference/glossary.md`` (every term, its
aliases, and its definition, anchored by term slug) and
``docs/_includes/abbreviations.md`` (about 15 core-term tooltips) from the
glossary memory web. Agent-internal cross-reference syntax becomes plain
links, except inside fenced or inline code.
"""

from __future__ import annotations

import importlib.util
from importlib.machinery import SourceFileLoader
from pathlib import Path
import sys
from types import ModuleType


ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))


def _load(name: str, path: Path) -> ModuleType:
    loader = SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    loader.exec_module(module)
    return module


def _fixture_webs(root: Path) -> None:
    glossary = root / "sase" / "memory" / "glossary"
    decisions = root / "sase" / "memory" / "decisions"
    glossary.mkdir(parents=True)
    decisions.mkdir(parents=True)
    (glossary / "patch.md").write_text(
        "---\nkeyword: Patch\n---\n\nA Patch is the unit of change. "
        "See [[glossary:stitch]] and [[decisions/single-turn-agents]].\n"
        "\nUse `[[glossary:stitch]]` literally in code.\n",
        encoding="utf-8",
    )
    (glossary / "stitch.md").write_text(
        "---\nkeyword: Stitch\naliases:\n  - stitches\n---\n\n"
        "A stitch lives inside a Patch.\n",
        encoding="utf-8",
    )
    tool = _load("render_glossary_fixture_terms", TOOLS / "render_glossary")
    for term, slug, _explicit in tool.ABBR_TERMS:
        if slug is None or (glossary / f"{slug}.md").exists():
            continue
        (glossary / f"{slug}.md").write_text(
            f"---\nkeyword: {term.title()}\n---\n\nA {term} is a test term.\n",
            encoding="utf-8",
        )
    (decisions / "single-turn-agents.md").write_text(
        "---\nkeyword: Agents Are Single-Turn\nsummary:\n  One turn only.\n"
        "metadata:\n  status: accepted\n  decided: 2026-08-15\n---\n\n"
        "**Claim.** One provider turn per agent.\n",
        encoding="utf-8",
    )


def test_glossary_page_anchors_aliases_and_links(tmp_path: Path) -> None:
    webs_mod = _load("docs_webs_glossary_test", TOOLS / "docs_webs.py")
    tool = _load("render_glossary_fixture", TOOLS / "render_glossary")
    _fixture_webs(tmp_path)
    webs = webs_mod.Webs.load(
        glossary_dir=tmp_path / "sase" / "memory" / "glossary",
        decisions_dir=tmp_path / "sase" / "memory" / "decisions",
    )
    text = tool.render_glossary_text(webs)
    assert "## Patch {#patch}" in text
    assert "## Stitch {#stitch}" in text
    assert text.index("## Patch {#patch}") < text.index("## Stitch {#stitch}")
    assert "*Also known as: stitches.*" in text
    assert "[Stitch](#stitch)" in text
    assert "[Agents Are Single-Turn](design-decisions.md#single-turn-agents)" in text
    # Inline code is never scanned for references.
    assert "`[[glossary:stitch]]`" in text


def test_abbreviations_cover_the_configured_core_terms() -> None:
    tool = _load("render_glossary_abbr_fixture", TOOLS / "render_glossary")
    terms = [term for term, _slug, _text in tool.ABBR_TERMS]
    assert len(terms) >= 13
    assert {
        "Patch",
        "bead",
        "plan",
        "epic",
        "macro",
        "gate",
        "monitor",
        "stitch",
    } <= set(terms)
    for term, slug, explicit in tool.ABBR_TERMS:
        assert explicit or slug, term


def test_glossary_render_and_check_roundtrip(tmp_path: Path) -> None:
    tool = _load("render_glossary_roundtrip", TOOLS / "render_glossary")
    _fixture_webs(tmp_path)
    assert tool.check(root=tmp_path) != []
    assert tool.render(root=tmp_path) is None
    assert tool.check(root=tmp_path) == []
    assert (tmp_path / "docs" / "reference" / "glossary.md").is_file()
    assert (tmp_path / "docs" / "_includes" / "abbreviations.md").is_file()


def test_real_glossary_web_renders_every_term() -> None:
    webs_mod = _load("docs_webs_real_test", TOOLS / "docs_webs.py")
    tool = _load("render_glossary_real", TOOLS / "render_glossary")
    webs = webs_mod.Webs.load()
    assert len(webs.glossary) >= 60
    text = tool.render_glossary_text(webs)
    for slug, strand in webs.glossary.items():
        assert f"{{#{slug}}}" in text, slug
        assert strand.keyword in text
    abbreviations = tool.render_abbreviations_text(webs)
    for term, _slug, _text in tool.ABBR_TERMS:
        assert f"*[{term}]:" in abbreviations, term
    committed = (ROOT / "docs" / "reference" / "glossary.md").read_text(
        encoding="utf-8"
    )
    for slug in webs.glossary:
        assert f"{{#{slug}}}" in committed, slug
