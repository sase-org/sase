"""Benchmark Git query-op parsers ahead of a possible Rust port.

Phase 5A (sase-1a.1) of
``sdd/plans/202604/rust_backend_phase5_git_query_ops.md``. Phase 5 considers
moving the deterministic parsing/normalization helpers used by
``GitQueryOpsMixin`` behind the Rust-backed ``sase.core`` facade. Before
landing any seam, this benchmark separates parse cost from subprocess
cost so the go/no-go decision is grounded in numbers rather than
intuition.

Workloads
---------

- ``synthetic_*`` — generated NUL-delimited streams of increasing size
  (small / medium / large) for ``parse_git_name_status_z``. The small
  workload mirrors the kind of diff a typical PR produces (~50 entries);
  the large workload stretches the parser past the noise floor (~10 000
  entries with rename/copy mixed in).
- ``end_to_end_*`` — real ``git diff --name-status -z`` invocations on a
  temporary repo with added / modified / deleted / renamed files. The
  goal is to compare in-process parse cost against the dominant
  subprocess fork+exec+diff cost.
- The smaller normalizer scenarios (``parse_git_branch_name``,
  ``derive_git_workspace_name``, ``parse_git_conflicted_files``,
  ``parse_git_local_changes``) all run on string inputs and are timed at
  realistic cardinalities to confirm they stay in microsecond range.

Marked ``slow`` so it does not run in ``just test``. Run via::

    just bench-git-query-ops
    just bench-git-query-ops --runs 500 --large 20000

Or directly::

    pytest -s -m slow tests/perf/bench_git_query_ops.py
"""

from __future__ import annotations

import argparse
import json
import platform
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

import pytest

from sase.core.git_query_facade import (
    derive_git_workspace_name,
    parse_git_branch_name,
    parse_git_conflicted_files,
    parse_git_local_changes,
    parse_git_name_status_z,
)

pytestmark = pytest.mark.slow

REPO_ROOT = Path(__file__).resolve().parents[2]
_GIT_AVAILABLE = shutil.which("git") is not None


# --- helpers ----------------------------------------------------------------


def _percentile(sorted_vals: list[float], pct: float) -> float:
    if not sorted_vals:
        return 0.0
    n = len(sorted_vals)
    idx = max(0, min(n - 1, int(round(pct * (n - 1)))))
    return sorted_vals[idx]


def _summarize_us(values: Iterable[float]) -> dict[str, float]:
    vs = sorted(values)
    if not vs:
        return {"count": 0.0}
    return {
        "count": float(len(vs)),
        "min_us": vs[0] * 1_000_000.0,
        "median_us": statistics.median(vs) * 1_000_000.0,
        "p95_us": _percentile(vs, 0.95) * 1_000_000.0,
        "max_us": vs[-1] * 1_000_000.0,
    }


def _time_calls(fn: Callable[[], Any], *, runs: int, warmup: int) -> dict[str, float]:
    for _ in range(warmup):
        fn()
    samples: list[float] = []
    for _ in range(runs):
        start = time.perf_counter()
        fn()
        samples.append(time.perf_counter() - start)
    return _summarize_us(samples)


# --- synthetic stream builders ----------------------------------------------


def _build_name_status_stream(
    *,
    n_simple: int,
    n_rename: int,
) -> str:
    """Build a synthetic ``git diff --name-status -z`` stdout stream.

    Statuses cycle through ``A``, ``M``, ``D``, ``T`` for simple entries.
    Renames use ``R100`` with paired old/new paths. The stream ends with
    a trailing NUL, matching git's actual emission.
    """
    parts: list[str] = []
    cycle = ("A", "M", "D", "T")
    for i in range(n_simple):
        parts.append(cycle[i % 4])
        parts.append(f"src/pkg{i // 100}/file_{i}.py")
    for i in range(n_rename):
        parts.append("R100")
        parts.append(f"old/path_{i}.py")
        parts.append(f"new/path_{i}.py")
    # git emits a NUL after every field, including the last.
    return "\0".join(parts) + "\0"


# --- direct parser scenarios ------------------------------------------------


def _measure_name_status_parser(
    *,
    label: str,
    stream: str,
    runs: int,
    warmup: int,
) -> dict[str, Any]:
    def s_parse() -> int:
        return len(parse_git_name_status_z(stream))

    return {
        "label": label,
        "size_bytes": len(stream.encode("utf-8")),
        "runs": runs,
        "warmup": warmup,
        "scenarios": {
            "parse_git_name_status_z": _time_calls(s_parse, runs=runs, warmup=warmup),
        },
    }


def _measure_normalizers(
    *,
    runs: int,
    warmup: int,
) -> dict[str, Any]:
    """Time the small normalizers through the ``sase.core`` facade.

    Phase 5E routes ``GitQueryOpsMixin`` through ``sase.core.git_query_facade``.
    The benchmark calls the same public facade entry points so the numbers
    reflect the production direct-Rust call path.
    """
    branch_inputs = ["main\n", "feature/big-rewrite\n", "HEAD\n", "\n"]
    workspace_inputs: list[tuple[str | None, str | None]] = [
        ("git@github.com:org/repo.git", "/home/u/repo"),
        ("https://github.com/org/repo", "/home/u/repo"),
        (None, "/home/u/some-checkout"),
        (None, None),
        ("/srv/git/bare/widget.git", None),
    ]
    # 50-entry conflicted output is realistic for a contentious rebase.
    conflicted_input = "\n".join(f"src/pkg/file_{i}.py" for i in range(50)) + "\n"
    # status --porcelain output (~150 dirty entries).
    porcelain_input = "\n".join(f" M src/pkg/file_{i}.py" for i in range(150)) + "\n"

    def s_parse_branch() -> int:
        return sum(1 for x in branch_inputs if parse_git_branch_name(x) is not None)

    def s_derive_workspace() -> int:
        return sum(1 for r, p in workspace_inputs if derive_git_workspace_name(r, p))

    def s_parse_conflicted() -> int:
        return len(parse_git_conflicted_files(conflicted_input))

    def s_parse_local_changes() -> int:
        # Run both empty and dirty paths.
        return int(parse_git_local_changes(porcelain_input) is not None) + int(
            parse_git_local_changes("   \n") is not None
        )

    return {
        "label": "normalizers",
        "runs": runs,
        "warmup": warmup,
        "scenarios": {
            "parse_git_branch_name_x4": _time_calls(
                s_parse_branch, runs=runs, warmup=warmup
            ),
            "derive_git_workspace_name_x5": _time_calls(
                s_derive_workspace, runs=runs, warmup=warmup
            ),
            "parse_git_conflicted_files_50": _time_calls(
                s_parse_conflicted, runs=runs, warmup=warmup
            ),
            "parse_git_local_changes_150": _time_calls(
                s_parse_local_changes, runs=runs, warmup=warmup
            ),
        },
    }


# --- end-to-end git scenarios -----------------------------------------------


def _git(cwd: str, args: list[str]) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, check=True)


def _seed_git_repo(repo: Path, *, n_files: int) -> tuple[str, str]:
    """Create a repo with a base commit and a head commit that adds,
    modifies, deletes, and renames files. Returns (base_sha, head_sha)."""
    cwd = str(repo)
    _git(cwd, ["init", "-q", "-b", "main"])
    _git(cwd, ["config", "user.email", "bench@bench"])
    _git(cwd, ["config", "user.name", "bench"])
    _git(cwd, ["config", "commit.gpgsign", "false"])

    # Initial population: enough files to support the modify/delete/rename
    # set on the head commit.
    initial = max(n_files, 4)
    for i in range(initial):
        (repo / f"f_{i}.py").write_text(f"# file {i}\n")
    _git(cwd, ["add", "."])
    _git(cwd, ["commit", "-q", "-m", "init"])
    base = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()

    # Head changes: modify a quarter, delete a quarter, rename a quarter,
    # add a quarter of new files.
    quarter = max(1, n_files // 4)
    for i in range(quarter):
        (repo / f"f_{i}.py").write_text(f"# file {i} modified\n")
    for i in range(quarter, 2 * quarter):
        (repo / f"f_{i}.py").unlink()
    for i in range(2 * quarter, 3 * quarter):
        (repo / f"f_{i}.py").rename(repo / f"renamed_{i}.py")
    for i in range(quarter):
        (repo / f"new_{i}.py").write_text(f"# new {i}\n")
    _git(cwd, ["add", "-A"])
    _git(cwd, ["commit", "-q", "-m", "head"])
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    return base, head


def _measure_end_to_end_diff_name_status(
    *,
    label: str,
    n_files: int,
    runs: int,
    warmup: int,
) -> dict[str, Any]:
    if not _GIT_AVAILABLE:
        return {
            "label": label,
            "skipped": "git not available",
        }
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        base, head = _seed_git_repo(repo, n_files=n_files)
        cwd = str(repo)

        # Capture the stream once for parser-only timing.
        proc = subprocess.run(
            [
                "git",
                "diff",
                "--name-status",
                "-z",
                f"{base}..{head}",
            ],
            cwd=cwd,
            capture_output=True,
            check=True,
            text=True,
        )
        stream = proc.stdout

        def s_subprocess_only() -> int:
            out = subprocess.run(
                [
                    "git",
                    "diff",
                    "--name-status",
                    "-z",
                    f"{base}..{head}",
                ],
                cwd=cwd,
                capture_output=True,
                check=True,
                text=True,
            )
            return len(out.stdout)

        def s_parse_only() -> int:
            return len(parse_git_name_status_z(stream))

        def s_subprocess_plus_parse() -> int:
            out = subprocess.run(
                [
                    "git",
                    "diff",
                    "--name-status",
                    "-z",
                    f"{base}..{head}",
                ],
                cwd=cwd,
                capture_output=True,
                check=True,
                text=True,
            )
            return len(parse_git_name_status_z(out.stdout))

        return {
            "label": label,
            "n_files_seeded": n_files,
            "stream_size_bytes": len(stream.encode("utf-8")),
            "runs": runs,
            "warmup": warmup,
            "scenarios": {
                "git_diff_subprocess_only": _time_calls(
                    s_subprocess_only, runs=runs, warmup=warmup
                ),
                "parse_git_name_status_z": _time_calls(
                    s_parse_only, runs=runs, warmup=warmup
                ),
                "git_diff_subprocess_plus_parse": _time_calls(
                    s_subprocess_plus_parse, runs=runs, warmup=warmup
                ),
            },
        }


# --- printer ----------------------------------------------------------------


def _print_human(report: dict[str, Any]) -> None:
    print()
    label = report.get("label", "?")
    if "skipped" in report:
        print(f"# {label} (skipped: {report['skipped']})")
        return
    extras: list[str] = []
    if "size_bytes" in report:
        extras.append(f"size_bytes={report['size_bytes']}")
    if "stream_size_bytes" in report:
        extras.append(f"stream_size_bytes={report['stream_size_bytes']}")
    if "n_files_seeded" in report:
        extras.append(f"n_files_seeded={report['n_files_seeded']}")
    extras_str = (" " + " ".join(extras)) if extras else ""
    print(f"# {label}{extras_str}")
    print(f"  runs={int(report['runs'])} warmup={int(report['warmup'])}")
    header = (
        f"{'scenario':<40} {'min_us':>10} {'median_us':>12} "
        f"{'p95_us':>10} {'max_us':>10}"
    )
    print("  " + header)
    print("  " + "-" * len(header))
    for name, summary in report["scenarios"].items():
        if summary.get("count", 0) == 0:
            continue
        print(
            "  " + f"{name:<40} {summary['min_us']:>10.3f} "
            f"{summary['median_us']:>12.3f} {summary['p95_us']:>10.3f} "
            f"{summary['max_us']:>10.3f}"
        )


# --- driver -----------------------------------------------------------------


def run_bench(
    *,
    runs: int,
    warmup: int,
    small: int,
    medium: int,
    large: int,
    e2e_runs: int | None,
    output: Path | None,
    skip_e2e: bool,
) -> dict[str, Any]:
    """Run the Phase 5A benchmark and return a structured report."""
    if e2e_runs is None:
        e2e_runs = max(5, min(runs, 30))

    workloads: list[dict[str, Any]] = []

    # Synthetic name-status streams at three sizes. The rename count is
    # ~10% of simple entries, matching real-world rename detection rates
    # observed on monorepos.
    for label, n_simple in (
        ("synthetic_small", small),
        ("synthetic_medium", medium),
        ("synthetic_large", large),
    ):
        stream = _build_name_status_stream(
            n_simple=n_simple, n_rename=max(1, n_simple // 10)
        )
        workloads.append(
            _measure_name_status_parser(
                label=label, stream=stream, runs=runs, warmup=warmup
            )
        )

    # Small normalizers — always cheap, but recorded for completeness.
    workloads.append(_measure_normalizers(runs=runs, warmup=warmup))

    # End-to-end git invocations. Keep the file counts modest because
    # each run forks ``git diff``.
    if not skip_e2e:
        for label, n_files in (
            ("end_to_end_50", 50),
            ("end_to_end_500", 500),
        ):
            workloads.append(
                _measure_end_to_end_diff_name_status(
                    label=label,
                    n_files=n_files,
                    runs=e2e_runs,
                    warmup=max(1, warmup // 2),
                )
            )

    report = {
        "tool": "bench_git_query_ops",
        "phase": "5A",
        "git_available": _GIT_AVAILABLE,
        "platform": {
            "python": sys.version.split()[0],
            "system": platform.system(),
            "machine": platform.machine(),
            "processor": platform.processor() or "unknown",
        },
        "workloads": workloads,
    }

    for w in workloads:
        _print_human(w)

    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2))
        print()
        print(f"Wrote JSON report -> {output}")

    return report


def _argparser() -> argparse.ArgumentParser:
    description = (__doc__ or "").splitlines()[0] if __doc__ else ""
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("-r", "--runs", type=int, default=200)
    parser.add_argument("-w", "--warmup", type=int, default=20)
    parser.add_argument(
        "-s",
        "--small",
        type=int,
        default=50,
        help="Synthetic small name-status entry count (default: 50, ~typical PR).",
    )
    parser.add_argument(
        "-m",
        "--medium",
        type=int,
        default=1000,
        help="Synthetic medium name-status entry count (default: 1000).",
    )
    parser.add_argument(
        "-l",
        "--large",
        type=int,
        default=10000,
        help="Synthetic large name-status entry count (default: 10000).",
    )
    parser.add_argument(
        "-E",
        "--e2e-runs",
        type=int,
        default=None,
        help=(
            "Timed iterations for the end-to-end git scenarios (defaults to "
            "max(5, min(runs, 30)) because each iteration forks git)."
        ),
    )
    parser.add_argument(
        "-S",
        "--skip-e2e",
        action="store_true",
        help="Skip end-to-end git scenarios (synthetic+normalizers only).",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="Write a JSON report to this path in addition to stdout.",
    )
    return parser


def test_bench_git_query_ops_smoke(tmp_path: Path) -> None:
    """Sanity check the harness on tiny inputs."""
    report = run_bench(
        runs=2,
        warmup=1,
        small=4,
        medium=8,
        large=16,
        e2e_runs=2,
        output=tmp_path / "bench.json",
        skip_e2e=not _GIT_AVAILABLE,
    )
    assert report["workloads"], "expected at least one workload"
    syn = next(w for w in report["workloads"] if w.get("label") == "synthetic_small")
    assert "parse_git_name_status_z" in syn["scenarios"]
    assert (tmp_path / "bench.json").exists()


def main(argv: list[str] | None = None) -> int:
    args = _argparser().parse_args(argv)
    run_bench(
        runs=args.runs,
        warmup=args.warmup,
        small=args.small,
        medium=args.medium,
        large=args.large,
        e2e_runs=args.e2e_runs,
        output=args.output,
        skip_e2e=args.skip_e2e,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
