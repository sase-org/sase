"""Patch relation-index memo, deferral, startup, and debounce."""

from __future__ import annotations

import asyncio
import threading
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest

from sase.ace.testing.fixtures import make_patch
from sase.ace.tui.actions._startup_loads_index import StartupLoadsIndexMixin
from sase.ace.tui.actions.patch import PatchMixin
from sase.ace.tui.actions.patch._loading import PatchLoadingMixin
from sase.ace.tui.actions.patch._loading_apply import _PreparedPatchLoad
from sase.ace.tui.actions.patch._relation_index import (
    clear_patch_relation_index_memo,
    patch_relation_index_real_build_count,
    patches_pane_is_visible,
    resolve_patch_relation_index,
)
from sase.ace.tui.relations.artifact_links import (
    ArtifactLinksSnapshot,
    known_target_for_ref,
)
from sase.ace.tui.widgets.artifacts.patch_entry import patch_row_target
from sase.core.artifact_entry_target import ArtifactEntryTarget


@pytest.fixture(autouse=True)
def _reset_relation_memo() -> None:
    clear_patch_relation_index_memo()
    yield
    clear_patch_relation_index_memo()


def _patches() -> list[Any]:
    return [
        make_patch(name="root", file_path="/tmp/proj/root.sase"),
        make_patch(
            name="root_child", parent="root", file_path="/tmp/proj/root_child.sase"
        ),
    ]


def _links(stamp: int) -> ArtifactLinksSnapshot:
    return ArtifactLinksSnapshot(source_key=(("proj", stamp, stamp),))


def test_patches_pane_is_visible_matches_auto_refresh_predicate() -> None:
    hidden = SimpleNamespace(current_tab="agents", current_artifacts_subtab="patches")
    stitches = SimpleNamespace(
        current_tab="artifacts", current_artifacts_subtab="stitches"
    )
    visible = SimpleNamespace(
        current_tab="artifacts", current_artifacts_subtab="patches"
    )
    missing_subtab = SimpleNamespace(current_tab="artifacts")
    assert patches_pane_is_visible(hidden) is False
    assert patches_pane_is_visible(stitches) is False
    assert patches_pane_is_visible(visible) is True
    assert patches_pane_is_visible(missing_subtab) is True


def test_hidden_build_is_targets_only_and_skips_real_build_counter() -> None:
    patches = _patches()
    index, deferred = resolve_patch_relation_index(
        patches, artifact_links=_links(1), build_relations=False
    )
    assert deferred is True
    assert index is not None
    assert index.edges == ()
    assert patch_row_target(patches[0]) in index.known_targets
    assert patch_relation_index_real_build_count() == 0


def test_hidden_source_key_churn_does_not_real_build() -> None:
    patches = _patches()
    for stamp in range(10):
        index, deferred = resolve_patch_relation_index(
            patches, artifact_links=_links(stamp), build_relations=False
        )
        assert deferred is True
        assert index is not None
        assert index.edges == ()
    assert patch_relation_index_real_build_count() == 0


def test_memo_hit_on_same_source_key_and_patch_objects() -> None:
    patches = _patches()
    links = _links(1)
    first, _ = resolve_patch_relation_index(
        patches, artifact_links=links, build_relations=True
    )
    assert patch_relation_index_real_build_count() == 1
    second, _ = resolve_patch_relation_index(
        patches, artifact_links=links, build_relations=True
    )
    assert second is first
    assert patch_relation_index_real_build_count() == 1


def test_changed_source_key_rebuilds_full_index() -> None:
    patches = _patches()
    resolve_patch_relation_index(
        patches, artifact_links=_links(1), build_relations=True
    )
    resolve_patch_relation_index(
        patches, artifact_links=_links(2), build_relations=True
    )
    assert patch_relation_index_real_build_count() == 2


def test_full_memo_satisfies_later_targets_only_request() -> None:
    patches = _patches()
    links = _links(1)
    full, deferred = resolve_patch_relation_index(
        patches, artifact_links=links, build_relations=True
    )
    assert deferred is False
    assert full is not None
    assert full.edges
    hidden, hidden_deferred = resolve_patch_relation_index(
        patches, artifact_links=links, build_relations=False
    )
    assert hidden is full
    assert hidden_deferred is False
    assert patch_relation_index_real_build_count() == 1


def test_deferred_memo_does_not_satisfy_full_request() -> None:
    patches = _patches()
    links = _links(1)
    targets, deferred = resolve_patch_relation_index(
        patches, artifact_links=links, build_relations=False
    )
    assert deferred is True
    assert targets is not None
    assert targets.edges == ()
    full, full_deferred = resolve_patch_relation_index(
        patches, artifact_links=links, build_relations=True
    )
    assert full_deferred is False
    assert full is not None
    assert full.edges
    assert full is not targets
    assert patch_relation_index_real_build_count() == 1


def test_link_follow_resolves_patch_target_from_targets_only_index() -> None:
    patches = _patches()
    index, deferred = resolve_patch_relation_index(
        patches, artifact_links=_links(1), build_relations=False
    )
    assert deferred is True
    assert index is not None
    resolved = known_target_for_ref("patch", "root", index.known_targets)
    assert resolved == ArtifactEntryTarget(pane_id="patches", parts=("proj", "root"))


class _ScheduleFake(PatchLoadingMixin):
    def __init__(self) -> None:
        self.current_tab = "agents"
        self.current_artifacts_subtab = "patches"
        self._patch_relation_index_deferred = False
        self._dirty_patches = False
        self._patches_loading = False
        self._patches_refresh_scheduled = False
        self._patches_refresh_pending = False
        self.spawned = 0

    def _spawn_patches_refresh_task(self) -> None:
        self.spawned += 1


def test_entering_patches_with_deferred_index_schedules_one_refresh() -> None:
    app = _ScheduleFake()
    app._maybe_schedule_visible_patch_relation_rebuild()
    assert app.spawned == 0

    app.current_tab = "artifacts"
    app._patch_relation_index_deferred = True
    app._maybe_schedule_visible_patch_relation_rebuild()
    app._maybe_schedule_visible_patch_relation_rebuild()
    assert app.spawned == 1
    assert app._patches_refresh_scheduled is True


def test_entering_patches_with_dirty_flag_schedules_refresh() -> None:
    app = _ScheduleFake()
    app.current_tab = "artifacts"
    app._dirty_patches = True
    app._maybe_schedule_visible_patch_relation_rebuild()
    assert app.spawned == 1


class _ApplyFake(PatchLoadingMixin):
    def __init__(self, patches: list[Any]) -> None:
        self.current_tab = "agents"
        self.current_artifacts_subtab = "patches"
        self.patches = patches
        self.current_idx = 0
        self.hide_reverted = False
        self.hide_submitted = False
        self._all_patches = patches
        self._patch_relation_index = None
        self._patch_relation_index_for_id = None
        self._patch_relation_index_deferred = False
        self._patches_first_load_done = False
        self._pr_unmirrored_counts_by_display_name: dict[str, int] = {}

    def _get_patch_query_index(self, patches: list[Any]) -> None:
        return None

    def _apply_prepared_patch_query_index(
        self, patches: list[Any], query_index: object
    ) -> None:
        return None

    def _filter_patches(self, patches: list[Any]) -> list[Any]:
        return list(patches)

    def _refresh_display(self) -> None:
        return None


def test_apply_patches_uses_prepared_index_without_loop_rebuild() -> None:
    patches = _patches()
    prepared_index, deferred = resolve_patch_relation_index(
        patches, artifact_links=_links(1), build_relations=False
    )
    builds_before = patch_relation_index_real_build_count()
    app = _ApplyFake(patches)
    with patch(
        "sase.ace.tui.actions.patch._loading_apply.resolve_patch_relation_index",
        side_effect=AssertionError("loop rebuilt the relation index"),
    ):
        app._apply_patches(
            patches,
            query_index=None,
            relation_index=prepared_index,
            relation_index_deferred=deferred,
        )
    assert app.relation_index() is prepared_index
    assert app._patch_relation_index_deferred is True
    assert patch_relation_index_real_build_count() == builds_before


def test_apply_patches_hidden_path_never_real_builds() -> None:
    patches = _patches()
    app = _ApplyFake(patches)
    app._apply_patches(patches, query_index=None)
    index = app.relation_index()
    assert index is not None
    assert index.edges == ()
    assert app._patch_relation_index_deferred is True
    assert patch_relation_index_real_build_count() == 0


class _StartupFake(StartupLoadsIndexMixin):
    def __init__(self) -> None:
        self.current_tab = "agents"
        self.current_artifacts_subtab = "patches"
        self._patches_first_load_done = False
        self.prepare_threads: list[int] = []
        self.apply_threads: list[int] = []
        self.scheduled = 0
        self.title = "sase"

    def _read_prompt_stash_counts(self) -> tuple[int, int]:
        return (0, 0)

    def _apply_prompt_stash_counts(self, *_counts: int) -> None:
        return None

    def _prepare_patch_load_from_disk(
        self, *, build_relations: bool
    ) -> _PreparedPatchLoad:
        self.prepare_threads.append(threading.get_ident())
        assert build_relations is False
        return _PreparedPatchLoad(
            all_patches=[],
            query_index=None,
            pr_unmirrored_counts={},
            relation_index=None,
            relation_index_deferred=True,
        )

    def _apply_patches(self, *_args: Any, **_kwargs: Any) -> None:
        self.apply_threads.append(threading.get_ident())

    def _schedule_patches_async_refresh(self) -> None:
        self.scheduled += 1

    def _read_last_selection_name(self) -> None:
        return None

    def _restore_last_selection(self, _name: object) -> None:
        return None

    def _save_startup_query(self) -> None:
        return None

    def _maybe_mark_mount_state_loads_done(self) -> None:
        return None


@pytest.mark.asyncio
async def test_startup_deferred_mount_prepares_off_loop() -> None:
    app = _StartupFake()
    main_ident = threading.get_ident()
    await StartupLoadsIndexMixin._run_deferred_mount_state_loads(app)
    assert app.prepare_threads
    assert all(ident != main_ident for ident in app.prepare_threads)
    assert app.apply_threads == [main_ident]


class _FlipFake(PatchLoadingMixin):
    def __init__(self) -> None:
        self.current_tab = "agents"
        self.current_artifacts_subtab = "patches"
        self.patches: list[Any] = []
        self.current_idx = 0
        self._patches_last_name = None
        self.follow_ups = 0

    def _prepare_patch_load_from_disk(
        self, *, build_relations: bool
    ) -> _PreparedPatchLoad:
        assert build_relations is False
        self.current_tab = "artifacts"
        return _PreparedPatchLoad(
            all_patches=[],
            query_index=None,
            pr_unmirrored_counts={},
            relation_index=None,
            relation_index_deferred=True,
        )

    def _apply_reloaded_patches(self, *_args: Any, **_kwargs: Any) -> None:
        return None

    def _schedule_patches_async_refresh(self) -> None:
        self.follow_ups += 1


@pytest.mark.asyncio
async def test_hidden_reload_schedules_follow_up_if_patches_became_visible() -> None:
    app = _FlipFake()
    await app._reload_and_reposition_async()
    assert app.follow_ups == 1


class _DebounceFake(PatchMixin):
    def __init__(self) -> None:
        self.patches: list[Any] = []
        self.current_idx = 0
        self.parsed_query = None
        self.query_string = ""
        self.hide_reverted = False
        self.hide_submitted = False
        self._all_patches: list[Any] = []
        self.marked_indices: set[int] = set()
        self._hidden_reverted_count = 0
        self._hidden_submitted_count = 0
        self._patches_loading = False
        self._patches_refresh_scheduled = False
        self._patches_refresh_pending = False
        self._patches_refresh_follow_up_timer = None
        self._last_patches_reload_duration = 0.0
        self.timers: list[tuple[float, Any]] = []
        self.spawned = 0

    def _refresh_display(self) -> None:
        return None

    async def _reload_and_reposition_async(
        self, current_name: str | None = None
    ) -> None:
        del current_name
        return None

    def set_timer(self, delay: float, callback: Any) -> Any:
        self.timers.append((delay, callback))
        return SimpleNamespace(stop=lambda: None)

    def _spawn_patches_refresh_task(self) -> None:
        self.spawned += 1


@pytest.mark.asyncio
async def test_adaptive_follow_up_waits_and_coalesces() -> None:
    app = _DebounceFake()
    app._patches_refresh_pending = True
    monotonic_values = iter([100.0, 101.25])

    with patch(
        "sase.ace.tui.actions.patch._loading.time.monotonic",
        side_effect=lambda: next(monotonic_values, 101.25),
    ):
        await app._run_patches_async_refresh()

    assert app._patches_refresh_pending is False
    assert app._patches_refresh_scheduled is True
    assert app.spawned == 0
    assert len(app.timers) == 1
    delay, callback = app.timers[0]
    assert delay == pytest.approx(1.25)
    app._schedule_patches_async_refresh()
    app._schedule_patches_async_refresh()
    assert app.spawned == 0
    callback()
    assert app.spawned == 1
