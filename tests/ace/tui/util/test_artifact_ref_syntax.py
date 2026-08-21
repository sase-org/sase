"""Tests for shared ACE artifact-reference syntax spans."""

from __future__ import annotations

from types import SimpleNamespace

from rich.text import Text

from sase.ace.tui.util import artifact_ref_syntax as ref_syntax
from sase.ace.tui.util.artifact_ref_syntax import (
    apply_artifact_ref_overlays,
    artifact_ref_style_palette_from_theme,
    artifact_ref_styled_spans,
    build_artifact_ref_candidate_spans,
)

_KNOWN_KINDS = frozenset({"plans", "commit", "agent", "bead"})


def _part_rows(text: str) -> list[tuple[str, int, int, str]]:
    candidates = build_artifact_ref_candidate_spans(
        text,
        known_kinds=_KNOWN_KINDS,
        max_bytes=10_000,
        max_lines=50,
    )
    return [
        (candidate.kind, part.span.start, part.span.end, part.role)
        for candidate in candidates
        for part in candidate.parts
    ]


def _style_keys(
    text: str, known_kinds: frozenset[str] | None = _KNOWN_KINDS
) -> list[str]:
    candidates = build_artifact_ref_candidate_spans(
        text,
        known_kinds=known_kinds,
        max_bytes=10_000,
        max_lines=50,
    )
    return [span.style_key for span in artifact_ref_styled_spans(candidates)]


def test_builds_multi_ref_component_spans_and_fragments() -> None:
    text = "Compare @plans:one.md and @commit:sase@abcdef1 before @plans:two.md#L2"

    candidates = build_artifact_ref_candidate_spans(
        text,
        known_kinds=_KNOWN_KINDS,
        max_bytes=10_000,
        max_lines=50,
    )

    assert [candidate.kind for candidate in candidates] == [
        "plans",
        "commit",
        "plans",
    ]
    assert candidates[2].parts[-1].role == "fragment"
    assert (
        text[candidates[2].parts[-1].span.start : candidates[2].parts[-1].span.end]
        == "#L2"
    )


def test_quoted_payload_delimiters_are_punctuation_parts() -> None:
    text = '@plans:"a b.md"#L3'

    assert _part_rows(text) == [
        ("plans", 0, 1, "sigil"),
        ("plans", 1, 6, "kind"),
        ("plans", 6, 7, "separator"),
        ("plans", 7, 8, "delimiter"),
        ("plans", 8, 14, "payload"),
        ("plans", 14, 15, "delimiter"),
        ("plans", 15, 18, "fragment"),
    ]


def test_converts_utf8_byte_offsets_to_rich_character_offsets() -> None:
    text = "é @plans:café.md"

    assert ("plans", 2, 3, "sigil") in _part_rows(text)
    assert ("plans", 9, 16, "payload") in _part_rows(text)


def test_skips_inline_and_fenced_literal_zones() -> None:
    text = "`@plans:inline.md`\n```\n@plans:fenced.md\n```\n@plans:live.md"

    candidates = build_artifact_ref_candidate_spans(
        text,
        known_kinds=_KNOWN_KINDS,
        max_bytes=10_000,
        max_lines=50,
    )

    assert [candidate.candidate.text for candidate in candidates] == ["@plans:live.md"]


def test_presentation_states_cover_cold_unknown_and_malformed_refs() -> None:
    assert _style_keys("@plans:") == ["error"]
    assert _style_keys("@user:handle") == ["unknown"]
    assert _style_keys("@plans:one.md", known_kinds=None) == ["neutral"]


def test_exact_size_boundary_is_inclusive() -> None:
    reference = "@plans:boundary.md"
    text = "x" * 5 + " " + reference

    assert build_artifact_ref_candidate_spans(
        text,
        known_kinds=_KNOWN_KINDS,
        max_bytes=len(text.encode("utf-8")),
        max_lines=1,
    )
    assert not build_artifact_ref_candidate_spans(
        text + "x",
        known_kinds=_KNOWN_KINDS,
        max_bytes=len(text.encode("utf-8")),
        max_lines=1,
    )


def test_palette_adapts_to_theme_and_styles_rich_text() -> None:
    dark = SimpleNamespace(
        secondary="#335577",
        success="#00aa66",
        accent="#9955cc",
        error="#cc3344",
        foreground="#ffffff",
        background="#000000",
    )
    light = SimpleNamespace(
        secondary="#335577",
        success="#00aa66",
        accent="#9955cc",
        error="#cc3344",
        foreground="#000000",
        background="#ffffff",
    )

    dark_palette = artifact_ref_style_palette_from_theme(dark)
    light_palette = artifact_ref_style_palette_from_theme(light)
    highlighted = Text("@plans:one.md")
    apply_artifact_ref_overlays(
        highlighted,
        highlighted.plain,
        known_kinds=_KNOWN_KINDS,
        palette=dark_palette,
        max_bytes=10_000,
        max_lines=50,
    )

    assert dark_palette.signature != light_palette.signature
    assert dark_palette.style_for_key("kind").bold is True
    assert dark_palette.style_for_key("fragment").italic is True
    assert highlighted.spans


def test_scanner_errors_fail_open(monkeypatch) -> None:
    def _raise(_text: str):
        raise RuntimeError("boom")

    monkeypatch.setattr(ref_syntax, "scan_artifact_refs", _raise)

    assert (
        build_artifact_ref_candidate_spans(
            "@plans:one.md",
            known_kinds=_KNOWN_KINDS,
            max_bytes=10_000,
            max_lines=50,
        )
        == ()
    )
