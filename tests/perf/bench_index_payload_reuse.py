"""Matched Python-boundary benchmark; run as a script with the checkout's Python.

Each mode starts in a new interpreter (cold native cache), with the same 1,000
mixed record fixture. Setup is outside timings. Native/binding time includes
selection, signatures, clones, and serialization; hydration time is measured
separately. Serialized row counts are observed at the binding boundary. On the
unchanged owned path zero serialized rows also means zero native record clones
(the Rust reusable query omits that vector before the binding serializer).
"""

from __future__ import annotations

import json
import sqlite3
import statistics
import subprocess
import sys
import tempfile
import time
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from sase.core.agent_scan_facade import rebuild_agent_artifact_index
from sase.core.agent_scan_wire import agent_scan_wire_from_dict
from sase.core.rust import require_rust_binding


def fixture(base: Path, count: int) -> tuple[Path, Path, Path]:
    root = base / "projects"
    for number in range(count):
        folder = "ace-run" if number % 5 else "workflow-example"
        stamp = (datetime(2026, 11, 23) + timedelta(seconds=number)).strftime(
            "%Y%m%d%H%M%S"
        )
        path = root / "proj" / "artifacts" / folder / stamp
        path.mkdir(parents=True, exist_ok=True)
        meta = {
            "name": f"agent-{number}",
            "agent_session": f"session-{number // 4}",
            "agent_clan": f"clan-{number // 12}",
            "agent_clan_generation": "1",
            "wait_for": [f"agent-{number - 1}"] if number % 4 == 1 else [],
            "bead_id": f"fixture-{number // 4}",
            "model": "fixture-model",
        }
        (path / "agent_meta.json").write_text(json.dumps(meta))
        if number % 4 == 0:
            (path / "running.json").write_text(
                json.dumps({"pid": 99999999, "model": "fixture-model"})
            )
        elif number % 4 == 1:
            (path / "waiting.json").write_text(
                json.dumps({"wait_for": [f"agent-{number - 1}"]})
            )
        else:
            (path / "done.json").write_text(
                json.dumps(
                    {
                        "outcome": "completed",
                        "finished_at": 1_800_000_000 + number,
                        "step_output": {
                            "meta_summary": "fixture result",
                            "_raw": "x" * 256,
                        },
                    }
                )
            )
    index = base / "index.sqlite"
    rebuild_agent_artifact_index(index, root)
    marker = root / "proj/artifacts/ace-run/20261123000001/agent_meta.json"
    return index, root, marker


def measure(mode: str, index: Path, root: Path, marker: Path) -> dict[str, Any]:
    query = {
        "include_active": True,
        "include_recent_completed": True,
        "active_limit": None,
        "recent_completed_limit": None,
        "include_hidden": True,
        "freshness": "revalidate",
    }
    binding = require_rust_binding(
        "query_agent_artifact_index_reusable"
        if mode == "owned"
        else "query_agent_artifact_index"
    )
    generation = None
    records: list[Any] = []
    measurements: dict[str, list[dict[str, Any]]] = {}

    def sample(case: str) -> None:
        nonlocal generation, records
        start_wall, start_cpu = time.perf_counter(), time.process_time()
        if mode == "owned":
            envelope = binding(str(index), str(root), query, None, generation)
            payload = envelope["snapshot"]
        else:
            envelope = None
            payload = binding(str(index), str(root), query)
        binding_wall, binding_cpu = time.perf_counter(), time.process_time()
        materialized = len(payload["records"])
        snapshot = agent_scan_wire_from_dict(payload)
        if envelope is not None:
            if envelope["records_reused"]:
                assert generation == envelope["payload_generation"]
                snapshot = replace(snapshot, records=records)
            generation = envelope.get("payload_generation")
        records = snapshot.records
        assert len(records) == 1000, f"fixture returned {len(records)} rows"
        if case in ("unchanged", "unchanged_after_repair"):
            assert snapshot.stats.record_json_decoded == 0
            assert snapshot.stats.marker_signatures_checked == 1000
            assert materialized == (0 if mode == "owned" else 1000)
        else:
            assert materialized == 1000
        if case == "repaired":
            assert snapshot.stats.rows_repaired == 1
        end_wall, end_cpu = time.perf_counter(), time.process_time()
        measurements.setdefault(case, []).append(
            {
                "binding_ms": 1000 * (binding_wall - start_wall),
                "hydration_ms": 1000 * (end_wall - binding_wall),
                "wall_ms": 1000 * (end_wall - start_wall),
                "cpu_ms": 1000 * (end_cpu - start_cpu),
                "binding_cpu_ms": 1000 * (binding_cpu - start_cpu),
                "binding_materialized_rows": materialized,
                "hydrated_rows": materialized,
                "returned_rows": len(records),
                "decoded_rows": snapshot.stats.record_json_decoded,
                "marker_checks": snapshot.stats.marker_signatures_checked,
                "repaired_rows": snapshot.stats.rows_repaired,
            }
        )

    sample("cold")
    for _ in range(10):
        sample("unchanged")
    # A database-only record edit with identical filesystem marker signatures.
    with sqlite3.connect(index) as conn:
        directory, raw = conn.execute(
            "SELECT artifact_dir, record_json FROM agent_artifacts ORDER BY artifact_dir LIMIT 1"
        ).fetchone()
        value = json.loads(raw)
        value["agent_meta"]["name"] = "database-only-change"
        conn.execute(
            "UPDATE agent_artifacts SET record_json = ? WHERE artifact_dir = ?",
            (json.dumps(value), directory),
        )
    sample("database_changed")
    meta = json.loads(marker.read_text())
    meta["name"] = "changed-marker-with-a-different-length"
    marker.write_text(json.dumps(meta))
    sample("repaired")
    sample("settle")
    for _ in range(5):
        sample("unchanged_after_repair")
    return {
        "mode": mode,
        "samples": measurements,
        "medians": {
            case: {key: statistics.median(row[key] for row in rows) for key in rows[0]}
            for case, rows in measurements.items()
        },
    }


def main() -> None:
    if len(sys.argv) > 1:
        mode, index, root, marker = sys.argv[1:]
        print(json.dumps(measure(mode, Path(index), Path(root), Path(marker))))
        return
    results = []
    with tempfile.TemporaryDirectory(prefix="index-payload-bench-") as folder:
        base = Path(folder)
        for mode in ("mutable", "owned"):
            index, root, marker = fixture(base / mode, 1000)
            output = subprocess.check_output(
                [sys.executable, __file__, mode, str(index), str(root), str(marker)],
                text=True,
            )
            results.append(json.loads(output))
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
