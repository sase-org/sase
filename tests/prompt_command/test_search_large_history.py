"""Large-history output bounds for ``sase prompt search``.

The local prompt history can hold tens of thousands of entries, so every
``search`` format must stay bounded under the default limit and never dump the
whole store. These tests seed a corpus far larger than the default limit (plus a
handful of very large pastes with sentinels buried past any snippet cutoff) and
assert that:

- ``compact`` shows at most the default limit, never echoes a full huge body,
  and reports the true (large) totals;
- ``json`` emits exactly the limit's worth of ``results`` while ``total`` /
  ``counts`` stay accurate;
- ``full`` renders exactly the limit's worth of hits (divider-separated) and
  reports the true totals.

The shared archive hits also confirm that canonical hits still group first and that
per-source counts stay correct even when the local store dwarfs them.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from sase.history.prompt_store import PromptEntry
from sase.prompt.cli_search import handle_prompt_search

from ._helpers import _entry, _prompt_id, _seed

# A corpus far larger than the default limit, so an unbounded format would be
# obviously wrong. A few very large pastes hide a unique sentinel near their tail
# (well past any snippet cutoff) and carry the most recent local timestamps, so
# they land inside the default window — proving ``compact`` keeps them bounded
# rather than excluding them.
_ARCHIVE_COUNT = 2
_BULK_COUNT = 1500
_HUGE_COUNT = 3
_HUGE_CHARS = 20_000

_DEFAULT_LIMIT = 20
_QUERY = "auth"

# Totals the seeded corpus must report.
_LOCAL_TOTAL = _BULK_COUNT + _HUGE_COUNT
_GRAND_TOTAL = _ARCHIVE_COUNT + _LOCAL_TOTAL


@dataclass(frozen=True)
class _Corpus:
    """Sentinels buried in the huge pastes plus stable ids for boundary checks."""

    sentinels: tuple[str, ...]
    newest_bulk_id: str
    oldest_bulk_id: str


def _ns(query: str, **overrides: object) -> argparse.Namespace:
    """Build a search Namespace with the parser defaults, overridable per test."""
    base: dict[str, object] = {
        "query": query,
        "after": None,
        "before": None,
        "color": "never",
        "format": "compact",
        "limit": _DEFAULT_LIMIT,
        "source": "all",
        "tag": None,
        "cancelled": False,
    }
    base.update(overrides)
    return argparse.Namespace(**base)


@pytest.fixture
def large_corpus(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, history_file: Path
) -> _Corpus:
    """Seed a large local history plus a few archive hits, all matching ``auth``.

    Runs from an isolated archive root so discovery is scoped to the temp tree.
    Every entry contains the query term, so the match count equals the whole
    corpus and any unbounded output would be unmistakable.
    """
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "sase.prompt.cli_search.resolve_prompt_archive_root", lambda: tmp_path
    )

    for index in range(_ARCHIVE_COUNT):
        path = tmp_path / "prompts" / "202604" / f"auth_archive_{index}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"rotate auth tokens nightly {index}\n", encoding="utf-8")

    entries: list[PromptEntry] = [
        _entry(f"auth bulk prompt number {i}", f"260101_{i:06d}")
        for i in range(_BULK_COUNT)
    ]

    sentinels: list[str] = []
    for j in range(_HUGE_COUNT):
        sentinel = f"SECRET_TAIL_{j}_END"
        sentinels.append(sentinel)
        # Innocuous head with the query, a huge body, the secret buried at the
        # tail, and the most recent timestamp so it lands in the default window.
        text = f"auth huge paste {j} " + ("x" * _HUGE_CHARS) + f" {sentinel}"
        entries.append(_entry(text, f"260201_00000{j}"))

    _seed(*entries)
    return _Corpus(
        sentinels=tuple(sentinels),
        newest_bulk_id=_prompt_id(f"auth bulk prompt number {_BULK_COUNT - 1}"),
        oldest_bulk_id=_prompt_id("auth bulk prompt number 0"),
    )


def test_compact_stays_bounded_and_hides_full_text(
    large_corpus: _Corpus,
    capsys: pytest.CaptureFixture[str],
) -> None:
    handle_prompt_search(_ns(_QUERY))
    out = capsys.readouterr().out

    # The footer reports the true (large) totals and flags the truncation.
    assert (
        f"{_GRAND_TOTAL} matches ({_ARCHIVE_COUNT} archive · {_LOCAL_TOTAL} local)"
        in out
    )
    assert f"showing {_DEFAULT_LIMIT}" in out

    # The archive still groups first even though local history dwarfs it.
    assert f"── Archived prompts ({_ARCHIVE_COUNT}) ──" in out
    assert out.index("Archived prompts") < out.index("Local history")

    # The newest local prompt is shown; the oldest (last-ranked) is not — proof
    # the default window is bounded rather than dumping every match.
    assert large_corpus.newest_bulk_id in out
    assert large_corpus.oldest_bulk_id not in out

    # No buried sentinel and no long run of a huge body leaks into the snippets.
    for sentinel in large_corpus.sentinels:
        assert sentinel not in out, f"leaked full prompt body ({sentinel})"
    assert "x" * 200 not in out


def test_json_results_are_capped_with_accurate_totals(
    large_corpus: _Corpus,
    capsys: pytest.CaptureFixture[str],
) -> None:
    handle_prompt_search(_ns(_QUERY, format="json"))
    payload = json.loads(capsys.readouterr().out)

    # Exactly the default limit's worth of results — never the whole store.
    assert payload["count"] == _DEFAULT_LIMIT
    assert len(payload["results"]) == _DEFAULT_LIMIT
    # Totals and per-source counts describe the full pre-limit match set.
    assert payload["total"] == _GRAND_TOTAL
    assert payload["counts"] == {
        "archive": _ARCHIVE_COUNT,
        "local": _LOCAL_TOTAL,
    }

    # The oldest (last-ranked) prompt is beyond the cap and absent from results.
    shown_ids = {result["id"] for result in payload["results"]}
    assert large_corpus.oldest_bulk_id not in shown_ids


def test_full_renders_only_the_limit_with_accurate_totals(
    large_corpus: _Corpus,
    capsys: pytest.CaptureFixture[str],
) -> None:
    handle_prompt_search(_ns(_QUERY, format="full"))
    out = capsys.readouterr().out

    # The footer still reports the true totals and the truncation.
    assert (
        f"{_GRAND_TOTAL} matches ({_ARCHIVE_COUNT} archive · {_LOCAL_TOTAL} local)"
        in out
    )
    assert f"showing {_DEFAULT_LIMIT}" in out

    # Dividers separate consecutive hits, so exactly limit-1 of them appear:
    # the full format renders the limit's worth of hits, not the whole store.
    assert out.count("─" * 72) == _DEFAULT_LIMIT - 1

    # The last-ranked prompt is beyond the cap and never rendered.
    assert large_corpus.oldest_bulk_id not in out
