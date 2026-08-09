"""Tests for Patches TUI persistent query-corpus routing."""

from __future__ import annotations

from typing import Any

import pytest

from sase.ace.query import parse_query
from sase.ace.testing import make_patch
from sase.ace.tui.actions.patch import PatchMixin
from sase.core.query_corpus_facade import QueryCorpus


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
        self.parsed_query = parse_query(query)
        self.query_string = query
        self.hide_reverted = hide_reverted
        self.hide_submitted = hide_submitted
        self._all_patches = patches
        self._query_corpus: QueryCorpus | None = None
        self._query_corpus_source_list_id: int | None = None
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
def fake_query_corpus(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[Any]]:
    calls: dict[str, list[Any]] = {"compile": [], "evaluate": []}

    def compile_query_corpus(patches: list[Any]) -> QueryCorpus:
        calls["compile"].append(patches)
        return QueryCorpus(
            source_list_id=id(patches),
            expected_length=len(patches),
            rust_handle=_FakeRustCorpus([cs.name for cs in patches]),
        )

    def evaluate_query_many_with_corpus(query: str, corpus: QueryCorpus) -> list[bool]:
        corpus.validate()
        calls["evaluate"].append((query, corpus))
        names = corpus.rust_handle.names
        if "feature" in query:
            return ["feature" in name for name in names]
        if "other" in query:
            return ["other" in name for name in names]
        return [False] * len(names)

    monkeypatch.setattr(
        "sase.core.query_corpus_facade.compile_query_corpus",
        compile_query_corpus,
    )
    monkeypatch.setattr(
        "sase.core.query_corpus_facade.evaluate_query_many_with_corpus",
        evaluate_query_many_with_corpus,
    )
    return calls


def test_initial_load_builds_corpus_and_reuses_it_per_query(
    fake_query_corpus: dict[str, list[Any]],
) -> None:
    specs = [
        make_patch(name="feature_a"),
        make_patch(name="other_b"),
    ]
    app = _FakeApp(specs, query='"feature"')

    app._apply_patches(specs)
    assert [cs.name for cs in app.patches] == ["feature_a"]

    app.query_string = '"other"'
    app.parsed_query = parse_query('"other"')
    refiltered = app._filter_patches(specs)

    assert [cs.name for cs in refiltered] == ["other_b"]
    assert fake_query_corpus["compile"] == [specs]
    assert [call[0] for call in fake_query_corpus["evaluate"]] == [
        '"feature"',
        '"other"',
    ]


def test_reload_replaces_corpus_for_new_list_identity(
    fake_query_corpus: dict[str, list[Any]],
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
    assert fake_query_corpus["compile"] == [first, second]
    assert app._query_corpus_source_list_id == id(second)


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

    def compile_query_corpus(patches: list[Any]) -> QueryCorpus:
        compile_contexts.append(worker_active)
        return QueryCorpus(
            source_list_id=id(patches),
            expected_length=len(patches),
            rust_handle=_FakeRustCorpus([cs.name for cs in patches]),
        )

    def evaluate_query_many_with_corpus(query: str, corpus: QueryCorpus) -> list[bool]:
        corpus.validate()
        return ["feature" in name for name in corpus.rust_handle.names]

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
        "sase.core.query_corpus_facade.compile_query_corpus",
        compile_query_corpus,
    )
    monkeypatch.setattr(
        "sase.core.query_corpus_facade.evaluate_query_many_with_corpus",
        evaluate_query_many_with_corpus,
    )
    monkeypatch.setattr("asyncio.to_thread", to_thread)

    await app._reload_and_reposition_async()

    assert [cs.name for cs in app.patches] == ["feature_a"]
    assert compile_contexts == [True]
    assert app._query_corpus_source_list_id == id(specs)


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
        "sase.core.query_corpus_facade.compile_query_corpus",
        lambda patches: QueryCorpus(
            source_list_id=id(patches),
            expected_length=len(patches),
            rust_handle=_FakeRustCorpus([cs.name for cs in patches]),
        ),
    )
    monkeypatch.setattr(
        "sase.core.query_corpus_facade.evaluate_query_many_with_corpus",
        lambda _query, corpus: [True] * len(corpus.rust_handle),
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
    app._query_corpus = QueryCorpus(
        source_list_id=id(specs),
        expected_length=len(specs),
        rust_handle=_FakeRustCorpus(["feature_a"], length=2),
    )
    app._query_corpus_source_list_id = id(specs)

    def evaluate_query_many_with_corpus(query: str, corpus: QueryCorpus) -> list[bool]:
        del query
        corpus.validate()
        return [True]

    monkeypatch.setattr(
        "sase.core.query_corpus_facade.evaluate_query_many_with_corpus",
        evaluate_query_many_with_corpus,
    )

    with pytest.raises(ValueError, match="stale query corpus wrapper"):
        app._filter_patches(specs)
