"""Tests for ChangeSpecs TUI persistent query-corpus routing."""

from __future__ import annotations

from typing import Any

import pytest

from sase.ace.query import parse_query
from sase.ace.testing import make_changespec
from sase.ace.tui.actions.changespec import ChangeSpecMixin
from sase.core.query_corpus_facade import QueryCorpus


class _FakeRustCorpus:
    def __init__(self, names: list[str], length: int | None = None) -> None:
        self.names = names
        self.length = len(names) if length is None else length

    def __len__(self) -> int:
        return self.length


class _FakeApp(ChangeSpecMixin):
    def __init__(
        self,
        changespecs: list[Any],
        *,
        query: str = '"feature"',
        hide_reverted: bool = False,
        hide_submitted: bool = False,
    ) -> None:
        self.changespecs = changespecs
        self.current_idx = 0
        self.current_tab = "changespecs"
        self.parsed_query = parse_query(query)
        self.query_string = query
        self.hide_reverted = hide_reverted
        self.hide_submitted = hide_submitted
        self._all_changespecs = changespecs
        self._query_corpus: QueryCorpus | None = None
        self._query_corpus_source_list_id: int | None = None
        self.marked_indices: set[int] = set()
        self._changespecs_last_idx = 0
        self._changespecs_last_name: str | None = None
        self._query_reverted_count = 0
        self._query_submitted_count = 0
        self._hidden_reverted_count = 0
        self._hidden_submitted_count = 0
        self.restored_selection = False

    @property
    def canonical_query_string(self) -> str:
        from sase.ace.query import to_canonical_string

        return to_canonical_string(self.parsed_query)

    def _update_cls_tab_count(self) -> None:
        return

    def _refresh_display(self) -> None:
        return

    def _changespec_banner_focus_still_valid(self) -> bool:
        return True

    def _restore_selection_for_current_query(self) -> None:
        self.restored_selection = True


@pytest.fixture
def fake_query_corpus(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[Any]]:
    calls: dict[str, list[Any]] = {"compile": [], "evaluate": []}

    def compile_query_corpus(changespecs: list[Any]) -> QueryCorpus:
        calls["compile"].append(changespecs)
        return QueryCorpus(
            source_list_id=id(changespecs),
            expected_length=len(changespecs),
            rust_handle=_FakeRustCorpus([cs.name for cs in changespecs]),
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
        make_changespec(name="feature_a"),
        make_changespec(name="other_b"),
    ]
    app = _FakeApp(specs, query='"feature"')

    app._apply_changespecs(specs)
    assert [cs.name for cs in app.changespecs] == ["feature_a"]

    app.query_string = '"other"'
    app.parsed_query = parse_query('"other"')
    refiltered = app._filter_changespecs(specs)

    assert [cs.name for cs in refiltered] == ["other_b"]
    assert fake_query_corpus["compile"] == [specs]
    assert [call[0] for call in fake_query_corpus["evaluate"]] == [
        '"feature"',
        '"other"',
    ]


def test_reload_replaces_corpus_for_new_list_identity(
    fake_query_corpus: dict[str, list[Any]],
) -> None:
    first = [make_changespec(name="feature_a")]
    second = [
        make_changespec(name="other_b"),
        make_changespec(name="feature_c"),
    ]
    app = _FakeApp(first, query='"feature"')

    app._apply_changespecs(first)
    app._apply_reloaded_changespecs(second, current_name=None)

    assert [cs.name for cs in app.changespecs] == ["feature_c"]
    assert fake_query_corpus["compile"] == [first, second]
    assert app._query_corpus_source_list_id == id(second)


@pytest.mark.asyncio
async def test_startup_saved_query_fallback_reuses_loaded_corpus(
    fake_query_corpus: dict[str, list[Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    specs = [
        make_changespec(name="feature_a"),
        make_changespec(name="other_b"),
    ]
    app = _FakeApp(specs, query='"nomatch"')
    app._apply_changespecs(specs)

    monkeypatch.setattr(
        "sase.ace.saved_queries.load_saved_queries",
        lambda: {"1": '"feature"'},
    )

    assert await app._try_startup_fallback_async() is True
    assert [cs.name for cs in app.changespecs] == ["feature_a"]
    assert app.query_string == '"feature"'
    assert app.restored_selection is True
    assert fake_query_corpus["compile"] == [specs]


def test_hide_counts_are_preserved_on_corpus_route(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    specs = [
        make_changespec(name="ready", status="Ready"),
        make_changespec(name="submitted", status="Submitted"),
        make_changespec(name="reverted", status="Reverted"),
        make_changespec(name="archived", status="Archived"),
    ]
    app = _FakeApp(
        specs,
        query='"anything"',
        hide_reverted=True,
        hide_submitted=True,
    )

    monkeypatch.setattr(
        "sase.core.query_corpus_facade.compile_query_corpus",
        lambda changespecs: QueryCorpus(
            source_list_id=id(changespecs),
            expected_length=len(changespecs),
            rust_handle=_FakeRustCorpus([cs.name for cs in changespecs]),
        ),
    )
    monkeypatch.setattr(
        "sase.core.query_corpus_facade.evaluate_query_many_with_corpus",
        lambda _query, corpus: [True] * len(corpus.rust_handle),
    )

    app._apply_changespecs(specs)

    assert [cs.name for cs in app.changespecs] == ["ready"]
    assert app._query_submitted_count == 1
    assert app._query_reverted_count == 2
    assert app._hidden_submitted_count == 1
    assert app._hidden_reverted_count == 2


def test_forced_stale_handle_fails_before_returning_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    specs = [make_changespec(name="feature_a")]
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
        app._filter_changespecs(specs)
