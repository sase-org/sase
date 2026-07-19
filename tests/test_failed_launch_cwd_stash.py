"""Failed-launch stash coverage for the non-TUI CWD / bead-work launch paths.

These paths feed mobile and CLI launch surfaces. A launch that fails before any
agent is created (e.g. an alias-map conflict or a pre-launch validation error)
must still preserve the submitted prompt in the per-user stash so it stays
recoverable -- no mobile-specific persistence path is added.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.core.rust import RUST_EXTENSION_MODULE_NAME


def _skip_without_prompt_stash_bindings() -> None:
    rust_module = pytest.importorskip(RUST_EXTENSION_MODULE_NAME)
    if not hasattr(rust_module, "append_prompt_stash"):
        pytest.skip("sase_core_rs is too old (no append_prompt_stash binding).")


def _stash_entries(path: Path) -> list:
    from sase.core.prompt_stash_facade import read_prompt_stash_snapshot

    return list(read_prompt_stash_snapshot(path).entries)


def test_launch_from_cwd_stashes_query_on_alias_canonicalization_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _skip_without_prompt_stash_bindings()
    stash_path = tmp_path / "prompt_stash.jsonl"
    monkeypatch.setattr(
        "sase.core.paths.prompt_stash_path", lambda: stash_path, raising=True
    )

    def _boom(_query: str) -> str:
        raise RuntimeError("ambiguous project alias")

    monkeypatch.setattr(
        "sase.project_aliases.canonicalize_project_aliases_in_prompt", _boom
    )

    from sase.agent.launcher import launch_agents_from_cwd

    submitted = "#al:thing do a very long unit of work please"
    with pytest.raises(RuntimeError, match="ambiguous project alias"):
        launch_agents_from_cwd(submitted)

    entries = _stash_entries(stash_path)
    assert [e.text for e in entries] == [submitted]
    assert entries[0].source == "failed_launch"


def test_chop_launch_does_not_stash_alias_canonicalization_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _skip_without_prompt_stash_bindings()
    stash_path = tmp_path / "prompt_stash.jsonl"
    monkeypatch.setattr(
        "sase.core.paths.prompt_stash_path", lambda: stash_path, raising=True
    )

    def _boom(_query: str) -> str:
        raise RuntimeError("ambiguous project alias")

    monkeypatch.setattr(
        "sase.project_aliases.canonicalize_project_aliases_in_prompt", _boom
    )

    from sase.agent.launcher import launch_agents_from_cwd
    from sase.axe.chop_agents import ENV_CHOP_NAME

    with pytest.raises(RuntimeError, match="ambiguous project alias"):
        launch_agents_from_cwd(
            "#al:thing run generated chop work",
            extra_env={ENV_CHOP_NAME: "refresh_docs"},
        )

    assert _stash_entries(stash_path) == []


def test_planned_bead_work_stashes_on_validation_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _skip_without_prompt_stash_bindings()
    stash_path = tmp_path / "prompt_stash.jsonl"
    monkeypatch.setattr(
        "sase.core.paths.prompt_stash_path", lambda: stash_path, raising=True
    )

    from sase.agent.launch_cwd_bead_work import launch_planned_bead_work_agents

    # Rendered name (%name:actual) does not match the planned expected name, so
    # pre-launch validation raises before the existing launch catch blocks.
    with pytest.raises(ValueError):
        launch_planned_bead_work_agents(
            segments=["%name:actual finish the bead work"],
            segment_extra_env=[{}],
            expected_names={"expected"},
            project_name="proj",
        )

    entries = _stash_entries(stash_path)
    assert len(entries) == 1
    assert entries[0].source == "failed_launch"
    assert "finish the bead work" in entries[0].text
