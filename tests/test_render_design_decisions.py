"""Tests for the generated design-decisions roster.

Phase sase-1le.8 renders ``docs/reference/design-decisions.md`` from the
decisions memory web: each record's claim, status (including superseded
marks), and a link to the full record on GitHub.
"""

from __future__ import annotations

import importlib.util
from importlib.machinery import SourceFileLoader
from pathlib import Path
import re
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
        "---\nkeyword: Patch\n---\n\nA Patch is the unit of change.\n",
        encoding="utf-8",
    )
    (decisions / "single-turn-agents.md").write_text(
        "---\nkeyword: Agents Are Single-Turn\nsummary:\n  One turn only.\n"
        "metadata:\n  status: accepted\n  decided: 2026-08-15\n---\n\n"
        "**Claim.** One provider turn per agent; see [[glossary:patch]].\n"
        "\n**Why.** Capacity.\n",
        encoding="utf-8",
    )
    (decisions / "old-rule.md").write_text(
        "---\nkeyword: Old Rule\naliases:\n  - legacy rule\nsummary:\n  Retired.\n"
        "metadata:\n  status: superseded\n  superseded_by:\n"
        "    - decisions/single-turn-agents\n---\n\n"
        "**Claim.** The old way.\n",
        encoding="utf-8",
    )
    (decisions / "unmarked.md").write_text(
        "---\nkeyword: Unmarked Rule\nsummary:\n  No metadata block.\n---\n\n"
        "**Claim.** Stands without a status mark.\n",
        encoding="utf-8",
    )


def test_roster_claims_statuses_and_github_links(tmp_path: Path) -> None:
    webs_mod = _load("docs_webs_decisions_test", TOOLS / "docs_webs.py")
    tool = _load("render_design_decisions_fixture", TOOLS / "render_design_decisions")
    _fixture_webs(tmp_path)
    webs = webs_mod.Webs.load(
        glossary_dir=tmp_path / "sase" / "memory" / "glossary",
        decisions_dir=tmp_path / "sase" / "memory" / "decisions",
    )
    text = tool.render_text(webs)
    assert "## Agents Are Single-Turn {#single-turn-agents}" in text
    assert "*Status: accepted · Decided: 2026-08-15.*" in text
    assert "**Claim.** One provider turn per agent;" in text
    assert "[Patch](glossary.md#patch)" in text
    assert "**Why.** Capacity." not in text
    assert "*Status: superseded · Superseded by: " in text
    assert "[Agents Are Single-Turn](#single-turn-agents)" in text
    assert "*Also known as: legacy rule.*" in text
    assert "blob/master/sase/memory/decisions/old-rule.md" in text
    assert "blob/master/sase/memory/decisions/unmarked.md" in text


def test_render_and_check_roundtrip(tmp_path: Path) -> None:
    tool = _load("render_design_decisions_roundtrip", TOOLS / "render_design_decisions")
    _fixture_webs(tmp_path)
    assert tool.check(root=tmp_path) != []
    assert tool.render(root=tmp_path) is None
    assert tool.check(root=tmp_path) == []
    assert (tmp_path / "docs" / "reference" / "design-decisions.md").is_file()


def test_real_decisions_web_renders_every_record() -> None:
    webs_mod = _load("docs_webs_decisions_real_test", TOOLS / "docs_webs.py")
    webs = webs_mod.Webs.load()
    assert len(webs.decisions) >= 25
    committed = (ROOT / "docs" / "reference" / "design-decisions.md").read_text(
        encoding="utf-8"
    )
    anchors = set(re.findall(r"\{#([a-z0-9-]+)\}", committed))
    for slug, strand in webs.decisions.items():
        assert slug in anchors, slug
        assert strand.keyword in committed
        assert f"blob/master/sase/memory/decisions/{slug}.md" in committed
        for ref in strand.superseded_by:
            target = ref.strip().split("/")[-1].strip("[]")
            assert target in anchors, f"{slug} -> {ref}"
