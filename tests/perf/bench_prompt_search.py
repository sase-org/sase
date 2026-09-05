"""Fresh-process benchmark for ``sase prompt search``.

Run the representative prompt-search corpus with:

    just bench-prompt-search

The default corpus is intentionally close to the measured shape from
``202609/prompt_search_performance.md``: roughly 5,000 archived prompts and
8,000 local prompt-history entries, with Unicode text, fenced code, long
tail-only matches, metadata-only hits, archive/local duplicates, and
artifact-heavy archive headers. Each search scenario runs in a fresh Python
process and captures renderer output so terminal throughput does not dominate
the result.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import json
import os
import resource
import statistics
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

pytestmark = pytest.mark.slow

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"

COMMON_QUERY = "promptbench-common"
RARE_TAIL_QUERY = "promptbench-tail-rare-7999"
NO_MATCH_QUERY = "promptbench-no-such-token"
METADATA_QUERY = "promptbench-meta-only"

DEFAULT_MONTH = "202609"
DEFAULT_ARCHIVE_COUNT = 5_000
DEFAULT_LOCAL_COUNT = 8_000
DEFAULT_DUPLICATE_COUNT = 200

_SCENARIO_QUERY_VALUES = {
    "common": COMMON_QUERY,
    "rare_tail": RARE_TAIL_QUERY,
    "no_match": NO_MATCH_QUERY,
    "metadata_only": METADATA_QUERY,
}
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

_MULTILINGUAL = (
    "cafe\u0301 resume\u0301 naive facade jalapeno "
    "東京 Καλημερα Здравствуйте مرحبا שלום नमस्ते 🙂"
)


@dataclass(frozen=True)
class _CorpusPaths:
    root: Path
    archive_root: Path
    sase_home: Path


@dataclass(frozen=True)
class _Scenario:
    source: str
    output_format: str
    query_name: str
    query: str
    limit: int

    @property
    def label(self) -> str:
        return f"{self.source}/{self.output_format}/{self.query_name}"

    def as_payload(self) -> dict[str, object]:
        return {
            "source": self.source,
            "format": self.output_format,
            "query": self.query_name,
            "limit": self.limit,
        }


def _insert_repo_paths() -> None:
    for path in (str(SRC_ROOT), str(REPO_ROOT)):
        if path not in sys.path:
            sys.path.insert(0, path)


def _timestamp(index: int) -> str:
    return (datetime(2026, 9, 1, 0, 0, 0) + timedelta(seconds=index)).strftime(
        "%y%m%d_%H%M%S"
    )


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _fence(index: int, fence_index: int) -> str:
    return (
        "```python\n"
        f"# synthetic fence {index}:{fence_index} {_MULTILINGUAL}\n"
        f"value_{index}_{fence_index} = '{COMMON_QUERY}:{index}:{fence_index}'\n"
        "```\n"
    )


def _body(
    *,
    index: int,
    source: str,
    include_common: bool = True,
    rare_tail: bool = False,
    metadata_ref: bool = False,
) -> str:
    head_parts = [f"Promptbench {source} prompt {index:05d}"]
    if include_common:
        head_parts.append(COMMON_QUERY)
    if metadata_ref:
        head_parts.append(f"@{METADATA_QUERY}")
    lines = [
        " ".join(head_parts),
        f"Review {_MULTILINGUAL} and inline `{COMMON_QUERY}-{source}-{index}`.",
        "Keep literal-zone handling represented without executing any prompt refs.",
    ]

    fence_count = 3 + (index % 4)
    if index % 257 == 0:
        fence_count += 8
    for fence_index in range(fence_count):
        lines.append(_fence(index, fence_index))

    if rare_tail:
        lines.append(("tail filler " + _MULTILINGUAL + " ") * 80 + RARE_TAIL_QUERY)
    return "\n".join(lines) + "\n"


def _archive_header(index: int) -> str:
    artifact_count = 12 if index % 101 == 0 else 1
    artifacts = "\n".join(
        "  - "
        f"[artifact-{index:05d}-{artifact_index:02d}.txt]"
        f"(../../artifacts/{DEFAULT_MONTH}/artifact-{index:05d}-{artifact_index:02d}.txt)"
        for artifact_index in range(artifact_count)
    )
    return (
        "- **PLAN:** "
        f"[{DEFAULT_MONTH}/prompt_search_performance.md]"
        "(https://example.invalid/plans/202609/prompt_search_performance.md)\n"
        "- **ARTIFACTS:**\n"
        f"{artifacts}\n"
    )


def _archive_document(index: int, body: str) -> str:
    tags = ["archive", f"bucket-{index % 17}"]
    if index % 499 == 0:
        tags.append(METADATA_QUERY)
    tag_lines = "\n".join(f"  - {tag}" for tag in tags)
    body_text = body.strip()
    return (
        "---\n"
        f"sha256: {_sha256(body_text)}\n"
        f"timestamp: {_timestamp(index)}\n"
        "prompt_tags:\n"
        f"{tag_lines}\n"
        "---\n"
        f"{_archive_header(index)}\n"
        f"{body}"
    )


def _seed_archive(
    archive_root: Path,
    *,
    archive_count: int,
) -> list[str]:
    archive_texts: list[str] = []
    prompts_dir = archive_root / "prompts" / DEFAULT_MONTH
    prompts_dir.mkdir(parents=True, exist_ok=True)
    for index in range(archive_count):
        body = _body(
            index=index,
            source="archive",
            rare_tail=index == archive_count - 1 and archive_count > 0,
            metadata_ref=index % 613 == 0,
        )
        archive_texts.append(body.strip())
        path = prompts_dir / f"prompt_{index:05d}.md"
        path.write_text(_archive_document(index, body), encoding="utf-8")

    return archive_texts


def _seed_local_history(
    sase_home: Path,
    *,
    archive_texts: Sequence[str],
    local_count: int,
    duplicate_count: int,
) -> None:
    _insert_repo_paths()
    from sase.history.prompt_store import PromptEntry, save_prompt_history

    previous_home = os.environ.get("SASE_HOME")
    os.environ["SASE_HOME"] = str(sase_home)
    try:
        entries: list[PromptEntry] = []
        duplicates = min(duplicate_count, len(archive_texts), local_count)
        for index in range(local_count):
            if index < duplicates:
                text = archive_texts[index]
            else:
                text = _body(
                    index=index,
                    source="local",
                    rare_tail=index == local_count - 1 and local_count > 0,
                    metadata_ref=index % 787 == 0,
                ).strip()
            ts = _timestamp(len(archive_texts) + index)
            entries.append(
                PromptEntry(
                    text=text,
                    timestamp=ts,
                    last_used=ts,
                    cancelled=index % 997 == 0,
                )
            )
        if not save_prompt_history(entries):
            raise RuntimeError("failed to seed prompt-history shards")
    finally:
        if previous_home is None:
            os.environ.pop("SASE_HOME", None)
        else:
            os.environ["SASE_HOME"] = previous_home


def _seed_corpus(
    root: Path,
    *,
    archive_count: int,
    local_count: int,
    duplicate_count: int,
) -> _CorpusPaths:
    archive_root = root / "archive"
    sase_home = root / "home" / ".sase"
    archive_texts = _seed_archive(
        archive_root,
        archive_count=archive_count,
    )
    _seed_local_history(
        sase_home,
        archive_texts=archive_texts,
        local_count=local_count,
        duplicate_count=duplicate_count,
    )
    return _CorpusPaths(root=root, archive_root=archive_root, sase_home=sase_home)


def _run_worker(args: argparse.Namespace) -> int:
    process_start = time.perf_counter()
    _insert_repo_paths()

    import_start = time.perf_counter()
    import sase.prompt.cli_search as cli_search
    import sase.prompt.search.sources as search_sources
    from sase.prompt.search.engine import search_prompts
    from sase.prompt.search.model import PromptSource

    imports_ms = (time.perf_counter() - import_start) * 1000.0

    archive_root = Path(args.archive_root)
    cli_search.resolve_prompt_archive_root = lambda: archive_root

    root_start = time.perf_counter()
    selected = cli_search._resolve_sources(args.source)
    resolved_archive_root = cli_search._resolve_archive_root(selected)
    root_resolution_ms = (time.perf_counter() - root_start) * 1000.0

    archive_hits = []
    local_hits = []
    archive_loading_ms = 0.0
    local_loading_ms = 0.0

    if PromptSource.ARCHIVE in selected and resolved_archive_root is not None:
        load_start = time.perf_counter()
        archive_hits = search_sources.load_archive_prompt_hits(resolved_archive_root)
        archive_loading_ms = (time.perf_counter() - load_start) * 1000.0

    if PromptSource.LOCAL in selected:
        load_start = time.perf_counter()
        local_hits = search_sources.load_local_prompt_hits()
        local_loading_ms = (time.perf_counter() - load_start) * 1000.0

    dedup_start = time.perf_counter()
    hits = search_sources._dedup_hits(archive_hits, local_hits)
    dedup_ms = (time.perf_counter() - dedup_start) * 1000.0

    match_start = time.perf_counter()
    result = search_prompts(
        args.query,
        hits,
        sources=selected,
        limit=args.limit,
    )
    matching_ms = (time.perf_counter() - match_start) * 1000.0

    render_start = time.perf_counter()
    with contextlib.redirect_stdout(io.StringIO()) as captured:
        if args.output_format == "compact":
            cli_search._render_compact(result, use_color=False)
        elif args.output_format == "json":
            cli_search._render_json(result)
        elif args.output_format == "full":
            cli_search._render_full(result, use_color=False)
        else:
            raise ValueError(f"unknown format: {args.output_format}")
    rendered = captured.getvalue()
    rendering_ms = (time.perf_counter() - render_start) * 1000.0

    payload = {
        "source": args.source,
        "format": args.output_format,
        "query": args.query_name,
        "limit": args.limit,
        "counts": {
            "archive_hits_loaded": len(archive_hits),
            "local_hits_loaded": len(local_hits),
            "combined_hits": len(hits),
            "matches_total": result.total,
            "matches_shown": result.count,
        },
        "output_bytes": len(rendered.encode("utf-8")),
        "fresh_process_ms": None,
        "worker_elapsed_ms": (time.perf_counter() - process_start) * 1000.0,
        "imports_ms": imports_ms,
        "root_resolution_ms": root_resolution_ms,
        "archive_loading_ms": archive_loading_ms,
        "local_loading_ms": local_loading_ms,
        "dedup_ms": dedup_ms,
        "matching_ms": matching_ms,
        "rendering_ms": rendering_ms,
        "peak_memory_mb": _peak_rss_mb(),
    }
    print(json.dumps(payload, sort_keys=True))
    return 0


def _peak_rss_mb() -> float:
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    # Linux reports kilobytes; macOS reports bytes. SASE's supported runtime
    # here is Linux, but keep the conversion explicit for local comparisons.
    if sys.platform == "darwin":
        return peak / 1_000_000.0
    return (peak * 1024.0) / 1_000_000.0


def _worker_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="prompt search benchmark worker")
    parser.add_argument("--archive-root", required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--format", dest="output_format", required=True)
    parser.add_argument("--query-name", required=True)
    parser.add_argument("--query", required=True)
    parser.add_argument("--limit", type=int, required=True)
    return parser


def _run_worker_process(
    corpus: _CorpusPaths,
    scenario: _Scenario,
    *,
    timeout: float,
) -> dict[str, Any]:
    env = os.environ.copy()
    env["SASE_HOME"] = str(corpus.sase_home)
    env["PYTHONPATH"] = (
        f"{SRC_ROOT}{os.pathsep}{REPO_ROOT}{os.pathsep}{env.get('PYTHONPATH', '')}"
    )
    env.pop("PYTEST_CURRENT_TEST", None)
    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--worker",
        "--archive-root",
        str(corpus.archive_root),
        "--source",
        scenario.source,
        "--format",
        scenario.output_format,
        "--query-name",
        scenario.query_name,
        "--query",
        scenario.query,
        "--limit",
        str(scenario.limit),
    ]
    start = time.perf_counter()
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            env=env,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        return {
            "scenario": scenario.as_payload(),
            "timed_out": True,
            "fresh_process_ms": (time.perf_counter() - start) * 1000.0,
            "timeout_seconds": timeout,
            "stdout": (exc.stdout or "")[-2_000:],
            "stderr": (exc.stderr or "")[-2_000:],
        }

    fresh_ms = (time.perf_counter() - start) * 1000.0
    if completed.returncode != 0:
        return {
            "scenario": scenario.as_payload(),
            "returncode": completed.returncode,
            "timed_out": False,
            "fresh_process_ms": fresh_ms,
            "stdout": completed.stdout[-2_000:],
            "stderr": completed.stderr[-2_000:],
        }

    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return {
            "scenario": scenario.as_payload(),
            "returncode": completed.returncode,
            "timed_out": False,
            "fresh_process_ms": fresh_ms,
            "stdout": completed.stdout[-2_000:],
            "stderr": completed.stderr[-2_000:],
            "error": "worker did not emit JSON",
        }
    payload["fresh_process_ms"] = fresh_ms
    payload["timed_out"] = False
    if completed.stderr:
        payload["stderr"] = completed.stderr[-2_000:]
    return payload


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


def _scenarios(
    *,
    sources: Sequence[str],
    formats: Sequence[str],
    queries: Sequence[str],
    limit: int,
) -> list[_Scenario]:
    scenarios: list[_Scenario] = []
    for source in sources:
        for output_format in formats:
            for query_name in queries:
                scenarios.append(
                    _Scenario(
                        source=source,
                        output_format=output_format,
                        query_name=query_name,
                        query=_SCENARIO_QUERY_VALUES[query_name],
                        limit=limit,
                    )
                )
    return scenarios


def _print_scenario_summary(report: dict[str, Any]) -> None:
    print()
    print("# prompt search benchmark")
    config = report["config"]
    print(
        "corpus "
        f"archive={config['archive_count']} local={config['local_count']} "
        f"duplicates={config['duplicate_count']} seed={config['seed']}"
    )
    header = (
        f"{'scenario':<28} {'ok':>5} {'fresh med':>10} {'cached med':>11} "
        f"{'load a':>9} {'load l':>9} {'match':>8} {'render':>8} {'total':>7}"
    )
    print(header)
    print("-" * len(header))
    for item in report["scenarios"]:
        summary = item["summary"]
        phases = summary["phases"]
        counts = summary["last_counts"]
        fresh = phases["fresh_process_ms"].get("median", 0.0)
        cached = summary["cached_fresh_process_ms"].get("median", 0.0)
        archive = phases["archive_loading_ms"].get("median", 0.0)
        local = phases["local_loading_ms"].get("median", 0.0)
        match = phases["matching_ms"].get("median", 0.0)
        render = phases["rendering_ms"].get("median", 0.0)
        print(
            f"{item['label']:<28} "
            f"{summary['completed']:>2}/{summary['runs']:<2} "
            f"{fresh:>10.1f} {cached:>11.1f} {archive:>9.1f} "
            f"{local:>9.1f} {match:>8.1f} {render:>8.1f} "
            f"{counts.get('matches_total', 0):>7}"
        )


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


def run_bench(
    *,
    archive_count: int = DEFAULT_ARCHIVE_COUNT,
    local_count: int = DEFAULT_LOCAL_COUNT,
    duplicate_count: int = DEFAULT_DUPLICATE_COUNT,
    runs: int = 3,
    timeout: float = 60.0,
    sources: Sequence[str] = ("all", "archive", "local"),
    formats: Sequence[str] = ("compact", "json", "full"),
    queries: Sequence[str] = ("common", "rare_tail", "no_match"),
    limit: int = 20,
    micro_blocks: Sequence[int] = (20, 80, 200),
    micro_runs: int = 5,
    micro_naive_max_blocks: int = 80,
    output: Path | None = None,
    keep_corpus: bool = False,
) -> dict[str, Any]:
    tempdir: tempfile.TemporaryDirectory[str] | None = None
    if keep_corpus:
        root = Path(
            tempfile.mkdtemp(prefix="sase-prompt-search-bench-", dir=None)
        ).resolve()
    else:
        tempdir = tempfile.TemporaryDirectory(prefix="sase-prompt-search-bench-")
        root = Path(tempdir.name).resolve()

    try:
        corpus = _seed_corpus(
            root,
            archive_count=archive_count,
            local_count=local_count,
            duplicate_count=duplicate_count,
        )
        scenario_reports: list[dict[str, Any]] = []
        for scenario in _scenarios(
            sources=sources,
            formats=formats,
            queries=queries,
            limit=limit,
        ):
            samples = [
                _run_worker_process(corpus, scenario, timeout=timeout)
                for _ in range(runs)
            ]
            scenario_reports.append(
                {
                    "label": scenario.label,
                    "scenario": scenario.as_payload(),
                    "samples": samples,
                    "summary": _summarize_samples(samples),
                }
            )

        microbenchmark = _run_microbenchmark(
            block_counts=micro_blocks,
            runs=micro_runs,
            naive_max_blocks=micro_naive_max_blocks,
        )
        report: dict[str, Any] = {
            "tool": "bench_prompt_search",
            "schema_version": 1,
            "config": {
                "archive_count": archive_count,
                "local_count": local_count,
                "duplicate_count": min(duplicate_count, archive_count, local_count),
                "seed": DEFAULT_MONTH,
                "runs": runs,
                "timeout_seconds": timeout,
                "sources": list(sources),
                "formats": list(formats),
                "queries": list(queries),
                "limit": limit,
                "corpus_root": str(root) if keep_corpus else None,
            },
            "scenarios": scenario_reports,
            "microbenchmark": microbenchmark,
        }
        _print_scenario_summary(report)
        _print_microbenchmark(microbenchmark)
        if output is not None:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(report, indent=2), encoding="utf-8")
            print()
            print(f"Wrote JSON report -> {output}")
        elif keep_corpus:
            print()
            print(f"Kept corpus -> {root}")
        return report
    finally:
        if tempdir is not None:
            tempdir.cleanup()


def _argparser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Benchmark prompt search.")
    parser.add_argument("--archive-count", type=int, default=DEFAULT_ARCHIVE_COUNT)
    parser.add_argument("--local-count", type=int, default=DEFAULT_LOCAL_COUNT)
    parser.add_argument("--duplicate-count", type=int, default=DEFAULT_DUPLICATE_COUNT)
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument(
        "--sources",
        nargs="+",
        choices=("all", "archive", "local"),
        default=["all", "archive", "local"],
    )
    parser.add_argument(
        "--formats",
        nargs="+",
        choices=("compact", "json", "full"),
        default=["compact", "json", "full"],
    )
    parser.add_argument(
        "--queries",
        nargs="+",
        choices=tuple(_SCENARIO_QUERY_VALUES),
        default=["common", "rare_tail", "no_match"],
    )
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--micro-blocks", nargs="+", type=int, default=[20, 80, 200])
    parser.add_argument("--micro-runs", type=int, default=5)
    parser.add_argument("--micro-naive-max-blocks", type=int, default=80)
    parser.add_argument("--keep-corpus", action="store_true")
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Write the full JSON report to this path.",
    )
    return parser


def test_bench_prompt_search_smoke(tmp_path: Path) -> None:
    report = run_bench(
        archive_count=4,
        local_count=6,
        duplicate_count=2,
        runs=1,
        timeout=30.0,
        sources=("all", "local"),
        formats=("compact",),
        queries=("common", "no_match"),
        micro_blocks=(2, 4),
        micro_runs=1,
        micro_naive_max_blocks=4,
        output=tmp_path / "bench.json",
    )

    assert (tmp_path / "bench.json").exists()
    assert len(report["scenarios"]) == 4
    assert all(item["summary"]["failures"] == 0 for item in report["scenarios"])
    assert report["microbenchmark"]


def main(argv: list[str] | None = None) -> int:
    raw_args = list(sys.argv[1:] if argv is None else argv)
    if raw_args[:1] == ["--worker"]:
        return _run_worker(_worker_parser().parse_args(raw_args[1:]))

    args = _argparser().parse_args(raw_args)
    run_bench(
        archive_count=args.archive_count,
        local_count=args.local_count,
        duplicate_count=args.duplicate_count,
        runs=args.runs,
        timeout=args.timeout,
        sources=tuple(args.sources),
        formats=tuple(args.formats),
        queries=tuple(args.queries),
        limit=args.limit,
        micro_blocks=tuple(args.micro_blocks),
        micro_runs=args.micro_runs,
        micro_naive_max_blocks=args.micro_naive_max_blocks,
        output=args.output,
        keep_corpus=args.keep_corpus,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
