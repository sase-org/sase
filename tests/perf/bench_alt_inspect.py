"""Slow benchmark: ``alt_inspect.tokenize`` on an alternation-heavy prompt.

Covers the phase requirement that the binding-backed ``tokenize`` run at or
below today's pure-Python implementation, well under the 16 ms keystroke
budget, on an ~80 KB alternation-heavy prompt. Marked ``slow`` so it does not
run in ``just test``. Run via::

    pytest -m slow tests/perf/bench_alt_inspect.py
    python -m tests.perf.bench_alt_inspect --output baseline.json
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.slow

# p95 ceiling (ms) for one cache-miss ``tokenize`` over the ~80 KB fixture.
# The pure-Python implementation measured p95 26.64 ms on this host before the
# binding adapter landed; the adapter measured p95 15.63 ms on the same
# fixture (median 12.62 ms vs 26.38 ms before, ~2.4x faster). The ceiling pins
# the "at or below today's implementation" requirement; the median assertion
# below holds the 16 ms keystroke budget.
TOKENIZE_P95_CEILING_MS = 26.0
TOKENIZE_MEDIAN_CEILING_MS = 16.0

_CHUNKS = (
    "Review the widget %{quickly | carefully} for regressions. ",
    "Run foo%{bar | baz}qux with %{a | b | c} flags set. ",
    "Nested %{sase-%{core | github} | chezmoi} prompt follows. ",
    "Quote the note %{don't | do} that again, please. ",
    "Value %effort:%{medium | high} applies to this launch. ",
    "Adjacent %{one | two}%{three | four} groups expand together. ",
    "Literal code `%{not | an} alt` stays unhighlighted here. ",
)


def build_fixture(target_bytes: int = 80 * 1024) -> str:
    """Return a deterministic ~*target_bytes* alternation-heavy prompt."""
    parts: list[str] = []
    size = 0
    index = 0
    while size < target_bytes:
        chunk = _CHUNKS[index % len(_CHUNKS)]
        parts.append(chunk)
        size += len(chunk.encode("utf-8"))
        index += 1
    return "".join(parts)


def _percentile(sorted_ms: list[float], pct: float) -> float:
    if not sorted_ms:
        return 0.0
    rank = min(len(sorted_ms) - 1, int(pct * len(sorted_ms)))
    return sorted_ms[rank]


def measure_tokenize_ms(text: str, *, runs: int, warmup: int) -> list[float]:
    """Per-call ``tokenize`` milliseconds on cache-miss text.

    Each keystroke produces a new text, so the budget path is a cache miss:
    the memo cache is cleared before every sample.
    """
    from sase.xprompt import alt_inspect

    cache = getattr(alt_inspect, "_cached_records", None)

    def _reset() -> None:
        if cache is not None:
            cache.cache_clear()

    for _ in range(warmup):
        _reset()
        alt_inspect.tokenize(text)
    samples: list[float] = []
    for _ in range(runs):
        _reset()
        start = time.perf_counter()
        spans = alt_inspect.tokenize(text)
        samples.append((time.perf_counter() - start) * 1000.0)
        assert spans, "fixture must produce alt spans"
    return sorted(samples)


def test_alt_tokenize_p95_within_budget() -> None:
    """Binding-backed ``tokenize`` stays within the recorded ceilings."""
    text = build_fixture()
    assert len(text.encode("utf-8")) >= 80 * 1024
    samples = measure_tokenize_ms(text, runs=31, warmup=5)
    p95 = _percentile(samples, 0.95)
    median = statistics.median(samples)
    assert p95 <= TOKENIZE_P95_CEILING_MS, (
        f"tokenize p95 {p95:.2f} ms exceeds ceiling {TOKENIZE_P95_CEILING_MS:.2f} ms"
    )
    assert median <= TOKENIZE_MEDIAN_CEILING_MS, (
        f"tokenize median {median:.2f} ms exceeds keystroke budget "
        f"{TOKENIZE_MEDIAN_CEILING_MS:.2f} ms"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--runs", type=int, default=21)
    parser.add_argument("--warmup", type=int, default=3)
    args = parser.parse_args(argv)
    text = build_fixture()
    samples = measure_tokenize_ms(text, runs=args.runs, warmup=args.warmup)
    report = {
        "bytes": len(text.encode("utf-8")),
        "runs": args.runs,
        "min_ms": samples[0],
        "median_ms": statistics.median(samples),
        "p95_ms": _percentile(samples, 0.95),
        "max_ms": samples[-1],
    }
    print(json.dumps(report, indent=2))
    if args.output is not None:
        args.output.write_text(json.dumps(report, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
