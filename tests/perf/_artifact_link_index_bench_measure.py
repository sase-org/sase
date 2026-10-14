"""Timing, Patch projection, capture, and CLI for the link-index bench."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import sys
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sase.ace.patch import Patch, parse_patch_project_file
from sase.ace.tui._artifact_tab_contract import compile_builtin_contract
from sase.ace.tui.models.patch_graph_index import build_patch_graph_index
from sase.ace.tui.relations import build_patches_relation_index
from sase.ace.tui.relations.artifact_links import (
    ArtifactLinksSnapshot,
    load_artifact_links_snapshot,
)
from sase.ace.tui.relations.link_index import (
    LinkIndex,
    _build_link_index,
    link_index_for_snapshot,
)
from sase.core.agent_identity_facade import AgentIdentitySnapshot
from sase.core.artifact_relations import RelationIndex
from sase.core.rust import require_rust_extension
from sase.sdd.artifact_link_store import ARTIFACT_LINK_ROW_SCHEMA_VERSION

from tests.perf._artifact_link_index_bench_fixture import (
    FIXTURE_DIR,
    fixture_patches,
    fixture_snapshot,
    identity_from_payload,
    identity_payload,
    load_fixture_input,
    patches_from_payload,
    pinned_identity,
    snapshot_from_saved_aggregate,
)
from tests.perf._artifact_link_index_bench_serialize import (
    chip_payload,
    index_enumeration_refs,
    jsonable,
    parity_diff,
    serialize_link_index,
    serialize_relation_index,
    target_payload,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]

__all__ = [
    "Timed",
    "build_parser",
    "build_patch_index",
    "capture_live_aggregate",
    "clear_link_index_cache",
    "consume_eager_index",
    "dump_json",
    "host_metadata",
    "input_hash",
    "main",
    "measure_snapshot",
    "patches_contract",
    "query_index",
    "timed_call",
    "unique_ref_count",
    "write_fixture_goldens",
]


def _thread_clock() -> float:
    clock = getattr(time, "thread_time", None)
    if clock is None:
        return time.process_time()
    return float(clock())


@dataclass(frozen=True, slots=True)
class Timed:
    """Wall and thread-CPU seconds for one measured thunk."""

    wall_s: float
    cpu_s: float
    result: Any


def timed_call(fn: Callable[[], Any]) -> Timed:
    """Time *fn* with ``perf_counter`` and ``thread_time``."""

    cpu0 = _thread_clock()
    wall0 = time.perf_counter()
    result = fn()
    return Timed(
        wall_s=time.perf_counter() - wall0,
        cpu_s=_thread_clock() - cpu0,
        result=result,
    )


def _timing_payload(sample: Timed) -> dict[str, float]:
    return {"wall_s": sample.wall_s, "cpu_s": sample.cpu_s}


def patches_contract() -> Any:
    return compile_builtin_contract("patches", label="Patch", icon="x", accent="#0")


def build_patch_index(
    snapshot: ArtifactLinksSnapshot,
    patches: Sequence[Patch],
) -> RelationIndex:
    contract = patches_contract()
    return build_patches_relation_index(
        list(patches),
        build_patch_graph_index(list(patches)),
        contract=contract,
        artifact_links=snapshot,
    )


def clear_link_index_cache() -> None:
    from sase.ace.tui.relations._native_link_index import (
        clear_native_link_index_cache,
    )

    clear_native_link_index_cache()


def consume_eager_index(
    index: LinkIndex, rows: Sequence[Mapping[str, Any]] | None = None
) -> dict[str, int]:
    """Query every chip and target the way an eager consumer does today.

    *rows* enumerates the refs to consume; production indexes are lazy
    per-ref views, so callers pass the snapshot rows they built from.
    """

    if rows is None:
        try:
            refs = list(index.by_ref.keys())  # type: ignore[union-attr]
        except TypeError:
            refs = []
        chip_count = sum(len(index.chips_for(ref)) for ref in refs)
        return {
            "chip_count": chip_count,
            "ref_count": len(refs),
            "target_count": len(refs),
        }
    refs = index_enumeration_refs(rows)
    chip_count = 0
    for ref in refs:
        chip_count += len(index.chips_for(ref))
        index.target_for(ref)
    return {
        "chip_count": chip_count,
        "ref_count": len(refs),
        "target_count": len(refs),
    }


def query_index(index: LinkIndex, refs: Sequence[str]) -> dict[str, Any]:
    chips = {ref: [chip_payload(chip) for chip in index.chips_for(ref)] for ref in refs}
    targets = {ref: target_payload(index.target_for(ref)) for ref in refs}
    return {"chips": chips, "targets": targets}


def input_hash(rows: Sequence[Mapping[str, Any]]) -> str:
    blob = json.dumps(list(rows), sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def host_metadata() -> dict[str, Any]:
    loadavg = list(os.getloadavg()) if hasattr(os, "getloadavg") else None
    core_path = _REPO_ROOT / "sase-core-revision.txt"
    try:
        core_revision = core_path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        core_revision = f"ERROR: {exc}"
    extension = require_rust_extension()
    return {
        "cpu_count": os.cpu_count(),
        "host": platform.node(),
        "interpreter": sys.version,
        "loadavg": loadavg,
        "platform": platform.platform(),
        "python": sys.executable,
        "python_version": platform.python_version(),
        "sase_core_revision": core_revision,
        "sase_core_rs": getattr(extension, "__file__", None),
        "workspace": str(_REPO_ROOT),
    }


def unique_ref_count(rows: Sequence[Mapping[str, Any]]) -> int:
    refs: set[str] = set()
    for row in rows:
        for key in ("source_ref", "target_ref"):
            value = str(row.get(key) or "").strip()
            if value:
                refs.add(value)
    return len(refs)


def measure_snapshot(
    snapshot: ArtifactLinksSnapshot,
    *,
    patches: Sequence[Patch],
    query_refs: Sequence[str],
    load_timing: Mapping[str, float] | None = None,
) -> dict[str, Any]:
    """Time cold build, eager consume, queries, Patch projection, and warm reuse."""

    clear_link_index_cache()
    cold = timed_call(lambda: _build_link_index(snapshot))
    index: LinkIndex = cold.result
    eager = timed_call(lambda: consume_eager_index(index, snapshot.rows))
    queries = timed_call(lambda: query_index(index, query_refs))
    projection = timed_call(lambda: build_patch_index(snapshot, patches))
    clear_link_index_cache()
    first_public = timed_call(lambda: link_index_for_snapshot(snapshot))
    warm = timed_call(lambda: link_index_for_snapshot(snapshot))
    counts = eager.result
    return {
        "counts": {
            "eager": counts,
            "query_refs": list(query_refs),
            "raw_ref_count": unique_ref_count(snapshot.rows),
            "raw_row_count": len(snapshot.rows),
            "relation_edge_count": len(projection.result.edges),
            "relation_target_count": len(projection.result.known_targets),
        },
        "host": host_metadata(),
        "input_hash": input_hash(snapshot.rows),
        "phases": {
            "cold_build_link_index": _timing_payload(cold),
            "eager_consume": _timing_payload(eager),
            "full_patch_projection": _timing_payload(projection),
            "input_load": dict(load_timing or {"wall_s": 0.0, "cpu_s": 0.0}),
            "public_cold_link_index_for_snapshot": _timing_payload(first_public),
            "representative_queries": _timing_payload(queries),
            "warm_reuse_link_index_for_snapshot": _timing_payload(warm),
        },
        "source_key": jsonable(snapshot.source_key),
    }


def dump_json(path: Path, payload: Any, *, indent: int | None = 2) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, indent=indent, sort_keys=True, ensure_ascii=False)
    path.write_text(text + "\n", encoding="utf-8")


def write_fixture_goldens(*, fixture_dir: Path | None = None) -> dict[str, Path]:
    """Capture current-code outputs for the sanitized fixture."""

    directory = fixture_dir or FIXTURE_DIR
    payload = load_fixture_input(directory / "input.json")
    identity = identity_from_payload(payload)
    snapshot = fixture_snapshot(payload)
    patches = fixture_patches(payload)
    with pinned_identity(identity):
        chips = serialize_link_index(_build_link_index(snapshot), snapshot.rows)
        relation = serialize_relation_index(build_patch_index(snapshot, patches))
    chips_path = directory / "expected_chips.json"
    patch_path = directory / "expected_patch_index.json"
    dump_json(chips_path, chips)
    dump_json(patch_path, relation)
    return {"chips": chips_path, "patch_index": patch_path}


def capture_live_aggregate(
    project: str,
    output_dir: Path,
    *,
    patch_file: Path | None = None,
) -> dict[str, Path]:
    """Load through ``load_artifact_links_snapshot`` and freeze a stable copy."""

    identity = AgentIdentitySnapshot.current()
    load = timed_call(lambda: load_artifact_links_snapshot(project))
    snapshot: ArtifactLinksSnapshot = load.result
    if not snapshot.rows:
        raise RuntimeError(
            f"live aggregate for {project!r} is empty; use build_synthetic_scale_rows"
        )
    spec = patch_file
    if spec is None:
        from sase.core.paths import sase_projects_dir

        spec = sase_projects_dir() / project / f"{project}.sase"
    patches = parse_patch_project_file(str(spec)) if spec.is_file() else []
    query_refs = _representative_refs(snapshot.rows)
    with pinned_identity(identity):
        report = measure_snapshot(
            snapshot,
            patches=patches,
            query_refs=query_refs,
            load_timing=_timing_payload(load),
        )
        index = _build_link_index(snapshot)
        chips = serialize_link_index(index, snapshot.rows)
        relation = serialize_relation_index(build_patch_index(snapshot, patches))
    aggregate = {
        "captured_from_project": project,
        "captured_via": "load_artifact_links_snapshot",
        "errors": list(snapshot.errors),
        "identity": identity_payload(identity),
        "patch_file": str(spec),
        "query_refs": query_refs,
        "row_count": len(snapshot.rows),
        "rows": [dict(row) for row in snapshot.rows],
        "schema_version": ARTIFACT_LINK_ROW_SCHEMA_VERSION,
        "source_key": jsonable(snapshot.source_key),
    }
    patches_payload = [
        {
            "file_path": patch.file_path,
            "name": patch.name,
            "parent": patch.parent,
            "status": patch.status,
        }
        for patch in patches
    ]
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "aggregate": output_dir / "aggregate.json",
        "expected_chips": output_dir / "expected_chips.json",
        "expected_patch_index": output_dir / "expected_patch_index.json",
        "patches": output_dir / "patches.json",
        "timings": output_dir / "timings.json",
    }
    dump_json(paths["aggregate"], aggregate, indent=None)
    dump_json(paths["expected_chips"], chips, indent=None)
    dump_json(paths["expected_patch_index"], relation)
    dump_json(paths["patches"], patches_payload)
    dump_json(
        paths["timings"],
        {
            **report,
            "identity": identity_payload(identity),
            "patch_count": len(patches),
            "patch_file": str(spec),
            "project": project,
        },
    )
    return paths


def _representative_refs(
    rows: Sequence[Mapping[str, Any]], *, limit: int = 8
) -> list[str]:
    counts: dict[str, int] = {}
    for row in rows:
        for key in ("source_ref", "target_ref"):
            value = str(row.get(key) or "").strip()
            if value:
                counts[value] = counts.get(value, 0) + 1
    ranked = sorted(counts, key=lambda ref: (-counts[ref], ref))
    refs = ranked[:limit]
    refs.append("missing:ref")
    return refs


def _cmd_write_fixture_goldens(args: argparse.Namespace) -> int:
    directory = Path(args.dir) if args.dir else FIXTURE_DIR
    paths = write_fixture_goldens(fixture_dir=directory)
    for label, path in paths.items():
        print(f"{label}: {path}")
    return 0


def _cmd_capture(args: argparse.Namespace) -> int:
    paths = capture_live_aggregate(
        args.project,
        Path(args.output_dir),
        patch_file=Path(args.patch_file) if args.patch_file else None,
    )
    for label, path in paths.items():
        print(f"{label}: {path} ({path.stat().st_size} bytes)")
    return 0


def _cmd_measure(args: argparse.Namespace) -> int:
    payload = json.loads(Path(args.aggregate).read_text(encoding="utf-8"))
    snapshot = snapshot_from_saved_aggregate(payload)
    identity = identity_from_payload(payload)
    if args.patches:
        patch_items = json.loads(Path(args.patches).read_text(encoding="utf-8"))
        patches = patches_from_payload(patch_items)
    else:
        patches = []
    query_refs = list(payload.get("query_refs") or _representative_refs(snapshot.rows))
    with pinned_identity(identity):
        report = measure_snapshot(snapshot, patches=patches, query_refs=query_refs)
    text = json.dumps(report, indent=2, sort_keys=True)
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


def _cmd_compare(args: argparse.Namespace) -> int:
    actual = json.loads(Path(args.actual).read_text(encoding="utf-8"))
    expected = json.loads(Path(args.expected).read_text(encoding="utf-8"))
    diffs = parity_diff(actual, expected)
    if not diffs:
        print("ok")
        return 0
    for line in diffs[:200]:
        print(line)
    if len(diffs) > 200:
        print(f"... {len(diffs) - 200} more")
    return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tests.perf.artifact_link_index_bench")
    sub = parser.add_subparsers(dest="command", required=True)

    write = sub.add_parser("write-fixture-goldens", help="capture sanitized goldens")
    write.add_argument("--dir", default="", help="fixture directory override")
    write.set_defaults(func=_cmd_write_fixture_goldens)

    capture = sub.add_parser("capture", help="freeze a live aggregate snapshot")
    capture.add_argument("--project", required=True)
    capture.add_argument("--output-dir", required=True)
    capture.add_argument("--patch-file", default="")
    capture.set_defaults(func=_cmd_capture)

    measure = sub.add_parser("measure", help="time a saved aggregate")
    measure.add_argument("--aggregate", required=True)
    measure.add_argument("--patches", default="")
    measure.add_argument("--output", default="")
    measure.set_defaults(func=_cmd_measure)

    compare = sub.add_parser("compare", help="diff two serialized outputs")
    compare.add_argument("--actual", required=True)
    compare.add_argument("--expected", required=True)
    compare.set_defaults(func=_cmd_compare)
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    return int(args.func(args))
