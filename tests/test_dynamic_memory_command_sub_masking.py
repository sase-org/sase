"""Tests for ``$(...)`` command-substitution masking in dynamic memory matching.

The matcher runs after upstream xprompt processing has already inlined the
stdout of ``$(...)`` substitutions in xprompt argument positions. Without
masking, that environment-derived text (file paths, command output) would
trigger spurious keyword matches against memories whose keywords happen to
appear in the inlined data but never appear in user-authored prompt text.
"""

from pathlib import Path
from unittest.mock import patch

import pytest

from sase.memory.dynamic import generate_dynamic_memory
from sase.xprompt.loader_parsing import parse_xprompt_entries
from sase.xprompt.models import xprompt_to_workflow


def _make_workflows(keywords: list[str]) -> dict[str, object]:
    entries = {
        "memory/long/sub_test": {
            "tags": "memory",
            "keywords": keywords,
            "content": "# Sub test content",
        }
    }
    xprompts = parse_xprompt_entries(entries, "test")
    return {name: xprompt_to_workflow(xp) for name, xp in xprompts.items()}


# ── core masking behavior ────────────────────────────────────────────────


def test_keyword_inside_command_substitution_is_ignored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A keyword whose only occurrence is inside ``$(...)`` must not match."""
    monkeypatch.chdir(tmp_path)
    workflows = _make_workflows(["growbird"])
    with (
        patch("sase.xprompt.loader.get_all_prompts", return_value=workflows),
        patch(
            "sase.gemini_wrapper.file_references.process_command_substitution",
            side_effect=lambda s: s,
        ),
    ):
        result = generate_dynamic_memory(
            "Can you describe what this CL does? @$(echo path/to/growbird/foo.py)",
            None,
        )

    assert result.matched == []


def test_nested_command_substitution_fully_masked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Nested ``$(outer $(inner build))`` is wholly masked — outermost span wins."""
    monkeypatch.chdir(tmp_path)
    workflows = _make_workflows(["build"])
    with (
        patch("sase.xprompt.loader.get_all_prompts", return_value=workflows),
        patch(
            "sase.gemini_wrapper.file_references.process_command_substitution",
            side_effect=lambda s: s,
        ),
    ):
        result = generate_dynamic_memory("@$(outer $(inner build))", None)

    assert result.matched == []


def test_escaped_dollar_paren_preserves_literal_match(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``\\$(build)`` is literal text, so ``build`` keyword still matches."""
    monkeypatch.chdir(tmp_path)
    workflows = _make_workflows(["build"])
    with (
        patch("sase.xprompt.loader.get_all_prompts", return_value=workflows),
        patch(
            "sase.gemini_wrapper.file_references.process_command_substitution",
            side_effect=lambda s: s,
        ),
    ):
        result = generate_dynamic_memory("discuss \\$(build) options", None)

    assert len(result.matched) == 1
    assert result.matched[0].keywords_matched == ["build"]


def test_keyword_outside_substitution_still_matches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A keyword that appears outside any ``$(...)`` still matches."""
    monkeypatch.chdir(tmp_path)
    workflows = _make_workflows(["build"])
    with (
        patch("sase.xprompt.loader.get_all_prompts", return_value=workflows),
        patch(
            "sase.gemini_wrapper.file_references.process_command_substitution",
            side_effect=lambda s: s,
        ),
    ):
        result = generate_dynamic_memory("Please run the build $(echo skip)", None)

    assert len(result.matched) == 1
    assert result.matched[0].keywords_matched == ["build"]


# ── composes with negative-keyword masking ───────────────────────────────


def test_command_sub_masking_composes_with_negative_masking(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Both masking passes compose: positive outside both masks fires; otherwise excluded.

    The command-substitution mask runs once on the whole prompt up-front; the
    negative-keyword mask is applied per-memory afterwards. Offsets must stay
    aligned so word-boundary semantics still apply at the seam.
    """
    monkeypatch.chdir(tmp_path)

    # Positive `skill` outside both masks; negative `!banana` masks the literal
    # `banana` token; `$(...)` masks the inlined `growbird` token.
    workflows = _make_workflows(["skill", "growbird", "!banana"])
    with (
        patch("sase.xprompt.loader.get_all_prompts", return_value=workflows),
        patch(
            "sase.gemini_wrapper.file_references.process_command_substitution",
            side_effect=lambda s: s,
        ),
    ):
        result = generate_dynamic_memory(
            "deploy a skill near banana via $(echo growbird)",
            None,
        )

    assert len(result.matched) == 1
    # `skill` survives both masks; `growbird` is inside the $(...) span;
    # `!banana` masks the standalone `banana` (which is not a positive here
    # anyway, but the mask must not bleed into `skill`).
    assert result.matched[0].keywords_matched == ["skill"]


# ── end-to-end regression for the reported bug ───────────────────────────


def test_cldd_style_xprompt_does_not_match_inlined_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reproduces the reported bug: ``#cldd``-shaped expansion with ``$(sase_xcmd ...)``
    wrapping inlined file paths must not match ``growbird`` / ``BUILD`` / ``test``.
    """
    monkeypatch.chdir(tmp_path)
    entries = {
        "memory/long/growbird": {
            "tags": "memory",
            "keywords": ["growbird"],
            "content": "# growbird content",
        },
        "memory/long/build_cleaner": {
            "tags": "memory",
            "keywords": ["build", "BUILD"],
            "content": "# build content",
        },
        "memory/long/aaa_test_structure": {
            "tags": "memory",
            "keywords": ["test"],
            "content": "# test content",
        },
    }
    xprompts = parse_xprompt_entries(entries, "test")
    workflows = {name: xprompt_to_workflow(xp) for name, xp in xprompts.items()}

    # Shape produced after process_xprompt_references resolves $(...) inside
    # the inner cmd argument and the x-xprompt body wraps it in $(sase_xcmd ...).
    prompt = (
        "Can you describe what this CL does?\n"
        "@$(sase_xcmd cl_changes.diff hg pdiff "
        "path/to/google3/.../growbird/foo.py "
        "path/to/google3/.../BUILD "
        "path/to/google3/.../foo_test.py | perl -nE ...)\n"
        "@$(sase_xcmd cl_desc cl_desc --short)"
    )

    with (
        patch("sase.xprompt.loader.get_all_prompts", return_value=workflows),
        patch(
            "sase.gemini_wrapper.file_references.process_command_substitution",
            side_effect=lambda s: s,
        ),
    ):
        result = generate_dynamic_memory(prompt, None)

    assert result.matched == [], (
        f"Expected no matches; got {[m.name for m in result.matched]}"
    )
