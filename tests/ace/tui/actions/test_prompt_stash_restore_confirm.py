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
    _restore_pairs,
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
    await _wait_prompt_stash_tasks(harness)

    # Loaded oldest-first regardless of selection order; frontmatter preserved.
    assert _restore_pairs(bar) == [("alpha", "model: c"), ("beta", "model: c")]
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
    await _wait_prompt_stash_tasks(harness)

    assert _restore_pairs(bar) == [("alpha", "model: c"), ("beta", "model: c")]
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
    await _wait_prompt_stash_tasks(harness)

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
    await _wait_prompt_stash_tasks(harness)

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
    await _wait_prompt_stash_tasks(harness)

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
    await _wait_prompt_stash_tasks(harness)

    assert _restore_pairs(bar) == [("alpha", "")]
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
    await _wait_prompt_stash_tasks(harness)

    # Loaded oldest-first regardless of selection order, but the store keeps
    # every entry.
    assert _restore_pairs(bar) == [("alpha", "model: c"), ("beta", "model: c")]
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
    await _wait_prompt_stash_tasks(harness)

    assert _restore_pairs(bar) == [("alpha", "")]
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
    await _wait_prompt_stash_tasks(harness)

    assert _restore_pairs(bar) == [("alpha", "model: c"), ("beta", "model: c")]
    from sase.core.prompt_stash_facade import read_prompt_stash_snapshot

    remaining = read_prompt_stash_snapshot(path).entries
    assert [e.id for e in remaining] == ["bundle"]
    assert remaining[0].pinned is True
    assert harness.notifications == [("Restored 2 prompts", None)]
    assert harness.applied_counts == []


async def test_confirm_restores_bundle_cursor_on_middle_pane(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _skip_without_prompt_stash_bindings()
    path = tmp_path / "prompt_stash.jsonl"
    _point_store_at(monkeypatch, path)
    from sase.core.prompt_stash_facade import (
        PromptStashCursorWire,
        PromptStashEntryWire,
        append_prompt_stash,
    )

    append_prompt_stash(
        path,
        PromptStashEntryWire(
            id="bundle",
            created_at="2026-06-16T10:00:00",
            text="alpha\n---\nbeta\n---\ngamma",
            frontmatter="model: c",
            cursor=PromptStashCursorWire(pane_index=1, row=0, column=2),
        ),
    )
    bar = _FakeBar(mode="prompt")
    harness = _RestoreHarness(bar=bar)

    await harness._on_prompt_stash_restore_confirmed(
        StashRestoreResult(pop_ids=["bundle"])
    )
    await _wait_prompt_stash_tasks(harness)

    assert bar.restored is not None
    assert [pane.text for pane in bar.restored] == ["alpha", "beta", "gamma"]
    assert [pane.is_focus_target for pane in bar.restored] == [False, True, False]
    assert bar.restored[1].cursor == (0, 2)


async def test_confirm_final_row_cursor_wins_over_earlier_rows(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _skip_without_prompt_stash_bindings()
    path = tmp_path / "prompt_stash.jsonl"
    _point_store_at(monkeypatch, path)
    from sase.core.prompt_stash_facade import (
        PromptStashCursorWire,
        PromptStashEntryWire,
        append_prompt_stash,
    )

    append_prompt_stash(
        path,
        PromptStashEntryWire(
            id="a",
            created_at="2026-06-16T10:00:00",
            text="first",
            cursor=PromptStashCursorWire(pane_index=0, row=0, column=1),
        ),
    )
    append_prompt_stash(
        path,
        PromptStashEntryWire(
            id="b",
            created_at="2026-06-16T11:00:00",
            text="second",
            cursor=PromptStashCursorWire(pane_index=0, row=0, column=4),
        ),
    )
    bar = _FakeBar(mode="prompt")
    harness = _RestoreHarness(bar=bar)

    await harness._on_prompt_stash_restore_confirmed(
        StashRestoreResult(pop_ids=["a", "b"])
    )
    await _wait_prompt_stash_tasks(harness)

    assert bar.restored is not None
    assert [pane.is_focus_target for pane in bar.restored] == [False, True]
    assert bar.restored[1].cursor == (0, 4)


async def test_confirm_without_bar_passes_final_row_cursor(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _skip_without_prompt_stash_bindings()
    path = tmp_path / "prompt_stash.jsonl"
    _point_store_at(monkeypatch, path)
    from sase.core.prompt_stash_facade import (
        PromptStashCursorWire,
        PromptStashEntryWire,
        append_prompt_stash,
    )

    append_prompt_stash(
        path,
        PromptStashEntryWire(
            id="a",
            created_at="2026-06-16T10:00:00",
            text="first",
            cursor=PromptStashCursorWire(pane_index=0, row=0, column=1),
        ),
    )
    append_prompt_stash(
        path,
        PromptStashEntryWire(
            id="b",
            created_at="2026-06-16T11:00:00",
            text="alpha\n---\nbeta",
            cursor=PromptStashCursorWire(pane_index=0, row=0, column=2),
        ),
    )
    harness = _RestoreHarness(bar=None)

    await harness._on_prompt_stash_restore_confirmed(
        StashRestoreResult(pop_ids=["a", "b"])
    )
    await _wait_prompt_stash_tasks(harness)

    assert harness.home_mounts == ["first\n---\nalpha\n---\nbeta"]
    assert harness.home_mount_selected_panes == [1]
    assert harness.home_mount_cursors == [(0, 2)]


async def test_confirm_without_bar_legacy_row_uses_end_fallback(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _skip_without_prompt_stash_bindings()
    path = tmp_path / "prompt_stash.jsonl"
    _point_store_at(monkeypatch, path)
    _seed(path, [("a", "2026-06-16T10:00:00", "solo", "")])
    harness = _RestoreHarness(bar=None)

    await harness._on_prompt_stash_restore_confirmed(StashRestoreResult(pop_ids=["a"]))
    await _wait_prompt_stash_tasks(harness)

    assert harness.home_mounts == ["solo"]
    assert harness.home_mount_selected_panes == [None]
    assert harness.home_mount_cursors == [None]
