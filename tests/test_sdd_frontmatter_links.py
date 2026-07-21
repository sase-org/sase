"""Parity tests for the Rust-backed SDD frontmatter-link adapter."""

from __future__ import annotations

from pathlib import Path

from sase.sdd.frontmatter_links import (
    SddFrontmatterLinkKind,
    canonical_sdd_frontmatter_link,
    parse_sdd_frontmatter_link,
)


def test_render_and_parse_canonical_link() -> None:
    root = Path("repo--plans")
    rendered = canonical_sdd_frontmatter_link(
        root,
        root / "202607" / "example.md",
        root / "202607" / "prompts" / "example.md",
    )

    assert rendered == "[202607/prompts/example.md](prompts/example.md)"
    parsed = parse_sdd_frontmatter_link(rendered)
    assert parsed.kind is SddFrontmatterLinkKind.CANONICAL
    assert parsed.label == "202607/prompts/example.md"
    assert parsed.target == "prompts/example.md"
    assert parsed.reference == "202607/prompts/example.md"
    assert parsed.resolution_target == "prompts/example.md"


def test_legacy_and_malformed_values_have_distinct_classifications() -> None:
    legacy = parse_sdd_frontmatter_link("202607/prompts/example.md")
    malformed = parse_sdd_frontmatter_link("[example.md] example.md")

    assert legacy.kind is SddFrontmatterLinkKind.LEGACY
    assert legacy.reference == "202607/prompts/example.md"
    assert legacy.resolution_target == "202607/prompts/example.md"
    assert malformed.kind is SddFrontmatterLinkKind.INVALID
    assert malformed.resolution_target is None


def test_canonical_builder_uses_source_and_target_locations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "repo--plans"
    plan = root / "202607" / "example.md"
    prompt = root / "202607" / "prompts" / "example.md"
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)

    forward = canonical_sdd_frontmatter_link(root, plan, prompt)
    reverse = canonical_sdd_frontmatter_link(
        root,
        prompt,
        plan,
        label_prefix="../",
    )

    assert forward == "[202607/prompts/example.md](prompts/example.md)"
    assert reverse == "[../202607/example.md](../example.md)"
    forward_target = parse_sdd_frontmatter_link(forward).resolution_target
    reverse_target = parse_sdd_frontmatter_link(reverse).resolution_target
    assert forward_target is not None
    assert reverse_target is not None
    assert (plan.parent / forward_target).resolve() == prompt.resolve()
    assert (prompt.parent / reverse_target).resolve() == plan.resolve()
