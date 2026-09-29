"""Tests for applying prompt-stash restore picker results.

Covers pop / keep / delete confirms, the pin toggle, and keep-only confirms
that load without popping. Cursor propagation, in-place deletes, and failure
recovery live in
`test_prompt_stash_restore_confirm_robustness.py`. The original
`test_prompt_stash_restore_confirm.py` module remains as a facade that lazily
re-exports every test here under its historic import path.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.ace.tui.modals.stashed_prompts_modal import (
    StashRestoreResult,
    StashedPromptsModal,
)

from ._prompt_stash_restore_helpers import (
    FakeBar,
    RestoreHarness,
    point_store_at,
    restore_pairs,
    seed_prompt_stash,
    skip_without_pinned_binding,
    skip_without_prompt_stash_bindings,
    wait_prompt_stash_tasks,
)


# --- confirm: pop / keep / delete ------------------------------------------


async def test_confirm_restores_into_mounted_bar_in_order(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    skip_without_prompt_stash_bindings()
    path = tmp_path / "prompt_stash.jsonl"
    point_store_at(monkeypatch, path)
    seed_prompt_stash(
        path,
        [
            ("a", "2026-06-16T10:00:00", "alpha", "model: c", True),
            ("b", "2026-06-16T11:00:00", "beta", "model: c"),
            ("c", "2026-06-16T12:00:00", "gamma", ""),
        ],
    )
    bar = FakeBar(mode="prompt")
    harness = RestoreHarness(bar=bar)

    await harness._on_prompt_stash_restore_confirmed(
        StashRestoreResult(pop_ids=["b"], keep_ids=["a"], delete_ids=[])
    )
    await wait_prompt_stash_tasks(harness)

    # Loaded oldest-first regardless of selection order; frontmatter preserved.
    assert restore_pairs(bar) == [("alpha", "model: c"), ("beta", "model: c")]
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
    skip_without_prompt_stash_bindings()
    path = tmp_path / "prompt_stash.jsonl"
    point_store_at(monkeypatch, path)
    seed_prompt_stash(
        path,
        [
            ("bundle", "2026-06-16T10:00:00", "alpha\n---\nbeta", "model: c"),
            ("keep", "2026-06-16T11:00:00", "gamma", ""),
        ],
    )
    bar = FakeBar(mode="prompt")
    harness = RestoreHarness(bar=bar)

    await harness._on_prompt_stash_restore_confirmed(
        StashRestoreResult(pop_ids=["bundle"], delete_ids=[])
    )
    await wait_prompt_stash_tasks(harness)

    assert restore_pairs(bar) == [("alpha", "model: c"), ("beta", "model: c")]
    from sase.core.prompt_stash_facade import read_prompt_stash_snapshot

    assert [e.id for e in read_prompt_stash_snapshot(path).entries] == ["keep"]
    assert harness.notifications == [("Restored 2 prompts", None)]
    assert harness.applied_counts == [1]


async def test_confirm_without_bar_mounts_home_with_combined_text(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    skip_without_prompt_stash_bindings()
    path = tmp_path / "prompt_stash.jsonl"
    point_store_at(monkeypatch, path)
    seed_prompt_stash(
        path,
        [
            ("a", "2026-06-16T10:00:00", "first\n---\nsecond", "model: c"),
            ("b", "2026-06-16T11:00:00", "third", ""),
        ],
    )
    harness = RestoreHarness(bar=None)

    await harness._on_prompt_stash_restore_confirmed(
        StashRestoreResult(pop_ids=["a", "b"], delete_ids=[])
    )
    await wait_prompt_stash_tasks(harness)

    assert harness.home_mounts == ["model: c\nfirst\n---\nsecond\n---\nthird"]
    assert harness.home_mount_xprompt_markdown == [True]
    assert harness.notifications == [("Restored 3 prompts", None)]


async def test_confirm_without_bar_mounts_single_body_as_xprompt_markdown(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    skip_without_prompt_stash_bindings()
    path = tmp_path / "prompt_stash.jsonl"
    point_store_at(monkeypatch, path)
    frontmatter = "---\nxprompts:\n  _stash_helper: Use restored helper\n---"
    seed_prompt_stash(
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
    harness = RestoreHarness(bar=None)

    await harness._on_prompt_stash_restore_confirmed(
        StashRestoreResult(pop_ids=["a"], delete_ids=[])
    )
    await wait_prompt_stash_tasks(harness)

    assert harness.home_mounts == [f"{frontmatter}\nsingle body"]
    assert harness.home_mount_xprompt_markdown == [True]
    assert harness.notifications == [("Restored prompt", None)]


async def test_confirm_delete_only_pops_without_loading(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    skip_without_prompt_stash_bindings()
    path = tmp_path / "prompt_stash.jsonl"
    point_store_at(monkeypatch, path)
    seed_prompt_stash(
        path,
        [
            ("a", "2026-06-16T10:00:00", "alpha", ""),
            ("b", "2026-06-16T11:00:00", "beta", ""),
        ],
    )
    bar = FakeBar(mode="prompt")
    harness = RestoreHarness(bar=bar)

    await harness._on_prompt_stash_restore_confirmed(
        StashRestoreResult(delete_ids=["a"])
    )
    await wait_prompt_stash_tasks(harness)

    assert bar.restored is None  # nothing loaded
    assert harness.home_mounts == []
    from sase.core.prompt_stash_facade import read_prompt_stash_snapshot

    assert [e.id for e in read_prompt_stash_snapshot(path).entries] == ["b"]
    assert harness.notifications == [
        (
            "Deleted stashed prompt. Drafts stay recoverable with "
            "`sase prompt stash-archive`.",
            None,
        )
    ]


async def test_confirm_restore_and_delete_mixed_summary(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    skip_without_prompt_stash_bindings()
    path = tmp_path / "prompt_stash.jsonl"
    point_store_at(monkeypatch, path)
    seed_prompt_stash(
        path,
        [
            ("a", "2026-06-16T10:00:00", "alpha", ""),
            ("b", "2026-06-16T11:00:00", "beta", ""),
        ],
    )
    bar = FakeBar(mode="prompt")
    harness = RestoreHarness(bar=bar)

    await harness._on_prompt_stash_restore_confirmed(
        StashRestoreResult(pop_ids=["a"], delete_ids=["b"])
    )
    await wait_prompt_stash_tasks(harness)

    assert restore_pairs(bar) == [("alpha", "")]
    assert harness.notifications == [
        (
            "Restored prompt, deleted 1. Drafts stay recoverable with "
            "`sase prompt stash-archive`.",
            None,
        )
    ]


async def test_confirm_none_is_noop() -> None:
    harness = RestoreHarness(bar=FakeBar())
    await harness._on_prompt_stash_restore_confirmed(None)
    assert harness.notifications == []
    assert harness.applied_counts == []


# --- pin toggle ------------------------------------------------------------


async def test_bundle_pin_toggled_persists_and_refreshes_badge_counts(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    skip_without_pinned_binding()
    path = tmp_path / "prompt_stash.jsonl"
    point_store_at(monkeypatch, path)
    seed_prompt_stash(
        path,
        [("bundle", "2026-06-16T10:00:00", "alpha\n---\nbeta", "")],
    )
    harness = RestoreHarness()

    from sase.core.prompt_stash_facade import read_prompt_stash_snapshot

    entry = read_prompt_stash_snapshot(path).entries[0]
    harness.on_stashed_prompts_modal_pin_toggled(
        StashedPromptsModal.PinToggled(entry, True)
    )
    await wait_prompt_stash_tasks(harness)

    assert read_prompt_stash_snapshot(path).entries[0].pinned is True
    assert harness.notifications == []
    assert harness.applied_counts == [1]
    assert harness.applied_pinned_counts == [1]

    harness.on_stashed_prompts_modal_pin_toggled(
        StashedPromptsModal.PinToggled(entry, False)
    )
    await wait_prompt_stash_tasks(harness)

    assert read_prompt_stash_snapshot(path).entries[0].pinned is False
    assert harness.notifications == []
    assert harness.applied_counts == [1, 1]
    assert harness.applied_pinned_counts == [1, 0]


# --- keep-only confirm: load without popping -------------------------------


async def test_confirm_keep_only_loads_without_popping(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    skip_without_prompt_stash_bindings()
    path = tmp_path / "prompt_stash.jsonl"
    point_store_at(monkeypatch, path)
    seed_prompt_stash(
        path,
        [
            ("a", "2026-06-16T10:00:00", "alpha", "model: c"),
            ("b", "2026-06-16T11:00:00", "beta", "model: c"),
            ("c", "2026-06-16T12:00:00", "gamma", ""),
        ],
    )
    bar = FakeBar(mode="prompt")
    harness = RestoreHarness(bar=bar)

    await harness._on_prompt_stash_restore_confirmed(
        StashRestoreResult(keep_ids=["b", "a"])
    )
    await wait_prompt_stash_tasks(harness)

    # Loaded oldest-first regardless of selection order, but the store keeps
    # every entry.
    assert restore_pairs(bar) == [("alpha", "model: c"), ("beta", "model: c")]
    from sase.core.prompt_stash_facade import read_prompt_stash_snapshot

    remaining = read_prompt_stash_snapshot(path).entries
    assert [e.id for e in remaining] == ["a", "b", "c"]
    assert harness.notifications == [("Restored 2 prompts", None)]
    # Badge unchanged: the entries are still stashed.
    assert harness.applied_counts == []


async def test_confirm_keep_only_single_restore_summary(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    skip_without_prompt_stash_bindings()
    path = tmp_path / "prompt_stash.jsonl"
    point_store_at(monkeypatch, path)
    seed_prompt_stash(path, [("a", "2026-06-16T10:00:00", "alpha", "")])
    bar = FakeBar(mode="prompt")
    harness = RestoreHarness(bar=bar)

    await harness._on_prompt_stash_restore_confirmed(StashRestoreResult(keep_ids=["a"]))
    await wait_prompt_stash_tasks(harness)

    assert restore_pairs(bar) == [("alpha", "")]
    assert harness.notifications == [("Restored prompt", None)]
    assert harness.applied_counts == []


async def test_confirm_keep_only_expands_bundle_without_popping(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    skip_without_prompt_stash_bindings()
    path = tmp_path / "prompt_stash.jsonl"
    point_store_at(monkeypatch, path)
    seed_prompt_stash(
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
    bar = FakeBar(mode="prompt")
    harness = RestoreHarness(bar=bar)

    await harness._on_prompt_stash_restore_confirmed(
        StashRestoreResult(keep_ids=["bundle"])
    )
    await wait_prompt_stash_tasks(harness)

    assert restore_pairs(bar) == [("alpha", "model: c"), ("beta", "model: c")]
    from sase.core.prompt_stash_facade import read_prompt_stash_snapshot

    remaining = read_prompt_stash_snapshot(path).entries
    assert [e.id for e in remaining] == ["bundle"]
    assert remaining[0].pinned is True
    assert harness.notifications == [("Restored 2 prompts", None)]
    assert harness.applied_counts == []
