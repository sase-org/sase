"""Unit tests for the best-effort failed-launch prompt-stash helper.

The helper preserves a submitted prompt whose launch failed into the existing
prompt-stash store so it stays recoverable through ``gp`` / ``gP``. It must:

- stash a long prompt with ``source="failed_launch"``,
- lift a leading xprompt/frontmatter block into ``frontmatter`` and store the
  body as ``text``,
- keep multi-prompt bodies as one canonical bundle row,
- skip blank prompts, and
- swallow a missing Rust binding / append failure without raising.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.agent.failed_launch_prompt_stash import stash_failed_launch_prompt
from sase.core.rust import RUST_EXTENSION_MODULE_NAME


def _skip_without_prompt_stash_bindings() -> None:
    rust_module = pytest.importorskip(RUST_EXTENSION_MODULE_NAME)
    if not hasattr(rust_module, "append_prompt_stash"):
        pytest.skip("sase_core_rs is too old (no append_prompt_stash binding).")


def _point_store_at(monkeypatch: pytest.MonkeyPatch, path: Path) -> None:
    monkeypatch.setattr("sase.core.paths.prompt_stash_path", lambda: path, raising=True)


def _read_entries(path: Path) -> list:
    from sase.core.prompt_stash_facade import read_prompt_stash_snapshot

    return list(read_prompt_stash_snapshot(path).entries)


def test_stashes_long_prompt_with_failed_launch_source(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _skip_without_prompt_stash_bindings()
    path = tmp_path / "prompt_stash.jsonl"
    _point_store_at(monkeypatch, path)

    long_prompt = "please build the entire feature " * 8
    stash_failed_launch_prompt(long_prompt, project="proj-a")

    entries = _read_entries(path)
    assert len(entries) == 1
    entry = entries[0]
    assert entry.text == long_prompt.strip()
    assert entry.frontmatter == ""
    assert entry.project == "proj-a"
    assert entry.source == "failed_launch"
    assert entry.pane_index == 0
    assert entry.id


def test_extracts_leading_frontmatter_into_frontmatter_field(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _skip_without_prompt_stash_bindings()
    path = tmp_path / "prompt_stash.jsonl"
    _point_store_at(monkeypatch, path)

    frontmatter = "---\nxprompts:\n  _helper: Use saved helper rules\n---"
    stash_failed_launch_prompt(f"{frontmatter}\nrun the helper now")

    entries = _read_entries(path)
    assert len(entries) == 1
    entry = entries[0]
    assert entry.text == "run the helper now"
    assert entry.frontmatter == frontmatter
    assert "xprompts:\n" in entry.frontmatter


def test_preserves_multi_prompt_body_as_single_bundle_row(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _skip_without_prompt_stash_bindings()
    path = tmp_path / "prompt_stash.jsonl"
    _point_store_at(monkeypatch, path)

    stash_failed_launch_prompt("first segment\n---\nsecond segment")

    entries = _read_entries(path)
    # One row, canonical separator, so restore expands it as a bundle.
    assert len(entries) == 1
    assert entries[0].text == "first segment\n---\nsecond segment"


def test_skips_blank_prompts(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _skip_without_prompt_stash_bindings()
    path = tmp_path / "prompt_stash.jsonl"
    _point_store_at(monkeypatch, path)

    stash_failed_launch_prompt("")
    stash_failed_launch_prompt("   \n\t ")

    assert not path.exists()


def test_swallows_missing_binding_without_raising(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A failed append degrades silently and never replaces the launch error."""
    path = tmp_path / "prompt_stash.jsonl"
    _point_store_at(monkeypatch, path)

    def _boom(_name: str) -> object:
        raise ImportError("sase_core_rs is not importable in this environment")

    monkeypatch.setattr("sase.core.prompt_stash_facade.require_rust_binding", _boom)

    # Must not raise even though the underlying append fails.
    stash_failed_launch_prompt("a prompt that cannot be persisted")

    assert not path.exists()
