"""Fresh-process benchmark for ``sase prompt search``.

The implementation lives in ``tests.perf.prompt_search``; this module keeps
the existing pytest and standalone-script interfaces.

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

import sys
from pathlib import Path

# Script invocation (`python tests/perf/bench_prompt_search.py`) puts this
# file's directory on ``sys.path``; the package imports need the repo root.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import pytest  # noqa: E402

from tests.perf.prompt_search.harness import (  # noqa: E402
    _argparser,
    run_bench,
)

pytestmark = pytest.mark.slow


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
    args = _argparser().parse_args(sys.argv[1:] if argv is None else argv)
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
    raise SystemExit(main())
