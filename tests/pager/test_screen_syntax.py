"""Tests for off-thread pager syntax preparation, caching, and invalidation.

Mirrors the ``_loading_diff_badges`` pattern: a minimal fake host exercises
the mixin's scheduling/coalescing logic synchronously, and a handful of
``asyncio`` tests drive the real worker body with controlled barriers
instead of timing-based sleeps.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest
from rich.text import Text

from sase.pager import _screen_syntax as screen_syntax_mod
from sase.pager._labels import PagerLabelLayer, build_label_layer
from sase.pager._screen_syntax import MAX_DOCUMENT_SYNTAX_SPANS, PagerSyntaxMixin
from sase.pager.document import (
    PagerDocument,
    PagerOrigin,
    PagerSection,
    RawSourceSpec,
)


class _FakeStatic:
    def __init__(self) -> None:
        self.updates: list[Any] = []

    def update(self, content: Any) -> None:
        self.updates.append(content)


class _FakeSearch:
    def __init__(self, *, is_active: bool = False) -> None:
        self.is_active = is_active
        self.refresh_calls = 0

    def refresh_styled_base(self) -> None:
        self.refresh_calls += 1


class _FakeHost(PagerSyntaxMixin):
    def __init__(self, document: PagerDocument, *, width: int = 80) -> None:
        self.document = document
        self._body = None
        self._body_width = width
        self._label_layer: PagerLabelLayer | None = None
        self._label_pending_prefix = ""
        self._search = _FakeSearch()
        self._current_index = 0
        self._pager_body = _FakeStatic()
        self.subject_updates = 0
        self.scheduled: list[tuple[PagerDocument, int]] = []
        self.after_refresh_calls: list[Any] = []
        self._init_syntax_state()

    def _current_section_index(self) -> int:
        return self._current_index

    def _build_label_layer(self, width: int) -> PagerLabelLayer:
        return build_label_layer(self.document, width=width)

    def _current_section(self) -> PagerSection:
        return self.document.sections[self._current_index]

    def query_one(self, selector: str, _cls: Any) -> Any:
        assert selector == "#pager-body"
        return self._pager_body

    def _update_subject(self) -> None:
        self.subject_updates += 1

    def call_after_refresh(self, callback: Any) -> None:
        self.after_refresh_calls.append(callback)
        callback()

    def _spawn_syntax_preparation_task(
        self, document: PagerDocument, generation: int
    ) -> None:
        """Record scheduling without starting a task in narrow sync tests."""
        self.scheduled.append((document, generation))


def _section(
    identity: str,
    body: str,
    *,
    language: str | None = "python",
    eligible: bool = True,
) -> PagerSection:
    return PagerSection(
        identity=identity,
        title=identity,
        kind="file",
        body=body,
        raw_source=RawSourceSpec(language=language, eligible=eligible),
    )


def _plain_section(identity: str, body: str) -> PagerSection:
    return PagerSection(identity=identity, title=identity, kind="file", body=body)


def _document(*sections: PagerSection) -> PagerDocument:
    return PagerDocument(sections=sections, title="doc", origin=PagerOrigin.FILE)


# --- scheduling / coalescing -------------------------------------------------


def test_no_pending_work_does_not_schedule() -> None:
    host = _FakeHost(_document(_plain_section("a", "plain text\n")))

    host._schedule_syntax_preparation()

    assert host.scheduled == []
    assert host._syntax_pass_running is False


def test_pending_work_schedules_exactly_one_task() -> None:
    document = _document(_section("a", "print('hi')\n"))
    host = _FakeHost(document)

    host._schedule_syntax_preparation()

    assert host.scheduled == [(document, 0)]
    assert host._syntax_pass_running is True


def test_scheduling_while_running_sets_restart_instead_of_a_second_task() -> None:
    document = _document(_section("a", "print('hi')\n"))
    host = _FakeHost(document)
    host._syntax_pass_running = True

    host._schedule_syntax_preparation()

    assert host.scheduled == []
    assert host._syntax_restart_requested is True


def test_document_has_pending_syntax_work_ignores_attempted_sections() -> None:
    document = _document(_section("a", "print('hi')\n"))
    host = _FakeHost(document)
    assert host._document_has_pending_syntax_work() is True

    host._syntax_attempted.add("a")

    assert host._document_has_pending_syntax_work() is False


def test_syntax_prepare_order_puts_the_current_section_first() -> None:
    document = _document(
        _section("a", "one\n"), _section("b", "two\n"), _section("c", "three\n")
    )
    host = _FakeHost(document)
    host._current_index = 2

    assert host._syntax_prepare_order() == [2, 0, 1]


def test_reset_for_new_document_bumps_generation_and_drops_per_document_state() -> None:
    document = _document(_section("a", "print('hi')\n"))
    host = _FakeHost(document)
    host._syntax_attempted.add("a")
    host._syntax_document_span_budget_used = 5

    host._reset_syntax_for_new_document()

    assert host._syntax_generation == 1
    assert host._syntax_attempted == set()
    assert host._syntax_prepared == {}
    assert host._syntax_document_span_budget_used == 0


# --- _prepare_one_section (async worker body) --------------------------------


async def test_prepare_one_section_highlights_an_eligible_section() -> None:
    document = _document(_section("a", "if True:\n    pass\n"))
    host = _FakeHost(document)
    section = document.sections[0]

    changed = await host._prepare_one_section(document, 0, section)

    assert changed is True
    assert "a" in host._syntax_attempted
    prepared = host._syntax_prepared["a"]
    assert prepared.styled_text.plain == section.plain_text
    assert prepared.hint == "py"


async def test_prepare_one_section_skips_a_section_without_raw_source() -> None:
    document = _document(_plain_section("a", "plain text\n"))
    host = _FakeHost(document)
    section = document.sections[0]

    changed = await host._prepare_one_section(document, 0, section)

    assert changed is False
    assert "a" in host._syntax_attempted
    assert "a" not in host._syntax_prepared
    assert len(host._syntax_result_cache) == 0


async def test_prepare_one_section_skips_a_plain_alias_without_hashing() -> None:
    document = _document(_section("a", "plain text\n", language="text"))
    host = _FakeHost(document)
    section = document.sections[0]

    changed = await host._prepare_one_section(document, 0, section)

    assert changed is False
    assert "a" in host._syntax_attempted
    assert len(host._syntax_result_cache) == 0


async def test_prepare_one_section_respects_the_document_span_budget() -> None:
    document = _document(_section("a", "if True:\n    pass\n"))
    host = _FakeHost(document)
    host._syntax_document_span_budget_used = MAX_DOCUMENT_SYNTAX_SPANS
    section = document.sections[0]

    changed = await host._prepare_one_section(document, 0, section)

    assert changed is False
    assert "a" in host._syntax_attempted
    assert "a" not in host._syntax_prepared


async def test_prepare_one_section_reuses_the_cached_result_for_identical_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = "if True:\n    pass\n"
    document = _document(_section("a", body), _section("b", body))
    host = _FakeHost(document)

    calls = []
    real_lex_and_style = screen_syntax_mod._lex_and_style

    def _counting(*args: Any, **kwargs: Any) -> Any:
        calls.append(1)
        return real_lex_and_style(*args, **kwargs)

    monkeypatch.setattr(screen_syntax_mod, "_lex_and_style", _counting)

    await host._prepare_one_section(document, 0, document.sections[0])
    await host._prepare_one_section(document, 0, document.sections[1])

    assert len(calls) == 1
    assert host._syntax_prepared["a"].styled_text.plain == body
    assert host._syntax_prepared["b"].styled_text.plain == body


async def test_prepare_one_section_reuses_cache_across_documents(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The cross-document cache is exactly what makes back/forward cheap."""
    body = "if True:\n    pass\n"
    first_document = _document(_section("a", body))
    host = _FakeHost(first_document)

    calls = []
    real_lex_and_style = screen_syntax_mod._lex_and_style

    def _counting(*args: Any, **kwargs: Any) -> Any:
        calls.append(1)
        return real_lex_and_style(*args, **kwargs)

    monkeypatch.setattr(screen_syntax_mod, "_lex_and_style", _counting)
    await host._prepare_one_section(first_document, 0, first_document.sections[0])
    assert len(calls) == 1

    second_document = _document(_section("a-again", body))
    host.document = second_document
    host._reset_syntax_for_new_document()

    await host._prepare_one_section(
        second_document, host._syntax_generation, second_document.sections[0]
    )

    assert len(calls) == 1  # still one -- the second visit hit the result cache
    assert host._syntax_prepared["a-again"].styled_text.plain == body


async def test_prepare_one_section_discards_a_stale_completion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A completion for a document the user already left must not publish."""
    document = _document(_section("a", "if True:\n    pass\n"))
    host = _FakeHost(document)
    section = document.sections[0]

    entered = asyncio.Event()
    release = asyncio.Event()
    real_lex_and_style = screen_syntax_mod._lex_and_style

    async def _slow_to_thread(func: Any, *args: Any) -> Any:
        if func is real_lex_and_style:
            entered.set()
            await release.wait()
        return func(*args)

    monkeypatch.setattr(screen_syntax_mod.asyncio, "to_thread", _slow_to_thread)

    task = asyncio.create_task(host._prepare_one_section(document, 0, section))
    await entered.wait()
    host._syntax_generation += 1  # simulate navigating away mid-prepare
    release.set()
    changed = await task

    assert changed is False
    assert "a" not in host._syntax_prepared


# --- theme invalidation -------------------------------------------------------


def _theme(name: str) -> Any:
    return SimpleNamespace(
        foreground=None,
        background=None,
        primary=None,
        secondary=None,
        accent=name,
        success=None,
        warning=None,
        error=None,
    )


async def test_theme_change_clears_styled_cache_and_reschedules() -> None:
    document = _document(_section("a", "if True:\n    pass\n"))
    host = _FakeHost(document)
    host.app = SimpleNamespace(current_theme=_theme("#010101"))
    await host._prepare_one_section(document, 0, document.sections[0])
    assert "a" in host._syntax_prepared
    assert len(host._syntax_styled_cache) == 1

    host.app = SimpleNamespace(current_theme=_theme("#020202"))
    host._on_app_theme_changed()

    assert host._syntax_prepared == {}
    assert host._syntax_attempted == set()
    assert len(host._syntax_styled_cache) == 0
    assert host.scheduled  # rescheduled via call_after_refresh
    # the lexed spans survive -- only the styled text needs recomputation.
    assert len(host._syntax_result_cache) == 1


def test_theme_change_is_a_noop_when_the_signature_is_unchanged() -> None:
    document = _document(_section("a", "if True:\n    pass\n"))
    host = _FakeHost(document)
    host.app = SimpleNamespace(current_theme=_theme("#010101"))
    host._on_app_theme_changed()
    first_palette = host._syntax_palette

    host._on_app_theme_changed()

    assert host._syntax_palette is first_palette
    assert len(host.scheduled) == 1  # only the initial real theme change rescheduled


# --- full worker: ordering, batching, staleness -------------------------------


async def test_run_syntax_preparation_processes_current_section_first_and_batches() -> (
    None
):
    document = _document(
        _section("a", "if True:\n    pass\n"),
        _section("b", "if False:\n    pass\n"),
        _section("c", "if None:\n    pass\n"),
    )
    host = _FakeHost(document)
    host._current_index = 1  # "b" is on screen
    order_seen: list[str] = []
    real_prepare = host._prepare_one_section

    async def _tracking(doc: PagerDocument, generation: int, section: PagerSection):
        order_seen.append(section.identity)
        return await real_prepare(doc, generation, section)

    host._prepare_one_section = _tracking  # type: ignore[method-assign]

    await host._run_syntax_preparation(document, 0)

    assert order_seen[0] == "b"
    assert set(order_seen) == {"a", "b", "c"}
    # one publish after the (current) first section, one more at the end.
    assert len(host._pager_body.updates) == 2
    assert host.subject_updates == 2


async def test_run_syntax_preparation_repaints_the_search_overlay_when_active() -> None:
    document = _document(_section("a", "if True:\n    pass\n"))
    host = _FakeHost(document)
    host._search = _FakeSearch(is_active=True)

    await host._run_syntax_preparation(document, 0)

    assert host._search.refresh_calls >= 1
    assert host._pager_body.updates == []  # overlay repainted, not the plain body


async def test_run_syntax_preparation_reorders_on_a_restart_request() -> None:
    document = _document(
        _section("a", "if True:\n    pass\n"),
        _section("b", "if False:\n    pass\n"),
    )
    host = _FakeHost(document)
    seen: list[str] = []
    real_prepare = host._prepare_one_section
    first_call = True

    async def _tracking(doc: PagerDocument, generation: int, section: PagerSection):
        nonlocal first_call
        seen.append(section.identity)
        if first_call:
            first_call = False
            host._current_index = 1
            host._syntax_restart_requested = True
        return await real_prepare(doc, generation, section)

    host._prepare_one_section = _tracking  # type: ignore[method-assign]

    await host._run_syntax_preparation(document, 0)

    # "a" runs once (current at start), then the restart reorders around the
    # new current section "b" -- "a" is already attempted, so only "b" reruns.
    assert seen == ["a", "b"]


async def test_run_syntax_preparation_finally_reschedules_a_pending_restart() -> None:
    """A restart requested too late for the loop to consume it inline still
    gets a fresh ``_schedule_syntax_preparation`` call from ``finally``,
    regardless of whether that call finds further work to do (covered
    separately by the scheduling tests above)."""
    document = _document(_section("a", "if True:\n    pass\n"))
    host = _FakeHost(document)
    real_prepare = host._prepare_one_section

    async def _request_restart_after(
        doc: PagerDocument, generation: int, section: PagerSection
    ):
        result = await real_prepare(doc, generation, section)
        host._syntax_restart_requested = True
        return result

    host._prepare_one_section = _request_restart_after  # type: ignore[method-assign]
    reschedule_calls: list[int] = []
    real_schedule = host._schedule_syntax_preparation

    def _spy() -> None:
        reschedule_calls.append(1)
        real_schedule()

    host._schedule_syntax_preparation = _spy  # type: ignore[method-assign]

    await host._run_syntax_preparation(document, 0)

    assert host._syntax_pass_running is False
    assert reschedule_calls == [1]


# --- helper accessors ----------------------------------------------------


def test_prepared_section_texts_and_current_hint_reflect_prepared_state() -> None:
    document = _document(_section("a", "one\n"), _section("b", "two\n"))
    host = _FakeHost(document)

    assert host._prepared_section_texts() == {}
    assert host._current_syntax_hint() is None

    host._syntax_prepared["b"] = screen_syntax_mod._PreparedSection(
        styled_text=Text("two\n"), hint="py"
    )

    assert list(host._prepared_section_texts()) == [1]
    host._current_index = 1
    assert host._current_syntax_hint() == "py"
    host._current_index = 0
    assert host._current_syntax_hint() is None
