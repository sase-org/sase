"""Fresh-process worker that times one ``sase prompt search`` scenario."""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import resource
import sys
import time
from pathlib import Path

from .corpus import _insert_repo_paths


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


def main(argv: list[str] | None = None) -> int:
    args = _worker_parser().parse_args(argv)
    return _run_worker(args)


if __name__ == "__main__":
    raise SystemExit(main())
