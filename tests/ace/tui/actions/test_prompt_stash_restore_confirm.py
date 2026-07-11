"""Tests for applying prompt-stash restore picker results."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.ace.tui.modals.stashed_prompts_modal import (
    StashRestoreResult,
    StashedPromptsModal,
)

from ._prompt_stash_restore_helpers import (
    _FakeBar,
    _RestoreHarness,
    _point_store_at,
    _seed,
    _skip_without_pinned_binding,
    _skip_without_prompt_stash_bindings,
    _wait_prompt_stash_tasks,
)


# --- confirm: pop / keep / delete ------------------------------------------


async def test_confirm_restores_into_mounted_bar_in_order(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _skip_without_prompt_stash_bindings()
    path = tmp_path / "prompt_stash.jsonl"
    _point_store_at(monkeypatch, path)
    _seed(
        path,
        [
            ("a", "2026-06-16T10:00:00", "alpha", "model: c", True),
            ("b", "2026-06-16T11:00:00", "beta", "model: c"),
            ("c", "2026-06-16T12:00:00", "gamma", ""),
        ],
    )
    bar = _FakeBar(mode="prompt")
    harness = _RestoreHarness(bar=bar)

    await harness._on_prompt_stash_restore_confirmed(
        StashRestoreResult(pop_ids=["b"], keep_ids=["a"], delete_ids=[])
    )

    # Loaded oldest-first regardless of selection order; frontmatter preserved.
    assert bar.restored == [("alpha", "model: c"), ("beta", "model: c")]
    # Only pop ids are removed; keep ids stay stashed.
    from sase.core.prompt_stash_facade import read_prompt_stash_snapshot

    remaining = read_prompt_stash_snapshot(path).entries
    assert [e.id for e in remaining] == ["a", "c"]
    assert remaining[0].pinned is True
    assert harness.notifications == [("Restored 2 prompts", None)]
    assert harness.applied_counts == [2]  # badge reflects remaining count


async def test_confirm_restores_bundle_row_into_mounted_bar(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _skip_without_prompt_stash_bindings()
    path = tmp_path / "prompt_stash.jsonl"
    _point_store_at(monkeypatch, path)
    _seed(
        path,
        [
            ("bundle", "2026-06-16T10:00:00", "alpha\n---\nbeta", "model: c"),
            ("keep", "2026-06-16T11:00:00", "gamma", ""),
        ],
    )
    bar = _FakeBar(mode="prompt")
    harness = _RestoreHarness(bar=bar)

    await harness._on_prompt_stash_restore_confirmed(
        StashRestoreResult(pop_ids=["bundle"], delete_ids=[])
    )

    assert bar.restored == [("alpha", "model: c"), ("beta", "model: c")]
    from sase.core.prompt_stash_facade import read_prompt_stash_snapshot

    assert [e.id for e in read_prompt_stash_snapshot(path).entries] == ["keep"]
    assert harness.notifications == [("Restored 2 prompts", None)]
    assert harness.applied_counts == [1]


async def test_confirm_without_bar_mounts_home_with_combined_text(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _skip_without_prompt_stash_bindings()
    path = tmp_path / "prompt_stash.jsonl"
    _point_store_at(monkeypatch, path)
    _seed(
        path,
        [
            ("a", "2026-06-16T10:00:00", "first\n---\nsecond", "model: c"),
            ("b", "2026-06-16T11:00:00", "third", ""),
        ],
    )
    harness = _RestoreHarness(bar=None)

    await harness._on_prompt_stash_restore_confirmed(
        StashRestoreResult(pop_ids=["a", "b"], delete_ids=[])
    )

    assert harness.home_mounts == ["model: c\nfirst\n---\nsecond\n---\nthird"]
    assert harness.home_mount_xprompt_markdown == [True]
    assert harness.notifications == [("Restored 3 prompts", None)]


async def test_confirm_without_bar_mounts_single_body_as_xprompt_markdown(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _skip_without_prompt_stash_bindings()
    path = tmp_path / "prompt_stash.jsonl"
    _point_store_at(monkeypatch, path)
    frontmatter = "---\nxprompts:\n  _stash_helper: Use restored helper\n---"
    _seed(
        path,
        [
            (
                "a",
                "2026-06-16T10:00:00",
                "single body",
                frontmatter,
            )
        ],
    )
    harness = _RestoreHarness(bar=None)

    await harness._on_prompt_stash_restore_confirmed(
        StashRestoreResult(pop_ids=["a"], delete_ids=[])
    )

    assert harness.home_mounts == [f"{frontmatter}\nsingle body"]
    assert harness.home_mount_xprompt_markdown == [True]
    assert harness.notifications == [("Restored prompt", None)]


async def test_confirm_delete_only_pops_without_loading(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _skip_without_prompt_stash_bindings()
    path = tmp_path / "prompt_stash.jsonl"
    _point_store_at(monkeypatch, path)
    _seed(
        path,
        [
            ("a", "2026-06-16T10:00:00", "alpha", ""),
            ("b", "2026-06-16T11:00:00", "beta", ""),
        ],
    )
    bar = _FakeBar(mode="prompt")
    harness = _RestoreHarness(bar=bar)

    await harness._on_prompt_stash_restore_confirmed(
        StashRestoreResult(delete_ids=["a"])
    )

    assert bar.restored is None  # nothing loaded
    assert harness.home_mounts == []
    from sase.core.prompt_stash_facade import read_prompt_stash_snapshot

    assert [e.id for e in read_prompt_stash_snapshot(path).entries] == ["b"]
    assert harness.notifications == [("Deleted stashed prompt", None)]


async def test_confirm_restore_and_delete_mixed_summary(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _skip_without_prompt_stash_bindings()
    path = tmp_path / "prompt_stash.jsonl"
    _point_store_at(monkeypatch, path)
    _seed(
        path,
        [
            ("a", "2026-06-16T10:00:00", "alpha", ""),
            ("b", "2026-06-16T11:00:00", "beta", ""),
        ],
    )
    bar = _FakeBar(mode="prompt")
    harness = _RestoreHarness(bar=bar)

    await harness._on_prompt_stash_restore_confirmed(
        StashRestoreResult(pop_ids=["a"], delete_ids=["b"])
    )

    assert bar.restored == [("alpha", "")]
    assert harness.notifications == [("Restored prompt, deleted 1", None)]


async def test_confirm_none_is_noop() -> None:
    harness = _RestoreHarness(bar=_FakeBar())
    await harness._on_prompt_stash_restore_confirmed(None)
    assert harness.notifications == []
    assert harness.applied_counts == []


# --- pin toggle ------------------------------------------------------------


async def test_bundle_pin_toggled_persists_and_refreshes_badge_counts(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _skip_without_pinned_binding()
    path = tmp_path / "prompt_stash.jsonl"
    _point_store_at(monkeypatch, path)
    _seed(
        path,
        [("bundle", "2026-06-16T10:00:00", "alpha\n---\nbeta", "")],
    )
    harness = _RestoreHarness()

    from sase.core.prompt_stash_facade import read_prompt_stash_snapshot

    entry = read_prompt_stash_snapshot(path).entries[0]
    harness.on_stashed_prompts_modal_pin_toggled(
        StashedPromptsModal.PinToggled(entry, True)
    )
    await _wait_prompt_stash_tasks(harness)

    assert read_prompt_stash_snapshot(path).entries[0].pinned is True
    assert harness.notifications == []
    assert harness.applied_counts == [1]
    assert harness.applied_pinned_counts == [1]

    harness.on_stashed_prompts_modal_pin_toggled(
        StashedPromptsModal.PinToggled(entry, False)
    )
    await _wait_prompt_stash_tasks(harness)

    assert read_prompt_stash_snapshot(path).entries[0].pinned is False
    assert harness.notifications == []
    assert harness.applied_counts == [1, 1]
    assert harness.applied_pinned_counts == [1, 0]


# --- keep-only confirm: load without popping -------------------------------


async def test_confirm_keep_only_loads_without_popping(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _skip_without_prompt_stash_bindings()
    path = tmp_path / "prompt_stash.jsonl"
    _point_store_at(monkeypatch, path)
    _seed(
        path,
        [
            ("a", "2026-06-16T10:00:00", "alpha", "model: c"),
            ("b", "2026-06-16T11:00:00", "beta", "model: c"),
            ("c", "2026-06-16T12:00:00", "gamma", ""),
        ],
    )
    bar = _FakeBar(mode="prompt")
    harness = _RestoreHarness(bar=bar)

    await harness._on_prompt_stash_restore_confirmed(
        StashRestoreResult(keep_ids=["b", "a"])
    )

    # Loaded oldest-first regardless of selection order, but the store keeps
    # every entry.
    assert bar.restored == [("alpha", "model: c"), ("beta", "model: c")]
    from sase.core.prompt_stash_facade import read_prompt_stash_snapshot

    remaining = read_prompt_stash_snapshot(path).entries
    assert [e.id for e in remaining] == ["a", "b", "c"]
    assert harness.notifications == [("Restored 2 prompts", None)]
    # Badge unchanged: the entries are still stashed.
    assert harness.applied_counts == []


async def test_confirm_keep_only_single_restore_summary(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _skip_without_prompt_stash_bindings()
    path = tmp_path / "prompt_stash.jsonl"
    _point_store_at(monkeypatch, path)
    _seed(path, [("a", "2026-06-16T10:00:00", "alpha", "")])
    bar = _FakeBar(mode="prompt")
    harness = _RestoreHarness(bar=bar)

    await harness._on_prompt_stash_restore_confirmed(StashRestoreResult(keep_ids=["a"]))

    assert bar.restored == [("alpha", "")]
    assert harness.notifications == [("Restored prompt", None)]
    assert harness.applied_counts == []


async def test_confirm_keep_only_expands_bundle_without_popping(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _skip_without_prompt_stash_bindings()
    path = tmp_path / "prompt_stash.jsonl"
    _point_store_at(monkeypatch, path)
    _seed(
        path,
        [
            (
                "bundle",
                "2026-06-16T10:00:00",
                "alpha\n---\nbeta",
                "model: c",
                True,
            )
        ],
    )
    bar = _FakeBar(mode="prompt")
    harness = _RestoreHarness(bar=bar)

    await harness._on_prompt_stash_restore_confirmed(
        StashRestoreResult(keep_ids=["bundle"])
    )

    assert bar.restored == [("alpha", "model: c"), ("beta", "model: c")]
    from sase.core.prompt_stash_facade import read_prompt_stash_snapshot

    remaining = read_prompt_stash_snapshot(path).entries
    assert [e.id for e in remaining] == ["bundle"]
    assert remaining[0].pinned is True
    assert harness.notifications == [("Restored 2 prompts", None)]
    assert harness.applied_counts == []
