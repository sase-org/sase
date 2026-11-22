"""SAVEALL regressions for Textual Strip self-cycle guards."""

from __future__ import annotations

import inspect
from collections import Counter

import pytest
from rich.segment import Segment
from textual.strip import Strip

from sase.ace.tui.util import textual_cycle_guards as guards
from tests.ace.tui._gc_cycles import collect_cyclic_garbage

_STRIP = "textual.strip.Strip"
_FIFO = "textual.cache.FIFOCache"
_LIST = "builtins.list"
_SEGMENT = "rich.segment.Segment"


def _wanted(counts: Counter[str]) -> dict[str, int]:
    return {name: int(counts.get(name, 0)) for name in (_STRIP, _FIFO, _LIST, _SEGMENT)}


def _drop_full_width_divide() -> None:
    strip = Strip([Segment("hello world")], 11)
    strip.divide([11])
    del strip


def _drop_full_width_crop_extend() -> None:
    strip = Strip([Segment("hello world")], 11)
    strip.crop_extend(0, 11, None)
    del strip


def test_install_is_idempotent_and_keeps_divide_signature() -> None:
    original_signature = inspect.signature(guards._UNPATCHED_DIVIDE)
    guards.install_textual_cycle_guards()
    guards.install_textual_cycle_guards()
    assert inspect.signature(Strip.divide) == original_signature
    assert inspect.signature(Strip.crop_extend) == inspect.signature(
        guards._UNPATCHED_CROP_EXTEND
    )


def test_divide_full_width_returns_fresh_self_list_and_does_not_cache() -> None:
    guards.install_textual_cycle_guards()
    strip = Strip([Segment("hello")], 5)
    first = strip.divide([5])
    second = strip.divide([5])
    assert list(first) == [strip]
    assert first[0] is strip
    assert list(second) == [strip]
    assert first is not second
    cache = getattr(strip, "_divide_cache", None)
    if cache is not None:
        assert cache.get((5,)) is None


def test_divide_other_cuts_still_delegate() -> None:
    guards.install_textual_cycle_guards()
    strip = Strip([Segment("hello world")], 11)
    parts = strip.divide([5, 11])
    assert len(parts) == 2
    assert parts[0] is not strip
    assert parts[0].cell_length == 5
    assert parts[1].cell_length == 6
    cache = getattr(strip, "_divide_cache", None)
    if cache is not None:
        cached = cache.get((5, 11))
        assert cached is not None
        assert list(cached) == list(parts)


def test_divide_full_width_leaves_no_cyclic_garbage() -> None:
    guards.install_textual_cycle_guards()
    observed = _wanted(collect_cyclic_garbage(_drop_full_width_divide, repeat=3))
    assert observed[_STRIP] == 0
    assert observed[_FIFO] == 0
    assert observed[_LIST] == 0
    assert observed[_SEGMENT] == 0


def test_crop_extend_full_width_leaves_no_cyclic_garbage() -> None:
    guards.install_textual_cycle_guards()
    strip = Strip([Segment("hello")], 5)
    result = strip.crop_extend(0, 5, None)
    assert result is strip
    cache = getattr(strip, "_crop_extend_cache", None)
    if cache is not None:
        assert cache.get((0, 5, None)) is None
    observed = _wanted(collect_cyclic_garbage(_drop_full_width_crop_extend, repeat=3))
    assert observed[_STRIP] == 0
    assert observed[_FIFO] == 0
    assert observed[_SEGMENT] == 0


def test_guard_is_noop_when_probe_finds_no_cycle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(guards, "_probe_strip_divide_self_cycle", lambda: False)
    monkeypatch.setattr(guards, "_probe_strip_crop_extend_self_cycle", lambda: False)
    monkeypatch.setattr(guards, "_DIVIDE_DECIDED", False)
    monkeypatch.setattr(guards, "_CROP_EXTEND_DECIDED", False)
    monkeypatch.setattr(Strip, "divide", guards._UNPATCHED_DIVIDE)
    monkeypatch.setattr(Strip, "crop_extend", guards._UNPATCHED_CROP_EXTEND)

    guards.install_textual_cycle_guards()

    assert Strip.divide is guards._UNPATCHED_DIVIDE
    assert Strip.crop_extend is guards._UNPATCHED_CROP_EXTEND


def test_unpatched_divide_still_creates_the_self_cycle() -> None:
    """The Textual bug remains on the captured original; the guard is needed."""

    def drop_unpatched() -> None:
        strip = Strip([Segment("hello world")], 11)
        guards._UNPATCHED_DIVIDE(strip, [11])
        del strip

    observed = _wanted(collect_cyclic_garbage(drop_unpatched, repeat=3))
    assert observed[_STRIP] >= 1
    assert observed[_FIFO] >= 1
    assert observed[_LIST] >= 1
