"""Phase 7C end-to-end TUI/CLI startup measurements.

Bead ``sase-1e.3`` / ``plans/202604/rust_backend_phase7.md``. Captures
user-facing surfaces (``sase ace`` cold-open, ``sase agents status -j``
listing, ``sase run`` startup up to the provider boundary) under both
backends so Phase 7D can describe what users actually pay before any LLM
work begins.

Each invocation produces ONE Phase 7 artifact for ONE
``(surface, backend)`` pair. Wrapping shell drivers (Phase 7E) iterate
the matrix; this script keeps a single timing loop per call so subprocess
cold-start cost is honest.

Usage::

    python tests/perf/bench_phase7_e2e.py \\
        --surface sase_agents_status_listing \\
        --backend default_rust --workload synthetic_200_specs \\
        --runs 10 --warmup 2 --output ...

Surfaces:

- ``sase_ace_cold_open`` — in-process Pilot harness (reuses
  ``bench_tui_trace._run_scenario``), records the ``cold_start``
  wall-time for the smallest synthetic fixture under each backend.
  Python interpreter imports are warm; this measures Pilot/AceApp
  constructor + first paint, not full subprocess cold start. Phase 7D
  should pair this with the manual home-tree note for context.
- ``sase_agents_status_listing`` — subprocess ``sase agents status -j``.
  Synthetic workload writes a temporary ``HOME/.sase/projects`` tree;
  the ``home_tree`` workload uses the real ``$HOME`` so cold listing
  cost reflects the user's actual project count.
- ``sase_run_startup`` — subprocess
  ``python -c "from sase.main.query_handler._query import run_query"``.
  This is a deliberately scoped proxy for "``sase run`` startup up to
  the provider boundary": it includes every import the dispatcher does
  before the LLM call but stops before any provider/network work, so it
  never invokes a live LLM and never depends on the user's keys.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from tests.perf.phase7 import BackendChoice, artifact_path, build_metadata


# Surface identifiers — must match the labels locked in
# ``sdd/plans/202604/perf_artifacts/README.md``.
SURFACE_ACE = "sase_ace_cold_open"
SURFACE_AGENTS = "sase_agents_status_listing"
SURFACE_RUN = "sase_run_startup"

_SURFACES = (SURFACE_ACE, SURFACE_AGENTS, SURFACE_RUN)


def _summarize(samples: list[float]) -> dict[str, float]:
    """Return a Phase 7A-compatible summary dict from per-run seconds."""
    if not samples:
        return {"count": 0.0}
    s = sorted(samples)
    n = len(s)
    p95_idx = max(0, int(round(0.95 * (n - 1))))
    return {
        "count": float(n),
        "min_ms": s[0] * 1000.0,
        "median_ms": statistics.median(s) * 1000.0,
        "p95_ms": s[p95_idx] * 1000.0,
        "max_ms": s[-1] * 1000.0,
    }


def _resolve_backend_env(choice: BackendChoice) -> dict[str, str]:
    """Phase 7A kept this helper around for filename tagging only.

    Post-Phase-8 there is no ``SASE_CORE_BACKEND`` env var to set; the
    facades always call ``sase_core_rs`` directly. The function returns
    an empty mapping so callers that still pass ``backend_env`` pick up
    no overrides.
    """
    del choice
    return {}


def _subprocess_env(extra: dict[str, str]) -> dict[str, str]:
    env = os.environ.copy()
    env.update(extra)
    return env


# --------------------------------------------------------------------------
# Surface 1: sase_ace_cold_open
# --------------------------------------------------------------------------


async def _bench_ace_cold_open_async(
    *,
    runs: int,
    warmup: int,
    cs_count: int,
    agent_count: int,
) -> list[float]:
    """Reuse ``bench_tui_trace._run_scenario`` to time the cold-open path.

    Returns a list of cold-start wall-times in seconds.
    """
    # Late import to keep this script importable in environments that
    # do not have the TUI / Pilot dependencies on the import path until
    # the surface is actually exercised.
    from tests.perf.bench_tui_trace import _run_scenario

    samples: list[float] = []
    with tempfile.TemporaryDirectory() as tmpdir:
        gp_file = Path(tmpdir) / "bench.gp"
        gp_file.write_text("")
        # Pilot/TUI tracing env — bench_tui_trace expects these set.
        trace_path = Path(tmpdir) / "tui_trace.jsonl"
        perf_path = Path(tmpdir) / "tui_jk.jsonl"
        os.environ.setdefault("SASE_TUI_TRACE", "1")
        os.environ["SASE_TUI_TRACE_PATH"] = str(trace_path)
        os.environ.setdefault("SASE_TUI_PERF", "1")
        os.environ["SASE_TUI_PERF_PATH"] = str(perf_path)

        for _ in range(warmup):
            await _run_scenario(
                cs_count,
                agent_count,
                j_keys=0,
                gp_file=gp_file,
                large_reply_text=None,
            )
        for _ in range(runs):
            if trace_path.exists():
                trace_path.unlink()
            if perf_path.exists():
                perf_path.unlink()
            result = await _run_scenario(
                cs_count,
                agent_count,
                j_keys=0,
                gp_file=gp_file,
                large_reply_text=None,
            )
            cold_ms = float(result["wall_ms"]["cold_start"])
            samples.append(cold_ms / 1000.0)
    return samples


def _bench_ace_cold_open(
    *, runs: int, warmup: int, cs_count: int, agent_count: int
) -> dict[str, Any]:
    samples = asyncio.run(
        _bench_ace_cold_open_async(
            runs=runs,
            warmup=warmup,
            cs_count=cs_count,
            agent_count=agent_count,
        )
    )
    workload_label = f"synthetic_{cs_count}_cs_{agent_count}_agents"
    return {
        "workload": workload_label,
        "scenarios": {
            "cold_start": _summarize(samples),
        },
        "extra": {
            "harness": "bench_tui_trace._run_scenario (in-process Pilot)",
            "boundary": (
                "AceApp constructor + first Pilot pause; Python imports are warm"
            ),
            "cs_count": cs_count,
            "agent_count": agent_count,
        },
    }


# --------------------------------------------------------------------------
# Surface 2: sase_agents_status_listing
# --------------------------------------------------------------------------


def _build_synthetic_home(home: Path, *, projects: int, per_project: int) -> None:
    """Lay out a synthetic ``~/.sase/projects`` tree for ``sase agents status``.

    Mirrors the Phase 6E synthetic shape (one ``ace-run`` workflow tree
    per project, plus a stopped ``done.json`` per agent so the listing
    is non-empty).
    """
    base_ts = 20260101000000
    for p in range(projects):
        proj_root = home / ".sase" / "projects" / f"proj{p:03d}"
        proj_root.mkdir(parents=True, exist_ok=True)
        (proj_root / f"proj{p:03d}.gp").write_text("")
        ace_root = proj_root / "artifacts" / "ace-run"
        ace_root.mkdir(parents=True, exist_ok=True)
        for i in range(per_project):
            ts = str(base_ts + p * per_project + i)
            adir = ace_root / ts
            adir.mkdir(parents=True, exist_ok=True)
            meta = {
                "name": f"agent_{p:03d}_{i:04d}",
                "workflow_name": f"wf_{(p * per_project + i) % 4}",
                "model": "claude-opus-4-7",
                "pid": 99_999_999,
                "stopped_at": "2026-01-01T00:00:00Z",
            }
            (adir / "agent_meta.json").write_text(json.dumps(meta))
            (adir / "done.json").write_text("{}")


def _bench_agents_status_listing(
    *,
    runs: int,
    warmup: int,
    backend_env: dict[str, str],
    workload: str,
    projects: int,
    per_project: int,
) -> dict[str, Any]:
    """Time ``sase agents status -j`` cold subprocess launches."""
    # ``shutil.which("sase")`` resolves the venv entry point for the
    # current python interpreter, which is what the user runs.
    sase_bin = _resolve_sase_bin()

    if workload == "synthetic":
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir)
            _build_synthetic_home(home, projects=projects, per_project=per_project)
            env = _subprocess_env(backend_env)
            env["HOME"] = str(home)
            samples = _time_subprocess(
                cmd=[sase_bin, "agents", "status", "-j"],
                env=env,
                runs=runs,
                warmup=warmup,
            )
        workload_label = f"synthetic_{projects}_projects_{per_project}_agents"
        extra: dict[str, Any] = {
            "workload_kind": "synthetic",
            "projects": projects,
            "per_project": per_project,
        }
    elif workload == "home_tree":
        env = _subprocess_env(backend_env)
        # Do NOT override HOME — point at the real user tree on purpose.
        # We sanitise the artifact below so the recorded path is opaque.
        samples = _time_subprocess(
            cmd=[sase_bin, "agents", "status", "-j"],
            env=env,
            runs=runs,
            warmup=warmup,
        )
        workload_label = "home_tree"
        extra = {
            "workload_kind": "home_tree",
            "home_path": "<sanitized>",
            "note": "Real $HOME tree; project paths intentionally not recorded.",
        }
    else:
        raise ValueError(f"Unknown workload {workload!r} for agents_status_listing")

    return {
        "workload": workload_label,
        "scenarios": {
            "sase_agents_status_j": _summarize(samples),
        },
        "extra": extra,
    }


# --------------------------------------------------------------------------
# Surface 3: sase_run_startup
# --------------------------------------------------------------------------


_RUN_STARTUP_SNIPPET = (
    "from sase.main.query_handler._query import run_query as _r; _ = _r"
)


def _bench_run_startup(
    *,
    runs: int,
    warmup: int,
    backend_env: dict[str, str],
) -> dict[str, Any]:
    """Time cold ``python -c <import-run_query>`` subprocess launches.

    The snippet imports the same ``run_query`` entry point ``sase run``
    drives but stops before invoking any provider. This is the documented
    Phase 7C "up to the provider boundary" boundary: it captures the
    interpreter + sase package + dispatcher import cost users pay before
    any LLM work, without depending on a live network or stub provider.
    """
    env = _subprocess_env(backend_env)
    samples = _time_subprocess(
        cmd=[sys.executable, "-c", _RUN_STARTUP_SNIPPET],
        env=env,
        runs=runs,
        warmup=warmup,
    )
    return {
        "workload": "import_run_query_cold",
        "scenarios": {
            "import_run_query_cold": _summarize(samples),
        },
        "extra": {
            "boundary": (
                "subprocess python -c 'from sase.main.query_handler._query "
                "import run_query'; provider invocation NOT exercised"
            ),
            "interpreter": sys.executable,
        },
    }


# --------------------------------------------------------------------------
# Subprocess timing helper
# --------------------------------------------------------------------------


def _time_subprocess(
    *, cmd: list[str], env: dict[str, str], runs: int, warmup: int
) -> list[float]:
    """Run ``cmd`` ``runs + warmup`` times, returning per-run wall seconds."""
    for _ in range(warmup):
        completed = subprocess.run(cmd, env=env, capture_output=True)
        if completed.returncode != 0:
            sys.stderr.write(
                f"warmup nonzero exit ({completed.returncode}): {cmd}\n"
                f"stderr: {completed.stderr.decode(errors='replace')}\n"
            )
    samples: list[float] = []
    for _ in range(runs):
        t0 = time.perf_counter()
        completed = subprocess.run(cmd, env=env, capture_output=True)
        elapsed = time.perf_counter() - t0
        if completed.returncode != 0:
            raise RuntimeError(
                f"command exited {completed.returncode}: {cmd}\n"
                f"stderr: {completed.stderr.decode(errors='replace')}"
            )
        samples.append(elapsed)
    return samples


def _resolve_sase_bin() -> str:
    """Return the path of the ``sase`` entry point alongside ``sys.executable``."""
    candidate = Path(sys.executable).parent / "sase"
    if candidate.exists():
        return str(candidate)
    # Fall back to whatever is on PATH; raises if completely missing.
    import shutil

    found = shutil.which("sase")
    if found is None:
        raise RuntimeError(
            "Could not locate the 'sase' entry point next to "
            f"{sys.executable!r} or on PATH."
        )
    return found


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def _sanitize(value: Any) -> Any:
    """Replace ``$HOME`` prefixes with ``~`` recursively in committed artifacts.

    Phase 7C ships these JSON files into the repo, so any path that
    resolves to ``$HOME`` would leak the developer's username. We do not
    rewrite ``$TMPDIR`` paths because synthetic workloads write under a
    short-lived ``tempfile.TemporaryDirectory`` whose name is meaningless
    by the time the artifact lands.
    """
    home = str(Path.home())
    if isinstance(value, str):
        if home and value.startswith(home):
            return "~" + value[len(home) :]
        return value
    if isinstance(value, list):
        return [_sanitize(v) for v in value]
    if isinstance(value, dict):
        return {k: _sanitize(v) for k, v in value.items()}
    return value


def _build_artifact(
    *,
    surface: str,
    backend: BackendChoice,
    runs: int,
    warmup: int,
    body: dict[str, Any],
) -> dict[str, Any]:
    metadata = build_metadata(
        tool="bench_phase7_e2e",
        surface=surface,
        workload=str(body.get("workload", "")),
        backend=backend,
        runs=runs,
        warmup=warmup,
        extra=body.get("extra", {}) or None,
    )
    return {
        "metadata": metadata.as_dict(),
        "workloads": [
            {
                "workload": body.get("workload", ""),
                "scenarios": body["scenarios"],
            }
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "-s",
        "--surface",
        required=True,
        choices=_SURFACES,
        help="Which Phase 7C surface to measure (one per invocation).",
    )
    parser.add_argument(
        "-b",
        "--backend",
        required=True,
        choices=[
            str(BackendChoice.DEFAULT_PYTHON),
            str(BackendChoice.DEFAULT_RUST),
            str(BackendChoice.EXPLICIT_PYTHON),
            str(BackendChoice.EXPLICIT_RUST),
        ],
        help=(
            "Backend tag retained for filename compatibility. Post-Phase-8 "
            "the facades always run direct-Rust regardless of this flag."
        ),
    )
    parser.add_argument(
        "-r",
        "--runs",
        type=int,
        default=10,
        help="Timed iterations per scenario (default 10).",
    )
    parser.add_argument(
        "-W",
        "--warmup",
        type=int,
        default=2,
        help="Untimed warmup iterations per scenario (default 2).",
    )
    parser.add_argument(
        "-w",
        "--workload",
        default="synthetic",
        help=(
            "Workload variant. agents_status_listing: 'synthetic' (default) "
            "or 'home_tree'. Other surfaces ignore this flag."
        ),
    )
    parser.add_argument(
        "-p",
        "--projects",
        type=int,
        default=8,
        help="Synthetic project count for agents_status_listing (default 8).",
    )
    parser.add_argument(
        "-n",
        "--per-project",
        type=int,
        default=25,
        help="Synthetic agents-per-project for agents_status_listing (default 25).",
    )
    parser.add_argument(
        "-c",
        "--cs-count",
        type=int,
        default=100,
        help="ChangeSpec count for sase_ace_cold_open (default 100).",
    )
    parser.add_argument(
        "-a",
        "--agent-count",
        type=int,
        default=50,
        help="Agent count for sase_ace_cold_open (default 50).",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help=(
            "Override output path. Defaults to "
            "sdd/plans/202604/perf_artifacts/"
            "rust_backend_phase7_<surface>_<backend>.json."
        ),
    )
    args = parser.parse_args(argv)

    backend = BackendChoice(args.backend)
    backend_env = _resolve_backend_env(backend)

    if args.surface == SURFACE_ACE:
        body = _bench_ace_cold_open(
            runs=args.runs,
            warmup=args.warmup,
            cs_count=args.cs_count,
            agent_count=args.agent_count,
        )
    elif args.surface == SURFACE_AGENTS:
        body = _bench_agents_status_listing(
            runs=args.runs,
            warmup=args.warmup,
            backend_env=backend_env,
            workload=args.workload,
            projects=args.projects,
            per_project=args.per_project,
        )
    elif args.surface == SURFACE_RUN:
        body = _bench_run_startup(
            runs=args.runs,
            warmup=args.warmup,
            backend_env=backend_env,
        )
    else:  # pragma: no cover - argparse guards this
        raise AssertionError(f"unreachable surface {args.surface!r}")

    artifact = _build_artifact(
        surface=args.surface,
        backend=backend,
        runs=args.runs,
        warmup=args.warmup,
        body=body,
    )

    output = args.output
    if output is None:
        output = artifact_path(surface=args.surface, backend_or_summary=backend)
    output.parent.mkdir(parents=True, exist_ok=True)
    sanitized = _sanitize(artifact)
    output.write_text(json.dumps(sanitized, indent=2) + "\n")

    median_ms = (
        next(iter(body["scenarios"].values())).get("median_ms", float("nan"))
        if body.get("scenarios")
        else float("nan")
    )
    print(
        f"phase7c surface={args.surface} backend={backend.value} "
        f"workload={body.get('workload', '')} "
        f"runs={args.runs} warmup={args.warmup} "
        f"median_ms={median_ms:.2f} -> {output}"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
