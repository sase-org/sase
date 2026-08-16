"""Tests for Patches TUI persistent profile-query-index routing."""

from __future__ import annotations

from typing import Any

import pytest

from collections import OrderedDict

from sase.ace.query import parse_query_for_profile
from sase.ace.query_profile import compiled_profile_for_builtin_pane
from sase.ace.testing import make_patch
from sase.ace.tui.actions.patch import PatchMixin
from sase.core.query_profile_corpus_facade import (
    ArtifactQueryIndex,
    ArtifactQueryResult,
)


class _FakeRustCorpus:
    def __init__(self, names: list[str], length: int | None = None) -> None:
        self.names = names
        self.length = len(names) if length is None else length

    def __len__(self) -> int:
        return self.length


class _FakeApp(PatchMixin):
    def __init__(
        self,
        patches: list[Any],
        *,
        query: str = '"feature"',
        hide_reverted: bool = False,
        hide_submitted: bool = False,
    ) -> None:
        self.patches = patches
        self.current_idx = 0
        self.current_tab = "patches"
        self._patch_query_profile = compiled_profile_for_builtin_pane("patches")
        assert self._patch_query_profile is not None
        self.parsed_query = parse_query_for_profile(query, self._patch_query_profile)
        self.query_string = query
        self.hide_reverted = hide_reverted
        self.hide_submitted = hide_submitted
        self._all_patches = patches
        self._patch_query_index: ArtifactQueryIndex | None = None
        self._patch_query_index_source_list_id: int | None = None
        self._patch_query_index_generation = 0
        self._patch_query_result_cache = OrderedDict()
        self.marked_indices: set[int] = set()
        self._patches_last_idx = 0
        self._patches_last_name: str | None = None
        self._hidden_reverted_count = 0
        self._hidden_submitted_count = 0
        self.restored_selection = False

    @property
    def canonical_query_string(self) -> str:
        from sase.ace.query import to_canonical_string

        return to_canonical_string(self.parsed_query)

    def _refresh_display(self) -> None:
        return

    def _patch_banner_focus_still_valid(self) -> bool:
        return True

    def _restore_selection_for_current_query(self) -> None:
        self.restored_selection = True


@pytest.fixture
def fake_query_index(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[Any]]:
    calls: dict[str, list[Any]] = {"compile": [], "evaluate": []}

    def compile_artifact_query_index(
        *,
        pane_id: str,
        generation: int,
        profile: Any,
        entries: list[Any],
    ) -> ArtifactQueryIndex:
        calls["compile"].append(entries)
        return ArtifactQueryIndex(
            pane_id=pane_id,
            generation=generation,
            profile=profile,
            row_ids=tuple(cs.name for cs in entries),
            facets={},
            rust_handle=_FakeRustCorpus([cs.name for cs in entries]),
        )

    def evaluate_artifact_query_many(
        query: str,
        index: ArtifactQueryIndex,
        *,
        canonical_query: str,
    ) -> ArtifactQueryResult:
        index.validate()
        calls["evaluate"].append((query, index))
        names = index.rust_handle.names
        if "feature" in query:
            mask = tuple("feature" in name for name in names)
        elif "other" in query:
            mask = tuple("other" in name for name in names)
        else:
            mask = tuple(False for _name in names)
        return ArtifactQueryResult(
            cache_key=index.cache_key(canonical_query),
            matched_row_ids=tuple(
                row_id for row_id, keep in zip(index.row_ids, mask, strict=True) if keep
            ),
            matched_mask=mask,
        )

    monkeypatch.setattr(
        "sase.core.query_profile_corpus_facade.compile_artifact_query_index",
        compile_artifact_query_index,
    )
    monkeypatch.setattr(
        "sase.core.query_profile_corpus_facade.evaluate_artifact_query_many",
        evaluate_artifact_query_many,
    )
    return calls


def test_initial_load_builds_corpus_and_reuses_it_per_query(
    fake_query_index: dict[str, list[Any]],
) -> None:
    specs = [
        make_patch(name="feature_a"),
        make_patch(name="other_b"),
    ]
    app = _FakeApp(specs, query='"feature"')

    app._apply_patches(specs)
    assert [cs.name for cs in app.patches] == ["feature_a"]

    app.query_string = '"other"'
    app.parsed_query = parse_query_for_profile('"other"', app._patch_query_profile)
    refiltered = app._filter_patches(specs)

    assert [cs.name for cs in refiltered] == ["other_b"]
    assert fake_query_index["compile"] == [specs]
    assert [call[0] for call in fake_query_index["evaluate"]] == [
        '"feature"',
        '"other"',
    ]


def test_reload_replaces_corpus_for_new_list_identity(
    fake_query_index: dict[str, list[Any]],
) -> None:
    first = [make_patch(name="feature_a")]
    second = [
        make_patch(name="other_b"),
        make_patch(name="feature_c"),
    ]
    app = _FakeApp(first, query='"feature"')

    app._apply_patches(first)
    app._apply_reloaded_patches(second, current_name=None)

    assert [cs.name for cs in app.patches] == ["feature_c"]
    assert fake_query_index["compile"] == [first, second]
    assert app._patch_query_index_source_list_id == id(second)


def test_repeated_query_hits_evaluation_cache(
    fake_query_index: dict[str, list[Any]],
) -> None:
    specs = [make_patch(name="feature_a")]
    app = _FakeApp(specs, query='"feature"')

    app._apply_patches(specs)
    app._filter_patches(specs)

    assert fake_query_index["compile"] == [specs]
    assert [call[0] for call in fake_query_index["evaluate"]] == ['"feature"']


@pytest.mark.asyncio
async def test_async_reload_prepares_corpus_inside_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    specs = [
        make_patch(name="feature_a"),
        make_patch(name="other_b"),
    ]
    app = _FakeApp([], query='"feature"')
    compile_contexts: list[bool] = []
    worker_active = False

    def compile_artifact_query_index(
        *,
        pane_id: str,
        generation: int,
        profile: Any,
        entries: list[Any],
    ) -> ArtifactQueryIndex:
        compile_contexts.append(worker_active)
        return ArtifactQueryIndex(
            pane_id=pane_id,
            generation=generation,
            profile=profile,
            row_ids=tuple(cs.name for cs in entries),
            facets={},
            rust_handle=_FakeRustCorpus([cs.name for cs in entries]),
        )

    def evaluate_artifact_query_many(
        query: str,
        index: ArtifactQueryIndex,
        *,
        canonical_query: str,
    ) -> ArtifactQueryResult:
        index.validate()
        mask = tuple("feature" in name for name in index.rust_handle.names)
        return ArtifactQueryResult(
            cache_key=index.cache_key(canonical_query),
            matched_row_ids=tuple(
                row_id for row_id, keep in zip(index.row_ids, mask, strict=True) if keep
            ),
            matched_mask=mask,
        )

    async def to_thread(func: Any, /, *args: Any, **kwargs: Any) -> Any:
        nonlocal worker_active
        worker_active = True
        try:
            return func(*args, **kwargs)
        finally:
            worker_active = False

    monkeypatch.setattr(
        "sase.ace.patch.find_all_patches_cached",
        lambda: specs,
    )
    monkeypatch.setattr(
        "sase.core.query_profile_corpus_facade.compile_artifact_query_index",
        compile_artifact_query_index,
    )
    monkeypatch.setattr(
        "sase.core.query_profile_corpus_facade.evaluate_artifact_query_many",
        evaluate_artifact_query_many,
    )
    monkeypatch.setattr("asyncio.to_thread", to_thread)

    await app._reload_and_reposition_async()

    assert [cs.name for cs in app.patches] == ["feature_a"]
    assert compile_contexts == [True]
    assert app._patch_query_index_source_list_id == id(specs)


def test_hide_counts_are_preserved_on_corpus_route(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    specs = [
        make_patch(name="ready", status="Ready"),
        make_patch(name="submitted", status="Submitted"),
        make_patch(name="reverted", status="Reverted"),
        make_patch(name="archived", status="Archived"),
    ]
    app = _FakeApp(
        specs,
        query='"anything"',
        hide_reverted=True,
        hide_submitted=True,
    )

    monkeypatch.setattr(
        "sase.core.query_profile_corpus_facade.compile_artifact_query_index",
        lambda *, pane_id, generation, profile, entries: ArtifactQueryIndex(
            pane_id=pane_id,
            generation=generation,
            profile=profile,
            row_ids=tuple(cs.name for cs in entries),
            facets={},
            rust_handle=_FakeRustCorpus([cs.name for cs in entries]),
        ),
    )
    monkeypatch.setattr(
        "sase.core.query_profile_corpus_facade.evaluate_artifact_query_many",
        lambda _query, index, *, canonical_query: ArtifactQueryResult(
            cache_key=index.cache_key(canonical_query),
            matched_row_ids=index.row_ids,
            matched_mask=tuple(True for _row_id in index.row_ids),
        ),
    )

    app._apply_patches(specs)

    assert [cs.name for cs in app.patches] == ["ready"]
    assert app._hidden_submitted_count == 1
    assert app._hidden_reverted_count == 2


def test_forced_stale_handle_fails_before_returning_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    specs = [make_patch(name="feature_a")]
    app = _FakeApp(specs, query='"feature"')
    app._patch_query_index = ArtifactQueryIndex(
        pane_id="patches",
        generation=1,
        profile=app._patch_query_profile,
        row_ids=("feature_a",),
        facets={},
        rust_handle=_FakeRustCorpus(["feature_a"], length=2),
    )
    app._patch_query_index_source_list_id = id(specs)

    with pytest.raises(ValueError, match="stale query index"):
        app._filter_patches(specs)
