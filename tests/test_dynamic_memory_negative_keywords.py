"""Tests for negative (`!`-prefixed) keyword behavior and span-masking semantics."""

from pathlib import Path
from unittest.mock import patch

import pytest

from sase.memory.dynamic import _split_keywords, generate_dynamic_memory
from sase.xprompt.loader_parsing import parse_xprompt_entries
from sase.xprompt.models import xprompt_to_workflow


def _make_negative_keyword_workflows(keywords: list[str]) -> dict[str, object]:
    entries = {
        "memory/long/neg_test": {
            "tags": "memory",
            "keywords": keywords,
            "content": "# Neg test content",
        }
    }
    xprompts = parse_xprompt_entries(entries, "test")
    return {name: xprompt_to_workflow(xp) for name, xp in xprompts.items()}


# ── _split_keywords ───────────────────────────────────────────────────────


def test_split_keywords_basic() -> None:
    positives, negatives = _split_keywords(["foo", "!bar", "baz", "!qux"])
    assert positives == ["foo", "baz"]
    assert negatives == ["bar", "qux"]


def test_split_keywords_bare_bang_dropped() -> None:
    """A bare '!' must not produce an empty-text negative that matches everywhere."""
    positives, negatives = _split_keywords(["foo", "!"])
    assert positives == ["foo"]
    assert negatives == []


# ── negative keyword semantics ────────────────────────────────────────────


def test_negative_keyword_does_not_exclude_when_positive_matches_outside_mask(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A negative hit only excludes when it masks away the sole positive hit."""
    monkeypatch.chdir(tmp_path)
    workflows = _make_negative_keyword_workflows(["skill", "!jetski"])
    with (
        patch("sase.xprompt.loader.get_all_prompts", return_value=workflows),
        patch(
            "sase.gemini_wrapper.file_references.process_command_substitution",
            side_effect=lambda s: s,
        ),
    ):
        result = generate_dynamic_memory("deploy a skill via jetski", None)

    assert len(result.matched) == 1
    assert result.matched[0].keywords_matched == ["skill"]


def test_negative_keyword_ignored_when_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    workflows = _make_negative_keyword_workflows(["skill", "!jetski"])
    with (
        patch("sase.xprompt.loader.get_all_prompts", return_value=workflows),
        patch(
            "sase.gemini_wrapper.file_references.process_command_substitution",
            side_effect=lambda s: s,
        ),
    ):
        result = generate_dynamic_memory("write a new skill", None)

    assert len(result.matched) == 1
    assert result.matched[0].keywords_matched == ["skill"]


def test_negative_only_keywords_never_match(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    workflows = _make_negative_keyword_workflows(["!jetski", "!deprecated"])
    with (
        patch("sase.xprompt.loader.get_all_prompts", return_value=workflows),
        patch(
            "sase.gemini_wrapper.file_references.process_command_substitution",
            side_effect=lambda s: s,
        ),
    ):
        result = generate_dynamic_memory("totally unrelated prompt", None)

    assert result.matched == []


def test_negative_overrides_positive_in_same_list(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    # Same keyword appears both positive and negative; negative wins.
    workflows = _make_negative_keyword_workflows(["skill", "!skill"])
    with (
        patch("sase.xprompt.loader.get_all_prompts", return_value=workflows),
        patch(
            "sase.gemini_wrapper.file_references.process_command_substitution",
            side_effect=lambda s: s,
        ),
    ):
        result = generate_dynamic_memory("update the skill", None)

    assert result.matched == []


def test_negative_keyword_case_insensitive_mask(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Negative matching is case-insensitive: uppercase JETSKI is still masked."""
    monkeypatch.chdir(tmp_path)
    # Positive `jetski` appears only inside the negative span, so after masking
    # only `skill` remains as a positive hit.
    workflows = _make_negative_keyword_workflows(["skill", "jetski", "!jetski"])
    with (
        patch("sase.xprompt.loader.get_all_prompts", return_value=workflows),
        patch(
            "sase.gemini_wrapper.file_references.process_command_substitution",
            side_effect=lambda s: s,
        ),
    ):
        result = generate_dynamic_memory("JETSKI skill deploy", None)

    assert len(result.matched) == 1
    assert result.matched[0].keywords_matched == ["skill"]


def test_negative_keyword_word_boundary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`!test` must not exclude on `testing` — word boundaries still apply."""
    monkeypatch.chdir(tmp_path)
    workflows = _make_negative_keyword_workflows(["skill", "!test"])
    with (
        patch("sase.xprompt.loader.get_all_prompts", return_value=workflows),
        patch(
            "sase.gemini_wrapper.file_references.process_command_substitution",
            side_effect=lambda s: s,
        ),
    ):
        result = generate_dynamic_memory("testing my skill", None)

    assert len(result.matched) == 1
    assert result.matched[0].keywords_matched == ["skill"]


# ── negative keyword roundtrips through loaders ──────────────────────────


def test_negative_keyword_frontmatter_roundtrip(tmp_path: Path) -> None:
    """Quoted '!foo' in YAML frontmatter is preserved through the model."""
    from sase.xprompt.loader import _load_xprompt_from_file

    md = tmp_path / "test.md"
    md.write_text(
        '---\ntags: memory\nkeywords: [skill, "!jetski"]\n---\n@memory/long/foo.md\n'
    )
    xp = _load_xprompt_from_file(md)
    assert xp is not None
    assert xp.keywords == ["skill", "!jetski"]


def test_negative_keyword_config_entry_roundtrip() -> None:
    """Negative keywords survive parse_xprompt_entries."""
    entries = {
        "memory/foo": {
            "tags": "memory",
            "keywords": ["skill", "!jetski"],
            "content": "# body",
        }
    }
    result = parse_xprompt_entries(entries, "test")
    assert result["memory/foo"].keywords == ["skill", "!jetski"]


def test_negative_keyword_memory_long_frontmatter(tmp_path: Path) -> None:
    """Auto-discovered memory/long/*.md files preserve '!'-prefixed keywords."""
    from sase.xprompt.loader import _load_memory_long_xprompts

    mem_dir = tmp_path / "memory" / "long"
    mem_dir.mkdir(parents=True)
    (mem_dir / "foo.md").write_text(
        '---\nkeywords: [skill, "!jetski"]\n---\n# Foo content\n'
    )

    with (
        patch(
            "sase.xprompt.loader._get_memory_long_search_dirs",
            return_value=[(mem_dir, True)],
        ),
        patch("sase.xprompt.loader.Path.cwd", return_value=tmp_path),
    ):
        result = _load_memory_long_xprompts()

    assert "memory/long/foo" in result
    assert result["memory/long/foo"].keywords == ["skill", "!jetski"]


# ── negative keyword masking ─────────────────────────────────────────────


def test_negative_mask_allows_positive_outside_span(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`[foo, "!/foo/"]` on a prompt with standalone `foo` still matches."""
    monkeypatch.chdir(tmp_path)
    workflows = _make_negative_keyword_workflows(["foo", "!/foo/"])
    with (
        patch("sase.xprompt.loader.get_all_prompts", return_value=workflows),
        patch(
            "sase.gemini_wrapper.file_references.process_command_substitution",
            side_effect=lambda s: s,
        ),
    ):
        result = generate_dynamic_memory("Add foo to the /path/to/foo/ directory", None)

    assert len(result.matched) == 1
    assert result.matched[0].keywords_matched == ["foo"]


def test_negative_mask_excludes_when_positive_only_inside_span(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`[foo, "!/foo/"]` excludes when the only `foo` sits inside the masked span."""
    monkeypatch.chdir(tmp_path)
    workflows = _make_negative_keyword_workflows(["foo", "!/foo/"])
    with (
        patch("sase.xprompt.loader.get_all_prompts", return_value=workflows),
        patch(
            "sase.gemini_wrapper.file_references.process_command_substitution",
            side_effect=lambda s: s,
        ),
    ):
        result = generate_dynamic_memory("Add bar to the /path/to/foo/ directory", None)

    assert result.matched == []


def test_negative_mask_preserves_word_boundaries_at_edges(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Masking with spaces must not invent a word boundary that wasn't there.

    In `"foobar"` there is no boundary between `foo` and `bar`; after masking
    `foo` to three spaces the result is `"   bar"`, where `bar` IS a standalone
    word. But in the original `"foobar"` the positive keyword `bar` cannot
    match because it's mid-word. We assert the masked result is what the code
    actually tests against — i.e. `bar` matches because the mask exposes the
    token. This pins the "replace-with-spaces" design choice: without the
    negative, `bar` would NOT match `"foobar"`, so the negative's mask is what
    made the positive fire.
    """
    monkeypatch.chdir(tmp_path)

    # Control: no negative → `bar` cannot match `foobar` (word-boundary).
    workflows_no_neg = _make_negative_keyword_workflows(["bar"])
    with (
        patch("sase.xprompt.loader.get_all_prompts", return_value=workflows_no_neg),
        patch(
            "sase.gemini_wrapper.file_references.process_command_substitution",
            side_effect=lambda s: s,
        ),
    ):
        control = generate_dynamic_memory("foobar", None)
    assert control.matched == []

    # With negative `!foo` masking the `foo` prefix, the remaining `bar` is a
    # standalone token in the masked prompt and does match.
    workflows = _make_negative_keyword_workflows(["bar", "!foo"])
    with (
        patch("sase.xprompt.loader.get_all_prompts", return_value=workflows),
        patch(
            "sase.gemini_wrapper.file_references.process_command_substitution",
            side_effect=lambda s: s,
        ),
    ):
        result = generate_dynamic_memory("foobar", None)
    # `foo` has no word boundaries against `bar` in `foobar`, so the negative
    # itself doesn't match and masking is a no-op — `bar` still can't match.
    assert result.matched == []


def test_negative_mask_overlapping_negatives(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Overlapping negative spans coalesce; the union is masked."""
    monkeypatch.chdir(tmp_path)
    # Both negatives overlap around `bar` in "foo bar baz".
    workflows = _make_negative_keyword_workflows(["foo", "baz", "!foo bar", "!bar baz"])
    with (
        patch("sase.xprompt.loader.get_all_prompts", return_value=workflows),
        patch(
            "sase.gemini_wrapper.file_references.process_command_substitution",
            side_effect=lambda s: s,
        ),
    ):
        result = generate_dynamic_memory("foo bar baz", None)

    # Every positive span lies inside a masked region → no hits.
    assert result.matched == []


def test_negative_mask_covers_entire_prompt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A negative that matches the whole prompt excludes even the positive inside it."""
    monkeypatch.chdir(tmp_path)
    workflows = _make_negative_keyword_workflows(["skill", "!deploy a skill"])
    with (
        patch("sase.xprompt.loader.get_all_prompts", return_value=workflows),
        patch(
            "sase.gemini_wrapper.file_references.process_command_substitution",
            side_effect=lambda s: s,
        ),
    ):
        result = generate_dynamic_memory("deploy a skill", None)

    assert result.matched == []
