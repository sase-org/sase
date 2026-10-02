"""Subprocess-isolated pager benchmark (phase ``pager-bench``).

Each ``(corpus, line count)`` case runs in a fresh subprocess with a
per-case timeout and reports ``TIMEOUT`` rather than hanging. Metrics cover
document build, headless mount to first paint, syntax-overlay publish, per-key
CPU, peak RSS, and a dismissed-view leak probe, plus a trivial-app floor so
numbers read both raw and above the floor.

Run directly (default ladder is 500/2k/20k/100k; cap with ``--max-lines``)::

    python tests/perf/bench_pager.py --cases code-sparse,log-dense
    python tests/perf/bench_pager.py --max-lines 2000 --no-cold
    python tests/perf/bench_pager.py --output /tmp/pager-bench.json

Baseline numbers are intentionally not committed: shared-host timing is noisy.
The fast smoke test lives in ``test_pager_bench_smoke.py`` (non-slow) so the
harness cannot rot under ``sase tool run check``.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import pty
import select
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

import pytest

try:
    from ._pager_bench_corpus import CASE_NAMES, LINE_LADDER, write_corpus
except ImportError:  # direct script run: tests/perf is on sys.path, no package
    from _pager_bench_corpus import CASE_NAMES, LINE_LADDER, write_corpus

pytestmark = pytest.mark.slow

_HERE = Path(__file__).resolve()
SIZE_MAIN = (120, 40)
SIZE_ALT = (100, 30)

NAV_KEYS = ("j", "k", "ctrl+d", "G", "g")
SEARCH_CHARS = ("l", "i", "n")


def _median(values: list[float]) -> float:
    return statistics.median(values) if values else 0.0


async def _measure_worker(
    case_path: str, case_name: str, line_count: int
) -> dict[str, Any]:
    """Run every in-process metric for one case; never raises out."""
    import gc
    import resource
    import weakref

    from sase.pager.app import SasePager
    from sase.pager.document import (
        PagerDocument,
        PagerOrigin,
        PagerSection,
        RawSourceSpec,
        section_syntax_language,
    )
    from sase.pager.screen import PagerScreen
    from sase.pager.view import PagerView

    notes: list[str] = []
    metrics: dict[str, Any] = {}

    text = Path(case_path).read_text(encoding="utf-8")

    # Corpora with real source text carry raw-source provenance so the syntax
    # overlay runs for them, matching the plan's corpus table.
    language = {"code-sparse": "python", "markdown": "markdown"}.get(case_name)
    raw_source = RawSourceSpec(language=language) if language else None

    t0 = time.perf_counter()
    section = PagerSection(
        identity=f"bench:{case_name}",
        title=case_name,
        kind="file",
        body=text,
        raw_source=raw_source,
    )
    document = PagerDocument(
        sections=(section,), title=case_name, origin=PagerOrigin.FILE
    )
    metrics["build_wall_s"] = time.perf_counter() - t0

    # Trivial-app floor, measured in the same harness.
    from textual.app import App

    class _Floor(App[None]):
        pass

    t0, c0 = time.perf_counter(), time.process_time()
    floor_app = _Floor()
    async with floor_app.run_test(size=SIZE_MAIN):
        pass
    metrics["floor_mount_wall_s"] = time.perf_counter() - t0
    metrics["floor_mount_cpu_s"] = time.process_time() - c0

    app = SasePager(document)
    t0, c0 = time.perf_counter(), time.process_time()
    try:
        async with app.run_test(size=SIZE_MAIN) as pilot:
            await pilot.pause()
            metrics["mount_wall_s"] = time.perf_counter() - t0
            metrics["mount_cpu_s"] = time.process_time() - c0

            screen = app.screen
            assert isinstance(screen, PagerScreen)

            # Syntax overlay publish: poll until a section attempt lands.
            # Sections with no syntax language never publish; skip the poll.
            syntax_s: float | None = None
            if section_syntax_language(section) is None:
                notes.append("no syntax language for this case; publish poll skipped")
            else:
                deadline = time.perf_counter() + 30.0
                while time.perf_counter() < deadline:
                    attempted: set[tuple[str, Any]] = getattr(
                        screen, "_syntax_attempted", set()
                    )
                    if attempted:
                        syntax_s = time.perf_counter() - t0
                        break
                    await pilot.pause()
                if syntax_s is None:
                    notes.append("syntax overlay did not publish within 30s")
            metrics["syntax_publish_s"] = syntax_s

            async def _press_cpu(key: str, *, reps: int = 1) -> dict[str, Any]:
                samples: list[float] = []
                try:
                    for _ in range(reps):
                        start = time.process_time()
                        await pilot.press(key)
                        await pilot.pause()
                        samples.append(time.process_time() - start)
                except Exception as exc:  # noqa: BLE001 - bench must not hang
                    return {"cpu_s": None, "note": f"{type(exc).__name__}: {exc}"}
                return {
                    "median_cpu_s": _median(samples),
                    "max_cpu_s": max(samples),
                    "reps": reps,
                }

            keys: dict[str, Any] = {}
            for key in NAV_KEYS:
                keys[key] = await _press_cpu(key, reps=3)

            # One label-prefix key. It may follow a link; note if we moved.
            keys["label_a"] = await _press_cpu("a")
            try:
                keys["label_a"]["navigated"] = app.screen is not screen
                while app.screen is not screen:
                    await pilot.press("backspace")
                    await pilot.pause()
                    break
            except Exception:  # noqa: BLE001 - best effort restore
                pass

            # Three-character search typed, then enter, then n.
            search: dict[str, Any] = {}
            try:
                await pilot.press("slash")
                await pilot.pause()
            except Exception as exc:  # noqa: BLE001
                search["open_error"] = f"{type(exc).__name__}: {exc}"
            for char in SEARCH_CHARS:
                search[f"char_{char}"] = await _press_cpu(char)
            search["enter"] = await _press_cpu("enter")
            search["n"] = await _press_cpu("n")
            try:
                await pilot.press("escape")
                await pilot.pause()
            except Exception:  # noqa: BLE001
                pass
            keys["search"] = search

            try:
                await pilot.press("q")
                await pilot.pause()
            except Exception:  # noqa: BLE001
                pass
    except Exception as exc:  # noqa: BLE001 - report, never hang the parent
        notes.append(f"headless run failed: {type(exc).__name__}: {exc}")
        metrics["headless_error"] = f"{type(exc).__name__}: {exc}"
        metrics.setdefault("mount_wall_s", None)
        metrics.setdefault("mount_cpu_s", None)
        metrics.setdefault("syntax_publish_s", None)
        keys = {}
    metrics["keys"] = keys

    # Resize proxy: remount at an alternate size (pilot has no resize API).
    try:
        app2 = SasePager(document)
        t0 = time.perf_counter()
        async with app2.run_test(size=SIZE_ALT) as pilot2:
            await pilot2.pause()
            try:
                await pilot2.press("q")
                await pilot2.pause()
            except Exception:  # noqa: BLE001
                pass
        metrics["remount_100x30_wall_s"] = time.perf_counter() - t0
    except Exception as exc:  # noqa: BLE001
        metrics["remount_100x30_wall_s"] = None
        notes.append(f"remount probe failed: {type(exc).__name__}: {exc}")

    # Leak probe: push/pop a PagerScreen three times, gc, count live views.
    try:
        host = SasePager(document)
        live_refs: list[weakref.ReferenceType[PagerView]] = []
        async with host.run_test(size=(80, 24)) as pilot3:
            for _ in range(3):
                pushed = PagerScreen(document)
                await host.push_screen(pushed)
                await pilot3.pause()
                try:
                    live_refs.append(weakref.ref(pushed.query_one(PagerView)))
                except Exception:  # noqa: BLE001
                    notes.append("leak probe could not find PagerView")
                await host.pop_screen()
                await pilot3.pause()
        gc.collect()
        metrics["leak_live_views"] = sum(1 for ref in live_refs if ref() is not None)
        metrics["leak_probed"] = len(live_refs)
    except Exception as exc:  # noqa: BLE001
        metrics["leak_live_views"] = None
        metrics["leak_probed"] = 0
        notes.append(f"leak probe failed: {type(exc).__name__}: {exc}")

    try:
        rss_kb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        metrics["peak_rss_mb"] = rss_kb / 1024.0
    except Exception:  # noqa: BLE001
        metrics["peak_rss_mb"] = None

    return {
        "status": "ok",
        "case": case_name,
        "lines": line_count,
        "bytes": len(text),
        "metrics": metrics,
        "notes": notes,
    }


def _worker_main(case_path: str, case_name: str, line_count: int) -> int:
    try:
        result = asyncio.run(_measure_worker(case_path, case_name, line_count))
    except Exception as exc:  # noqa: BLE001 - last resort; parent parses JSON
        result = {
            "status": "ERROR",
            "case": case_name,
            "error": f"{type(exc).__name__}: {exc}",
        }
    sys.stdout.write(json.dumps(result) + "\n")
    sys.stdout.flush()
    return 0


def _run_case_subprocess(
    *, case_path: str, case_name: str, line_count: int, timeout: float
) -> dict[str, Any]:
    """Run one case in a fresh subprocess; TIMEOUT instead of hanging."""
    cmd = [
        sys.executable,
        str(_HERE),
        "--worker",
        case_path,
        case_name,
        str(line_count),
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"status": "TIMEOUT", "case": case_name, "lines": line_count}
    if proc.returncode != 0 or not proc.stdout.strip():
        return {
            "status": "ERROR",
            "case": case_name,
            "lines": line_count,
            "returncode": proc.returncode,
            "stderr_tail": proc.stderr[-2000:],
        }
    try:
        payload = json.loads(proc.stdout.strip().splitlines()[-1])
    except json.JSONDecodeError:
        return {
            "status": "ERROR",
            "case": case_name,
            "lines": line_count,
            "stdout_tail": proc.stdout[-2000:],
        }
    payload.setdefault("lines", line_count)
    return payload


def _parse_importtime_cumulative(output: str, module: str) -> float | None:
    """Return the cumulative import time in seconds for *module*."""
    best: float | None = None
    for line in output.splitlines():
        # Format: "import time: self [us] | cumulative [us] | module.name"
        parts = [part.strip() for part in line.split("|")]
        if len(parts) == 3 and parts[2] == module:
            try:
                best = int(parts[1]) / 1_000_000.0
            except ValueError:
                continue
    return best


def _cold_probes(*, sample_path: str, timeout: float = 120.0) -> dict[str, Any]:
    """Fresh-process cold-path probes (importtime, plain wall, pty paint)."""
    probes: dict[str, Any] = {}
    env = dict(os.environ)
    for module in ("sase.main.pager_handler", "sase.pager.screen"):
        key = f"importtime_{module.rsplit('.', 1)[-1]}_s"
        try:
            proc = subprocess.run(
                [sys.executable, "-X", "importtime", "-c", f"import {module}"],
                capture_output=True,
                text=True,
                timeout=timeout,
                env=env,
            )
            probes[key] = _parse_importtime_cumulative(proc.stderr, module)
        except subprocess.TimeoutExpired:
            probes[key] = "TIMEOUT"
        except Exception as exc:  # noqa: BLE001
            probes[key] = f"ERROR: {type(exc).__name__}: {exc}"

    try:
        start = time.perf_counter()
        proc = subprocess.run(
            [sys.executable, "-m", "sase.main.entry", "pager", "--plain", sample_path],
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )
        probes["plain_file_wall_s"] = time.perf_counter() - start
        probes["plain_file_rc"] = proc.returncode
        if proc.returncode != 0:
            probes["plain_file_stderr_tail"] = proc.stderr[-1000:]
    except subprocess.TimeoutExpired:
        probes["plain_file_wall_s"] = "TIMEOUT"
    except Exception as exc:  # noqa: BLE001
        probes["plain_file_wall_s"] = f"ERROR: {type(exc).__name__}: {exc}"

    probes["plain_bead_wall_s"] = "SKIPPED: no disposable SASE_HOME bead-store fixture"
    probes["pty_first_paint_s"] = _pty_first_paint(
        sample_path, timeout=min(timeout, 180.0)
    )
    return probes


def _pty_first_paint(sample_path: str, *, timeout: float) -> float | str | None:
    """Spawn ``sase pager`` under a 120x40 pty; time to first output bytes."""
    argv = [sys.executable, "-m", "sase.main.entry", "pager", sample_path]
    try:
        pid, fd = pty.fork()
    except Exception as exc:  # noqa: OSError - pty unavailable  # BLE001
        return f"ERROR: {type(exc).__name__}: {exc}"
    if pid == 0:  # child
        try:
            import fcntl
            import struct
            import termios

            winsize = struct.pack("HHHH", 40, 120, 0, 0)
            fcntl.ioctl(1, termios.TIOCSWINSZ, winsize)
        except Exception:  # noqa: BLE001 - best effort; size default still paints
            pass
        os.execvp(argv[0], argv)
        os._exit(127)  # noqa: PGH5501 - execvp either replaces us or fails
    start = time.perf_counter()
    first: float | None = None
    try:
        deadline = start + timeout
        while time.perf_counter() < deadline:
            ready, _, _ = select.select([fd], [], [], 2.0)
            if ready:
                try:
                    chunk = os.read(fd, 65536)
                except OSError:
                    break
                if not chunk:
                    break
                if first is None:
                    first = time.perf_counter() - start
                if (
                    len(chunk) > 0
                    and first is not None
                    and time.perf_counter() - start > first + 1.0
                ):
                    break
        try:
            os.write(fd, b"q")
        except OSError:
            pass
        time.sleep(1.0)  # sase-test-wait: pty quit drain
    finally:
        try:
            os.close(fd)
        except OSError:
            pass
        try:
            _, status = os.waitpid(pid, os.WNOHANG)
            if status == 0 and first is None:
                pass
        except ChildProcessError:
            pass
        try:
            os.kill(pid, 9)
        except (OSError, ProcessLookupError):
            pass
    return first if first is not None else "TIMEOUT"


def _print_table(report: dict[str, Any]) -> None:
    print(f"{'case':<28} {'metric':<28} {'value':>14} {'above_floor':>14}")
    for key in sorted(
        report["results"], key=lambda k: report["results"][k].get("sort", k)
    ):
        entry = report["results"][key]
        status = entry.get("status")
        if status != "ok":
            print(f"{key:<28} {'status':<28} {str(status):>14} {'':>14}")
            continue
        metrics = entry.get("metrics", {})
        floor = metrics.get("floor_mount_cpu_s") or 0.0
        rows: list[tuple[str, Any]] = [
            ("build_wall_s", metrics.get("build_wall_s")),
            ("mount_wall_s", metrics.get("mount_wall_s")),
            ("mount_cpu_s", metrics.get("mount_cpu_s")),
            ("syntax_publish_s", metrics.get("syntax_publish_s")),
            ("remount_100x30_wall_s", metrics.get("remount_100x30_wall_s")),
            ("peak_rss_mb", metrics.get("peak_rss_mb")),
            ("leak_live_views", metrics.get("leak_live_views")),
        ]
        for key_name, key_entry in (metrics.get("keys") or {}).items():
            if not isinstance(key_entry, dict):
                continue
            if "median_cpu_s" in key_entry:
                rows.append(
                    (f"key:{key_name}_median_cpu_s", key_entry.get("median_cpu_s"))
                )
                rows.append((f"key:{key_name}_max_cpu_s", key_entry.get("max_cpu_s")))
            for sub in ("open_error", "note"):
                if key_entry.get(sub):
                    rows.append((f"key:{key_name}_{sub}", key_entry[sub]))
        search = (metrics.get("keys") or {}).get("search")
        if isinstance(search, dict):
            for sub_name, sub_entry in search.items():
                if isinstance(sub_entry, dict) and "median_cpu_s" in sub_entry:
                    rows.append((f"search:{sub_name}_cpu_s", sub_entry["median_cpu_s"]))
        for metric, value in rows:
            if value is None:
                rendered, above = "n/a", ""
            elif isinstance(value, (int, float)) and "cpu_s" in metric:
                rendered = f"{value:.3f}"
                above = f"{max(0.0, value - floor):.3f}"
            elif isinstance(value, float):
                rendered = f"{value:.3f}"
                above = ""
            else:
                rendered = str(value)[:40]
                above = ""
            print(f"{key:<28} {metric:<28} {rendered:>14} {above:>14}")


def run_bench(
    *,
    cases: tuple[str, ...] = CASE_NAMES,
    ladder: tuple[int, ...] = LINE_LADDER,
    per_case_timeout: float = 600.0,
    include_cold: bool = True,
    output: Path | None = None,
    corpus_dir: Path | None = None,
) -> dict[str, Any]:
    """Run the full matrix; each case isolated in a fresh subprocess."""
    with tempfile.TemporaryDirectory(prefix="pager-bench-") as tmp:
        root = corpus_dir or Path(tmp)
        descriptors = write_corpus(root, cases=cases, ladder=ladder)
        if include_cold:
            smallest = next(d for d in descriptors if d["lines"] == min(ladder))
            cold = _cold_probes(sample_path=str(smallest["path"]))
        else:
            cold = {"note": "cold probes disabled (--no-cold)"}
        results: dict[str, Any] = {}
        for descriptor in descriptors:
            key = f"{descriptor['name']}/{descriptor['lines']}"
            entry = _run_case_subprocess(
                case_path=str(descriptor["path"]),
                case_name=str(descriptor["name"]),
                line_count=int(descriptor["lines"]),  # type: ignore[arg-type]
                timeout=per_case_timeout,
            )
            entry["sort"] = key
            results[key] = entry
    report: dict[str, Any] = {
        "tool": "bench_pager",
        "cases": list(cases),
        "ladder": list(ladder),
        "per_case_timeout_s": per_case_timeout,
        "cold": cold,
        "results": results,
    }
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return report


def _parse_csv_strings(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", default=",".join(CASE_NAMES))
    parser.add_argument("--ladder", default=",".join(str(n) for n in LINE_LADDER))
    parser.add_argument("--max-lines", type=int, default=None)
    parser.add_argument("--timeout", type=float, default=600.0)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--no-cold", action="store_true")
    parser.add_argument(
        "--worker", nargs=3, metavar=("PATH", "NAME", "LINES"), default=None
    )
    args = parser.parse_args(argv)
    if args.worker is not None:
        path, name, lines = args.worker
        return _worker_main(path, name, int(lines))
    ladder = tuple(int(n) for n in _parse_csv_strings(args.ladder))
    if args.max_lines is not None:
        ladder = tuple(n for n in ladder if n <= args.max_lines) or (min(ladder),)
    report = run_bench(
        cases=tuple(_parse_csv_strings(args.cases)),
        ladder=ladder,
        per_case_timeout=args.timeout,
        include_cold=not args.no_cold,
        output=args.output,
    )
    _print_table(report)
    if args.output is None:
        print(json.dumps(report["cold"], indent=2, sort_keys=True))
    return 0


def test_bench_pager_matrix(tmp_path: Path) -> None:
    """Slow harness exercise: every corpus at 500 lines, subprocess-isolated."""
    report = run_bench(
        cases=CASE_NAMES,
        ladder=(500,),
        per_case_timeout=300.0,
        include_cold=False,
        output=tmp_path / "pager-bench.json",
        corpus_dir=tmp_path / "corpus",
    )
    assert report["tool"] == "bench_pager"
    assert (tmp_path / "pager-bench.json").exists()
    assert len(report["results"]) == len(CASE_NAMES)
    for key, entry in report["results"].items():
        assert entry["status"] == "ok", f"{key}: {entry}"
        assert entry["metrics"]["build_wall_s"] is not None
        assert entry["metrics"]["mount_wall_s"] is not None


if __name__ == "__main__":
    raise SystemExit(main())
