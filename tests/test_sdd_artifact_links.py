"""Parity tests for the Rust-backed SDD artifact-link adapter."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.sdd.artifact_links import (
    SddArtifactLinkKind,
    SddArtifactLinkType,
    canonical_sdd_artifact_link,
    parse_sdd_artifact_link,
    update_source_aware_artifact_link,
)


def test_render_parse_and_split_canonical_document() -> None:
    root = Path("repo--plans")
    label, href, bullet = canonical_sdd_artifact_link(
        root,
        root / "202607" / "example.md",
        root / "202607" / "prompts" / "example.md",
        SddArtifactLinkType.PROMPT,
    )
    document = f"---\ntier: tale\n---\n\n{bullet}\n\n# Plan\n"

    assert label == "202607/prompts/example.md"
    assert href == "prompts/example.md"
    assert bullet == ("- **PROMPT:** [202607/prompts/example.md](prompts/example.md)")
    parsed = parse_sdd_artifact_link(document)
    assert parsed.kind is SddArtifactLinkKind.CANONICAL
    assert parsed.link_type is SddArtifactLinkType.PROMPT
    assert parsed.label == label
    assert parsed.target == href
    assert parsed.reference == label
    assert parsed.resolution_target == href
    assert parsed.body == "# Plan\n"
    assert parsed.canonical_layout


def test_legacy_mixed_and_malformed_documents_are_distinct() -> None:
    legacy = parse_sdd_artifact_link(
        "---\nprompt: 202607/prompts/example.md\n---\n# Plan\n"
    )
    mixed = parse_sdd_artifact_link(
        "---\nprompt: 202607/prompts/example.md\n---\n\n"
        "- **PROMPT:** [202607/prompts/example.md](prompts/example.md)\n\n"
        "# Plan\n"
    )
    malformed = parse_sdd_artifact_link(
        "- **PROMPT:** [example.md] example.md\n\n# Plan\n"
    )

    assert legacy.kind is SddArtifactLinkKind.LEGACY
    assert legacy.reference == "202607/prompts/example.md"
    assert legacy.resolution_target == "202607/prompts/example.md"
    assert mixed.kind is SddArtifactLinkKind.MIXED
    assert mixed.reference == "202607/prompts/example.md"
    assert malformed.kind is SddArtifactLinkKind.INVALID
    assert malformed.resolution_target is None


def test_source_aware_updater_preserves_content_and_is_idempotent() -> None:
    root = Path("repo--plans")
    plan = root / "202607" / "example.md"
    prompt = root / "202607" / "prompts" / "example.md"
    original = (
        "---\n"
        "tier: tale\n"
        "prompt: '[202607/prompts/example.md](prompts/example.md)'\n"
        "goal: Keep this exact line\n"
        "---\n"
        "# Plan\n\nBody.\n"
    )

    updated = update_source_aware_artifact_link(
        original,
        root,
        plan,
        prompt,
        SddArtifactLinkType.PROMPT,
    )

    assert updated == (
        "---\n"
        "tier: tale\n"
        "goal: Keep this exact line\n"
        "---\n\n"
        "- **PROMPT:** [202607/prompts/example.md](prompts/example.md)\n\n"
        "# Plan\n\nBody.\n"
    )
    assert (
        update_source_aware_artifact_link(
            updated,
            root,
            plan,
            prompt,
            SddArtifactLinkType.PROMPT,
        )
        == updated
    )


def test_canonical_builder_uses_physical_source_and_target_locations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "repo--plans"
    plan = root / "202607" / "example.md"
    prompt = root / "202607" / "prompts" / "example.md"
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)

    _, forward_href, forward = canonical_sdd_artifact_link(
        root, plan, prompt, SddArtifactLinkType.PROMPT
    )
    _, reverse_href, reverse = canonical_sdd_artifact_link(
        root,
        prompt,
        plan,
        SddArtifactLinkType.PLAN,
        label_prefix="../",
    )

    assert forward == ("- **PROMPT:** [202607/prompts/example.md](prompts/example.md)")
    assert reverse == "- **PLAN:** [../202607/example.md](../example.md)"
    assert (plan.parent / forward_href).resolve() == prompt.resolve()
    assert (prompt.parent / reverse_href).resolve() == plan.resolve()
