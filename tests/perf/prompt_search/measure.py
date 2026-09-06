"""Timing summaries and unicode-offset microbenchmarks for prompt search."""

from __future__ import annotations

import statistics
import time
from collections.abc import Callable, Iterable, Sequence
from typing import Any

from .corpus import _MULTILINGUAL, _fence, _insert_repo_paths

_PHASE_KEYS = (
    "fresh_process_ms",
    "worker_elapsed_ms",
    "imports_ms",
    "root_resolution_ms",
    "archive_loading_ms",
    "local_loading_ms",
    "dedup_ms",
    "matching_ms",
    "rendering_ms",
    "peak_memory_mb",
    "output_bytes",
)


def _percentile(sorted_values: Sequence[float], pct: float) -> float:
    if not sorted_values:
        return 0.0
    index = round(pct * (len(sorted_values) - 1))
    return sorted_values[max(0, min(len(sorted_values) - 1, index))]


def _summarize_values(values: Iterable[float]) -> dict[str, float]:
    ordered = sorted(values)
    if not ordered:
        return {"count": 0.0}
    return {
        "count": float(len(ordered)),
        "min": ordered[0],
        "median": statistics.median(ordered),
        "p95": _percentile(ordered, 0.95),
        "max": ordered[-1],
    }


def _summarize_samples(samples: list[dict[str, Any]]) -> dict[str, Any]:
    ok_samples = [
        sample
        for sample in samples
        if not sample.get("timed_out") and sample.get("worker_elapsed_ms") is not None
    ]
    phase_summaries = {
        key: _summarize_values(
            float(sample[key])
            for sample in ok_samples
            if isinstance(sample.get(key), (int, float))
        )
        for key in _PHASE_KEYS
    }
    cached_elapsed = [
        float(sample["fresh_process_ms"])
        for sample in ok_samples[1:]
        if isinstance(sample.get("fresh_process_ms"), (int, float))
    ]
    return {
        "runs": len(samples),
        "completed": len(ok_samples),
        "failures": len(samples) - len(ok_samples),
        "first_fresh_process_ms": (
            float(ok_samples[0]["fresh_process_ms"]) if ok_samples else None
        ),
        "cached_fresh_process_ms": _summarize_values(cached_elapsed),
        "phases": phase_summaries,
        "last_counts": ok_samples[-1].get("counts") if ok_samples else {},
    }


def _micro_text(blocks: int) -> tuple[str, list[tuple[int, int]]]:
    parts: list[str] = []
    ranges: list[tuple[int, int]] = []
    cursor = 0
    for index in range(blocks):
        prefix = f"before {index} {_MULTILINGUAL}\n"
        parts.append(prefix)
        cursor += len(prefix)
        fence = _fence(index, index % 7)
        start = cursor
        end = start + len(fence)
        ranges.append((start, start + 3))
        ranges.append((start + 3, start + 9))
        ranges.append((start + 10, end - 4))
        ranges.append((end - 4, end))
        ranges.append((start, end))
        parts.append(fence)
        cursor = end
    return "".join(parts), ranges


def _time_call(fn: Callable[[], object], *, runs: int) -> dict[str, float]:
    samples: list[float] = []
    for _ in range(runs):
        start = time.perf_counter()
        fn()
        samples.append((time.perf_counter() - start) * 1000.0)
    return _summarize_values(samples)


def _range_endpoints(ranges: Iterable[tuple[int, int]]) -> list[int]:
    endpoints: list[int] = []
    for start, end in ranges:
        endpoints.extend((start, end))
    return endpoints


def _naive_byte_to_character_map(text: str) -> dict[int, int]:
    mapping: dict[int, int] = {}
    cursor = 0
    for character_index, character in enumerate(text):
        for _ in character.encode("utf-8"):
            mapping[cursor] = character_index
            cursor += 1
    mapping[cursor] = len(text)
    return mapping


def _naive_convert_ranges(
    text: str,
    ranges: Sequence[tuple[int, int]],
) -> list[tuple[int, int]]:
    converted: list[tuple[int, int]] = []
    for start, end in ranges:
        mapping = _naive_byte_to_character_map(text)
        converted.append((mapping[start], mapping[end]))
    return converted


def _run_microbenchmark(
    *,
    block_counts: Sequence[int],
    runs: int,
    naive_max_blocks: int,
) -> list[dict[str, Any]]:
    _insert_repo_paths()
    from sase.xprompt._fenced_blocks import fenced_block_details
    from sase.xprompt._utf8_offsets import (
        byte_offsets_to_character_offsets,
        character_offsets_to_byte_offsets,
    )

    rows: list[dict[str, Any]] = []
    for blocks in block_counts:
        text, character_ranges = _micro_text(blocks)
        character_offsets = _range_endpoints(character_ranges)
        character_to_byte = character_offsets_to_byte_offsets(text, character_offsets)
        byte_ranges = [
            (character_to_byte[start], character_to_byte[end])
            for start, end in character_ranges
        ]
        byte_offsets = _range_endpoints(byte_ranges)

        sparse_summary = _time_call(
            lambda text=text, byte_offsets=byte_offsets: (
                byte_offsets_to_character_offsets(text, byte_offsets)
            ),
            runs=runs,
        )
        detail_summary = _time_call(
            lambda text=text: fenced_block_details(text),
            runs=runs,
        )
        naive_summary: dict[str, float] = {"count": 0.0}
        speedup = None
        if blocks <= naive_max_blocks:
            expected = _naive_convert_ranges(text, byte_ranges)
            actual_map = byte_offsets_to_character_offsets(text, byte_offsets)
            actual = [
                (actual_map[start], actual_map[end]) for start, end in byte_ranges
            ]
            if actual != expected:
                raise AssertionError(
                    "sparse offset conversion does not match naive map"
                )
            naive_summary = _time_call(
                lambda text=text, byte_ranges=byte_ranges: _naive_convert_ranges(
                    text,
                    byte_ranges,
                ),
                runs=max(1, min(runs, 3)),
            )
            sparse_median = sparse_summary.get("median", 0.0)
            if sparse_median > 0:
                speedup = naive_summary.get("median", 0.0) / sparse_median

        rows.append(
            {
                "blocks": blocks,
                "text_chars": len(text),
                "text_bytes": len(text.encode("utf-8")),
                "offsets": len(byte_offsets),
                "sparse_offsets_ms": sparse_summary,
                "fenced_block_details_ms": detail_summary,
                "naive_old_per_range_ms": naive_summary,
                "naive_vs_sparse_speedup": speedup,
            }
        )
    return rows


def _print_microbenchmark(rows: Sequence[dict[str, Any]]) -> None:
    if not rows:
        return
    print()
    print("# unicode offset microbenchmark")
    header = (
        f"{'blocks':>7} {'chars':>8} {'offsets':>8} "
        f"{'sparse med':>11} {'details med':>11} {'naive med':>10} {'speedup':>8}"
    )
    print(header)
    print("-" * len(header))
    for row in rows:
        sparse = row["sparse_offsets_ms"].get("median", 0.0)
        details = row["fenced_block_details_ms"].get("median", 0.0)
        naive = row["naive_old_per_range_ms"].get("median", 0.0)
        speedup = row["naive_vs_sparse_speedup"]
        speedup_text = "" if speedup is None else f"{speedup:>.1f}x"
        print(
            f"{row['blocks']:>7} {row['text_chars']:>8} {row['offsets']:>8} "
            f"{sparse:>11.3f} {details:>11.3f} {naive:>10.3f} "
            f"{speedup_text:>8}"
        )
