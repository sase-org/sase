"""Orchestration for the prompt-search performance benchmark."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .corpus import (
    COMMON_QUERY,
    DEFAULT_ARCHIVE_COUNT,
    DEFAULT_DUPLICATE_COUNT,
    DEFAULT_LOCAL_COUNT,
    DEFAULT_MONTH,
    METADATA_QUERY,
    NO_MATCH_QUERY,
    RARE_TAIL_QUERY,
    REPO_ROOT,
    SRC_ROOT,
    _CorpusPaths,
    _seed_corpus,
)
from .measure import (
    _print_microbenchmark,
    _run_microbenchmark,
    _summarize_samples,
)

_SCENARIO_QUERY_VALUES = {
    "common": COMMON_QUERY,
    "rare_tail": RARE_TAIL_QUERY,
    "no_match": NO_MATCH_QUERY,
    "metadata_only": METADATA_QUERY,
}


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
        "-m",
        "tests.perf.prompt_search.worker",
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
            cwd=str(REPO_ROOT),
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
