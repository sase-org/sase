"""Tests for :func:`rewrite_dynamic_memory_for_prompt` (post-prestep regeneration)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from sase.memory.dynamic import (
    _parse_dynamic_memory_section,
    rewrite_dynamic_memory_for_prompt,
)
from sase.xprompt.loader_parsing import parse_xprompt_entries
from sase.xprompt.models import xprompt_to_workflow


def _make_memory_workflows() -> dict[str, object]:
    entries = {
        "memory/long/external_repos": {
            "tags": "memory",
            "keywords": ["chezmoi"],
            "content": "# External Repos content",
        },
    }
    xprompts = parse_xprompt_entries(entries, "test")
    return {name: xprompt_to_workflow(xp) for name, xp in xprompts.items()}


# ── _parse_dynamic_memory_section ─────────────────────────────────────────


def test_parse_dynamic_memory_section_single() -> None:
    prompt = (
        "Before\n\n"
        "### DYNAMIC MEMORY\n"
        "- @.sase/memory/long-external-repos.md"
        " (memory/long/external_repos, matched: `chezmoi`)"
    )
    pairs = _parse_dynamic_memory_section(prompt)
    assert pairs == [
        ("memory/long/external_repos", ".sase/memory/long-external-repos.md")
    ]


def test_parse_dynamic_memory_section_multiple() -> None:
    prompt = (
        "### DYNAMIC MEMORY\n"
        "- @.sase/memory/long-a.md (memory/long/a, matched: `x`)\n"
        "- @.sase/memory/long-b.md (memory/long/b, matched: `y`, `z`)"
    )
    pairs = _parse_dynamic_memory_section(prompt)
    assert pairs == [
        ("memory/long/a", ".sase/memory/long-a.md"),
        ("memory/long/b", ".sase/memory/long-b.md"),
    ]


def test_parse_dynamic_memory_section_absent() -> None:
    assert _parse_dynamic_memory_section("nothing here") == []


# ── rewrite_dynamic_memory_for_prompt ─────────────────────────────────────


def test_rewrite_recreates_wiped_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If the workspace was wiped after the early write, late phase restores the file."""
    monkeypatch.chdir(tmp_path)
    # Simulate a prior early pass that wrote the file and an embedded pre-step
    # that then cleaned the workspace: the file does NOT exist on disk now.
    assert not (tmp_path / ".sase" / "memory" / "long-external-repos.md").exists()

    prompt = (
        "Some prompt\n\n"
        "### DYNAMIC MEMORY\n"
        "- @.sase/memory/long-external-repos.md"
        " (memory/long/external_repos, matched: `chezmoi`)"
    )
    workflows = _make_memory_workflows()
    with (
        patch("sase.xprompt.loader.get_all_prompts", return_value=workflows),
        patch(
            "sase.gemini_wrapper.file_references.process_command_substitution",
            side_effect=lambda s: s,
        ),
    ):
        rewrite_dynamic_memory_for_prompt(prompt)

    file_path = tmp_path / ".sase" / "memory" / "long-external-repos.md"
    assert file_path.exists()
    assert file_path.read_text() == "# External Repos content"


def test_rewrite_writes_into_new_cwd_after_chdir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When a pre-step chdir'd into a sibling dir, the late phase writes there."""
    original = tmp_path / "workspace_a"
    new_cwd = tmp_path / "workspace_b"
    original.mkdir()
    new_cwd.mkdir()

    monkeypatch.chdir(new_cwd)
    prompt = (
        "### DYNAMIC MEMORY\n"
        "- @.sase/memory/long-external-repos.md"
        " (memory/long/external_repos, matched: `chezmoi`)"
    )
    workflows = _make_memory_workflows()
    with (
        patch("sase.xprompt.loader.get_all_prompts", return_value=workflows),
        patch(
            "sase.gemini_wrapper.file_references.process_command_substitution",
            side_effect=lambda s: s,
        ),
    ):
        rewrite_dynamic_memory_for_prompt(prompt)

    assert (new_cwd / ".sase" / "memory" / "long-external-repos.md").exists()
    assert not (original / ".sase" / "memory" / "long-external-repos.md").exists()


def test_rewrite_noop_when_no_dynamic_memory_section(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Prompts without the section must not touch the loader or disk."""
    monkeypatch.chdir(tmp_path)
    with patch("sase.xprompt.loader.get_all_prompts") as loader:
        rewrite_dynamic_memory_for_prompt("a plain prompt")
    loader.assert_not_called()
    assert not (tmp_path / ".sase").exists()


def test_preprocess_prompt_late_regenerates_before_validation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """End-to-end: preprocess_prompt_late rewrites memory files before @-ref validation.

    Simulates the production bug: the prompt carries a DYNAMIC MEMORY section
    referencing ``@.sase/memory/long-external-repos.md``, but the on-disk file
    was wiped between the early and late phases.  validate_file_references
    must still succeed because preprocess_prompt_late re-writes the file.
    """
    from sase.llm_provider.preprocessing import preprocess_prompt_late

    monkeypatch.chdir(tmp_path)
    prompt = (
        "Do something\n\n"
        "### DYNAMIC MEMORY\n"
        "- @.sase/memory/long-external-repos.md"
        " (memory/long/external_repos, matched: `chezmoi`)"
    )
    workflows = _make_memory_workflows()
    with (
        patch("sase.xprompt.loader.get_all_prompts", return_value=workflows),
        patch(
            "sase.gemini_wrapper.file_references.process_command_substitution",
            side_effect=lambda s: s,
        ),
        patch(
            "sase.gemini_wrapper.file_references.format_with_prettier",
            side_effect=lambda s: s,
        ),
    ):
        # file_ref_mode="validate" runs validate_file_references, which would
        # sys.exit(1) if .sase/memory/long-external-repos.md did not exist.
        preprocess_prompt_late(prompt, file_ref_mode="validate")

    assert (tmp_path / ".sase" / "memory" / "long-external-repos.md").exists()


def test_rewrite_skips_unknown_xprompt_names(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If a listed xprompt no longer exists in the loader, it's silently skipped."""
    monkeypatch.chdir(tmp_path)
    prompt = (
        "### DYNAMIC MEMORY\n"
        "- @.sase/memory/long-gone.md (memory/long/gone, matched: `x`)"
    )
    workflows = _make_memory_workflows()
    with (
        patch("sase.xprompt.loader.get_all_prompts", return_value=workflows),
        patch(
            "sase.gemini_wrapper.file_references.process_command_substitution",
            side_effect=lambda s: s,
        ),
    ):
        rewrite_dynamic_memory_for_prompt(prompt)

    assert not (tmp_path / ".sase" / "memory" / "long-gone.md").exists()
