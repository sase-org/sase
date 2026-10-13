"""Reusable artifact-link index parity comparison and timing helper.

Phase ``parity-baseline`` (bead:sase-1kj.8.1.1) of
``plan:202610/artifact_link_inverted_index.md``. Later native-index and
python-integration phases import this module against the same saved
aggregate and the committed sanitized fixture.

Public entry points today are ``load_artifact_links_snapshot``,
``_build_link_index``, ``link_index_for_snapshot``, and
``build_patches_relation_index``. Cold construction is timed through
``_build_link_index``; warm reuse through ``link_index_for_snapshot``.
Eager-consumer work (walking ``by_ref`` / ``targets_by_ref``) is timed
separately so a later lazy handle cannot report deferred chip work as
eliminated.

Run::

    .venv/bin/python -m tests.perf.artifact_link_index_bench write-fixture-goldens
    .venv/bin/python -m tests.perf.artifact_link_index_bench capture \\
        --project gh_sase-org__sase --output-dir /tmp/artifact-link-parity
    .venv/bin/python -m tests.perf.artifact_link_index_bench measure \\
        --aggregate /path/to/aggregate.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import sys
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from collections.abc import Iterator

from sase.ace.patch import Patch, parse_patch_project_file
from sase.ace.tui._artifact_tab_contract import compile_builtin_contract
from sase.ace.tui.artifact_tabs import reset_artifacts_subtabs_cache
from sase.ace.tui.models.patch_graph_index import build_patch_graph_index
from sase.ace.tui.relations import build_patches_relation_index
from sase.ace.tui.relations.artifact_links import (
    ArtifactLinksSnapshot,
    load_artifact_links_snapshot,
)
from sase.ace.tui.relations.link_index import (
    LinkChip,
    LinkIndex,
    _build_link_index,
    link_index_for_snapshot,
)
from sase.core.agent_identity_facade import AgentIdentitySnapshot, AgentOwnerIdentity
from sase.core.artifact_entry_target import ArtifactEntryTarget
from sase.core.artifact_relations import RelationDiagnostic, RelationEdge, RelationIndex
from sase.core.rust import require_rust_extension
from sase.sdd.artifact_link_store import ARTIFACT_LINK_ROW_SCHEMA_VERSION

_REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_DIR = _REPO_ROOT / "tests" / "ace" / "tui" / "fixtures" / "artifact_link_parity"
FIXTURE_INPUT_PATH = FIXTURE_DIR / "input.json"
FIXTURE_CHIPS_PATH = FIXTURE_DIR / "expected_chips.json"
FIXTURE_PATCH_INDEX_PATH = FIXTURE_DIR / "expected_patch_index.json"
SYNTHETIC_SCALE_ROWS = 45_000


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


def target_payload(target: ArtifactEntryTarget | None) -> dict[str, Any] | None:
    """Normalize a target to a JSON object, or ``None``."""

    if target is None:
        return None
    return {"pane_id": target.pane_id, "parts": list(target.parts)}


def chip_payload(chip: LinkChip) -> dict[str, Any]:
    """Pin every :class:`LinkChip` field."""

    return {
        "accent": chip.accent,
        "created_at": chip.created_at,
        "created_by": chip.created_by,
        "directed": chip.directed,
        "icon": chip.icon,
        "label": chip.label,
        "neighbor_ref": chip.neighbor_ref,
        "neighbor_target": target_payload(chip.neighbor_target),
        "origin": chip.origin,
        "relation": chip.relation,
        "this_is_source": chip.this_is_source,
        "uses": chip.uses,
        "why": chip.why,
        "writable": chip.writable,
    }


def edge_payload(edge: RelationEdge) -> dict[str, Any]:
    """Pin every :class:`RelationEdge` field."""

    return {
        "dangling": edge.dangling,
        "derived": edge.derived,
        "description": edge.description,
        "kind": edge.kind.value,
        "label": edge.label,
        "origin": edge.origin,
        "relation": edge.relation,
        "source": target_payload(edge.source),
        "target": target_payload(edge.target),
        "uses": edge.uses,
    }


def diagnostic_payload(item: RelationDiagnostic) -> dict[str, Any]:
    return {
        "code": item.code,
        "message": item.message,
        "relation": item.relation,
        "target": target_payload(item.target),
    }


def serialize_link_index(index: LinkIndex) -> dict[str, Any]:
    """Stable JSON form of chips and targets, keyed in sorted ref order."""

    return {
        "by_ref": {
            ref: [chip_payload(chip) for chip in chips]
            for ref, chips in sorted(index.by_ref.items())
        },
        "source_key": _jsonable(index.source_key),
        "targets_by_ref": {
            ref: target_payload(target)
            for ref, target in sorted(index.targets_by_ref.items())
        },
    }


def serialize_relation_index(index: RelationIndex) -> dict[str, Any]:
    """Stable JSON form of Patch ``RelationIndex`` edges and targets."""

    known: list[dict[str, Any]] = []
    for target in index.known_targets:
        payload = target_payload(target)
        if payload is not None:
            known.append(payload)
    known.sort(key=lambda item: (str(item["pane_id"]), list(item["parts"])))
    return {
        "diagnostics": [diagnostic_payload(item) for item in index.diagnostics],
        "edges": [edge_payload(edge) for edge in index.edges],
        "known_targets": known,
        "pane_id": index.pane_id,
    }


def parity_diff(actual: Any, expected: Any, *, path: str = "$") -> list[str]:
    """Return human-readable mismatch lines; empty means equal."""

    if type(actual) is not type(expected) and not (
        isinstance(actual, (int, float)) and isinstance(expected, (int, float))
    ):
        return [f"{path}: type {type(actual).__name__} != {type(expected).__name__}"]
    if isinstance(actual, dict):
        diffs: list[str] = []
        actual_keys = set(actual)
        expected_keys = set(expected)
        for key in sorted(actual_keys - expected_keys):
            diffs.append(f"{path}.{key}: unexpected key")
        for key in sorted(expected_keys - actual_keys):
            diffs.append(f"{path}.{key}: missing key")
        for key in sorted(actual_keys & expected_keys):
            diffs.extend(parity_diff(actual[key], expected[key], path=f"{path}.{key}"))
        return diffs
    if isinstance(actual, list):
        diffs = []
        if len(actual) != len(expected):
            diffs.append(f"{path}: len {len(actual)} != {len(expected)}")
        for index, (left, right) in enumerate(zip(actual, expected, strict=False)):
            diffs.extend(parity_diff(left, right, path=f"{path}[{index}]"))
        return diffs
    if actual != expected:
        return [f"{path}: {actual!r} != {expected!r}"]
    return []


def _jsonable(value: Any) -> Any:
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    return value


def source_key_from_payload(value: Any) -> tuple[object, ...]:
    if not isinstance(value, (list, tuple)):
        return (value,)
    return tuple(tuple(item) if isinstance(item, list) else item for item in value)


def load_fixture_input(path: Path | None = None) -> dict[str, Any]:
    target = path or FIXTURE_INPUT_PATH
    return json.loads(target.read_text(encoding="utf-8"))


def identity_from_payload(payload: Mapping[str, Any]) -> AgentIdentitySnapshot:
    identity = payload.get("identity") or {}
    username = str(identity.get("username") or "alice")
    machine = str(identity.get("machine_name") or "athena")
    siblings = tuple(identity.get("sibling_machines") or (machine,))
    roots = tuple(identity.get("known_owner_roots") or ())
    return AgentIdentitySnapshot(
        AgentOwnerIdentity(username, machine),
        siblings,
        roots,
    )


def identity_payload(identity: AgentIdentitySnapshot) -> dict[str, Any]:
    owner = identity.owner
    return {
        "known_owner_roots": list(identity.known_owner_roots),
        "machine_name": None if owner is None else owner.machine_name,
        "sibling_machines": list(identity.sibling_machines),
        "username": None if owner is None else owner.username,
    }


@contextmanager
def pinned_identity(identity: AgentIdentitySnapshot) -> Iterator[None]:
    """Force identity and pane-descriptor style for deterministic chips.

    Unknown document kinds (`ref:research`, ...) otherwise hash a live
    provider palette. The fixture pins them to the no-descriptor fallback
    (external accent/icon) so tests, golden capture, and later phases agree.
    """

    from sase.ace.tui import artifact_tabs

    original = AgentIdentitySnapshot.current
    original_descriptor = artifact_tabs.descriptor_for_artifacts_pane_id

    @classmethod  # type: ignore[misc]
    def _current(_cls: type[AgentIdentitySnapshot]) -> AgentIdentitySnapshot:
        return identity

    def _no_descriptor(_pane_id: str) -> None:
        return None

    AgentIdentitySnapshot.current = _current  # type: ignore[method-assign]
    artifact_tabs.descriptor_for_artifacts_pane_id = _no_descriptor
    try:
        reset_artifacts_subtabs_cache()
        yield
    finally:
        AgentIdentitySnapshot.current = original  # type: ignore[method-assign]
        artifact_tabs.descriptor_for_artifacts_pane_id = original_descriptor
        reset_artifacts_subtabs_cache()


def patches_from_payload(items: Sequence[Mapping[str, Any]]) -> list[Patch]:
    return [
        Patch(
            name=str(item["name"]),
            description=str(item.get("description") or "d"),
            parent=item.get("parent"),
            status=str(item.get("status") or "Ready"),
            file_path=str(item["file_path"]),
            line_number=int(item.get("line_number") or 1),
        )
        for item in items
    ]


def snapshot_from_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    source_key: tuple[object, ...] = ("artifact-link-parity",),
    errors: tuple[str, ...] = (),
) -> ArtifactLinksSnapshot:
    return ArtifactLinksSnapshot(
        rows=tuple(dict(row) for row in rows),
        source_key=source_key,
        errors=errors,
    )


def snapshot_from_saved_aggregate(payload: Mapping[str, Any]) -> ArtifactLinksSnapshot:
    """Rebuild a snapshot from a durable capture (not a live sidecar read)."""

    rows = payload.get("rows")
    if not isinstance(rows, list):
        raise ValueError("saved aggregate rows must be a list")
    return snapshot_from_rows(
        rows,
        source_key=source_key_from_payload(payload.get("source_key") or ()),
        errors=tuple(payload.get("errors") or ()),
    )


def load_saved_aggregate(path: Path) -> ArtifactLinksSnapshot:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError(f"saved aggregate is not an object: {path}")
    return snapshot_from_saved_aggregate(payload)


def fixture_snapshot(payload: Mapping[str, Any] | None = None) -> ArtifactLinksSnapshot:
    data = payload if payload is not None else load_fixture_input()
    return snapshot_from_rows(
        data["rows"],
        source_key=source_key_from_payload(
            data.get("source_key") or ["artifact-link-parity"]
        ),
    )


def fixture_patches(payload: Mapping[str, Any] | None = None) -> list[Patch]:
    data = payload if payload is not None else load_fixture_input()
    return patches_from_payload(data.get("patches") or ())


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
    from sase.ace.tui.relations import link_index as link_index_mod

    with link_index_mod._INDEX_CACHE_LOCK:
        link_index_mod._INDEX_CACHE.clear()


def consume_eager_index(index: LinkIndex) -> dict[str, int]:
    """Walk every chip and target the way an eager consumer does today."""

    chip_count = 0
    for chips in index.by_ref.values():
        chip_count += len(chips)
    target_count = len(index.targets_by_ref)
    return {
        "chip_count": chip_count,
        "ref_count": len(index.by_ref),
        "target_count": target_count,
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
    eager = timed_call(lambda: consume_eager_index(index))
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
        "source_key": _jsonable(snapshot.source_key),
    }


def build_synthetic_scale_rows(
    n: int = SYNTHETIC_SCALE_ROWS,
) -> tuple[dict[str, Any], ...]:
    """Representative synthetic aggregate when no nonempty real file exists."""

    rows: list[dict[str, Any]] = []
    relations = ("related", "cites", "implements", "read", "derives-from")
    for index in range(n):
        relation = relations[index % len(relations)]
        rows.append(
            {
                "_project": "alpha" if index % 2 == 0 else "beta",
                "created_at": "2026-01-01T00:00:00Z",
                "created_by": "synthetic",
                "description": "",
                "origin": "manual" if index % 11 else "projected",
                "relation": relation,
                "source_ref": f"bead:sase-syn-{index % 500}",
                "target_ref": f"plan:202608/syn-{index}.md",
                "uses": index % 7,
            }
        )
    return tuple(rows)


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
        chips = serialize_link_index(_build_link_index(snapshot))
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
        chips = serialize_link_index(index)
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
        "source_key": _jsonable(snapshot.source_key),
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


if __name__ == "__main__":
    raise SystemExit(main())
