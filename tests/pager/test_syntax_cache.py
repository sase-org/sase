"""Tests for the bounded cross-document syntax result/styled-text caches."""

from __future__ import annotations

from rich.text import Text

from sase.pager._syntax_cache import (
    ResultCacheKey,
    StyledCacheKey,
    StyledTextCache,
    SyntaxResultCache,
    content_digest,
)
from sase.pager.syntax import SyntaxDisposition, SyntaxResult, SyntaxRole, SyntaxSpan


def _result(*, spans: int = 0) -> SyntaxResult:
    return SyntaxResult(
        language="python",
        disposition=SyntaxDisposition.HIGHLIGHTED if spans else SyntaxDisposition.PLAIN,
        source_length=100,
        spans=tuple(
            SyntaxSpan(index, index + 1, SyntaxRole.KEYWORD) for index in range(spans)
        ),
    )


def test_content_digest_is_stable_and_content_sensitive() -> None:
    assert content_digest("alpha") == content_digest("alpha")
    assert content_digest("alpha") != content_digest("beta")


def test_result_cache_hits_on_matching_key() -> None:
    cache = SyntaxResultCache()
    key = ResultCacheKey(digest="d1", language="python")
    result = _result(spans=2)

    cache.put(key, result)

    assert cache.get(key) is result
    assert cache.get(ResultCacheKey(digest="d1", language="rust")) is None


def test_result_cache_evicts_oldest_section_past_the_section_cap() -> None:
    cache = SyntaxResultCache(max_sections=2, max_spans=1_000_000)
    cache.put(ResultCacheKey(digest="a", language="python"), _result())
    cache.put(ResultCacheKey(digest="b", language="python"), _result())
    cache.put(ResultCacheKey(digest="c", language="python"), _result())

    assert cache.get(ResultCacheKey(digest="a", language="python")) is None
    assert cache.get(ResultCacheKey(digest="b", language="python")) is not None
    assert cache.get(ResultCacheKey(digest="c", language="python")) is not None
    assert len(cache) == 2


def test_result_cache_get_refreshes_lru_order() -> None:
    cache = SyntaxResultCache(max_sections=2, max_spans=1_000_000)
    key_a = ResultCacheKey(digest="a", language="python")
    key_b = ResultCacheKey(digest="b", language="python")
    cache.put(key_a, _result())
    cache.put(key_b, _result())

    cache.get(key_a)  # touch "a" so "b" becomes the oldest entry
    cache.put(ResultCacheKey(digest="c", language="python"), _result())

    assert cache.get(key_a) is not None
    assert cache.get(key_b) is None


def test_result_cache_evicts_past_the_aggregate_span_budget() -> None:
    cache = SyntaxResultCache(max_sections=100, max_spans=5)
    cache.put(ResultCacheKey(digest="a", language="python"), _result(spans=3))
    cache.put(ResultCacheKey(digest="b", language="python"), _result(spans=3))

    assert cache.total_spans <= 5
    assert cache.get(ResultCacheKey(digest="a", language="python")) is None
    assert cache.get(ResultCacheKey(digest="b", language="python")) is not None


def test_result_cache_replacing_a_key_updates_the_span_total() -> None:
    cache = SyntaxResultCache(max_sections=100, max_spans=1_000_000)
    key = ResultCacheKey(digest="a", language="python")
    cache.put(key, _result(spans=5))
    cache.put(key, _result(spans=1))

    assert cache.total_spans == 1


def test_styled_cache_hits_on_the_full_key_including_theme_and_producer() -> None:
    cache = StyledTextCache()
    key = StyledCacheKey(
        digest="d1", language="python", theme_signature="dark", producer_eligible=False
    )
    text = Text("styled")

    cache.put(key, text)

    assert cache.get(key) is text
    other_theme = StyledCacheKey(
        digest="d1", language="python", theme_signature="light", producer_eligible=False
    )
    assert cache.get(other_theme) is None


def test_styled_cache_evicts_oldest_past_the_section_cap() -> None:
    cache = StyledTextCache(max_sections=2)
    for digest in ("a", "b", "c"):
        cache.put(
            StyledCacheKey(
                digest=digest,
                language="python",
                theme_signature="dark",
                producer_eligible=False,
            ),
            Text(digest),
        )

    assert (
        cache.get(
            StyledCacheKey(
                digest="a",
                language="python",
                theme_signature="dark",
                producer_eligible=False,
            )
        )
        is None
    )
    assert len(cache) == 2


def test_styled_cache_clear_drops_every_entry() -> None:
    cache = StyledTextCache()
    key = StyledCacheKey(
        digest="d1", language="python", theme_signature="dark", producer_eligible=False
    )
    cache.put(key, Text("styled"))

    cache.clear()

    assert cache.get(key) is None
    assert len(cache) == 0
