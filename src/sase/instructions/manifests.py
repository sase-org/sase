"""Read back per-run shadow instruction manifests (E2 decision 9).

:func:`read_run_manifests` lists one :class:`RunManifest` per ``NN``
root invocation and, when present, a second record for the matching
``NN-<provider>.helper.json`` helper bundle. Records are sorted by
sequence then root-before-helper. Missing and corrupt files are
tolerated and flagged on the record instead of raising, so the
scoreboard can report coverage over partial runs. Manifests validate
through the Rust-backed adapter and may be v1 or v2 documents.

:func:`launch_root_bundle` is the public locator for the recorded root
bundle a TUI launch row should open: the lowest-sequence non-helper
manifest that still has a bundle path, plus its delivery status and
integrity check.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_HELPER_MARKER = ".helper."


@dataclass(frozen=True)
class RunManifest:
    """One per-invocation shadow record, possibly partial."""

    seq: int
    provider: str
    bundle_path: Path | None
    manifest_path: Path | None
    manifest: dict[str, Any] | None
    error: dict[str, Any] | None = None
    problems: tuple[str, ...] = field(default_factory=tuple)
    is_helper: bool = False
    actor: str = ""
    parent_invocation_id: str | None = None
    raw: dict[str, Any] | None = None


@dataclass(frozen=True)
class BundleIntegrity:
    """Result of comparing stored bundle bytes to the manifest digest."""

    label: str
    data: bytes | None
    source: str
    expected_sha: str
    actual_sha: str | None

    @property
    def ok(self) -> bool:
        return self.label == "bytes match"


@dataclass(frozen=True)
class LaunchRootBundle:
    """Lowest-sequence non-helper recorded bundle for one run."""

    entry: RunManifest
    delivery_status: str
    integrity: BundleIntegrity

    @property
    def is_explicit(self) -> bool:
        return self.delivery_status == "explicit"


def _read_json(path: Path) -> tuple[Any | None, str | None]:
    """Return ``(payload, problem)`` for *path*; never raises."""
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle), None
    except FileNotFoundError:
        return None, f"missing {path.name}"
    except (json.JSONDecodeError, OSError, ValueError) as exc:
        return None, f"corrupt {path.name}: {exc}"


def _parse_instruction_name(name: str) -> tuple[int, str] | None:
    """Return ``(seq, role)`` for an instructions filename, or ``None``."""
    prefix, sep, rest = name.partition("-")
    if not sep or len(prefix) != 2 or not prefix.isdigit() or not rest:
        return None
    role = "helper" if _HELPER_MARKER in rest else "root"
    return int(prefix), role


def _record_from_group(
    *,
    seq: int,
    is_helper: bool,
    files: dict[str, Path],
    prefix: str,
) -> RunManifest:
    from sase.core.instruction_manifest import normalize_instruction_manifest

    manifest_file: Path | None = None
    manifest: dict[str, Any] | None = None
    raw_payload: dict[str, Any] | None = None
    error: dict[str, Any] | None = None
    problems: list[str] = []
    provider = "unknown"
    actor = ""
    parent_invocation_id: str | None = None
    manifest_path = next(
        (
            path
            for rest, path in files.items()
            if rest.endswith(".json") and not rest.endswith(".error.json")
        ),
        None,
    )
    if manifest_path is not None:
        manifest_file = manifest_path
        payload, problem = _read_json(manifest_path)
        if problem is not None:
            problems.append(problem)
        elif isinstance(payload, dict):
            raw_payload = payload
            try:
                manifest = normalize_instruction_manifest(payload)
            except Exception as exc:  # noqa: BLE001 - flagged, not raised.
                problems.append(f"invalid {manifest_path.name}: {exc}")
        else:
            problems.append(f"corrupt {manifest_path.name}: not an object")
        source = manifest if manifest is not None else raw_payload
        if isinstance(source, dict):
            facts = source.get("facts")
            if isinstance(facts, dict):
                raw = facts.get("provider")
                if isinstance(raw, str) and raw:
                    provider = raw
                raw_actor = facts.get("actor")
                if isinstance(raw_actor, str) and raw_actor:
                    actor = raw_actor
            delivery = source.get("delivery")
            if isinstance(delivery, dict):
                raw_parent = delivery.get("parent_invocation_id")
                if isinstance(raw_parent, str) and raw_parent:
                    parent_invocation_id = raw_parent
    error_path = next(
        (path for rest, path in files.items() if rest.endswith(".error.json")),
        None,
    )
    if error_path is not None:
        payload, problem = _read_json(error_path)
        if problem is not None:
            problems.append(problem)
        elif isinstance(payload, dict):
            error = payload
        else:
            problems.append(f"corrupt {error_path.name}: not an object")
    bundle_path = next(
        (path for rest, path in files.items() if rest.endswith(".md")),
        None,
    )
    if manifest_file is None and error is None:
        kind = "helper " if is_helper else ""
        problems.append(f"no {kind}manifest or error record for sequence {prefix}")
    if not actor:
        actor = "native_helper" if is_helper else ""
    return RunManifest(
        seq=seq,
        provider=provider,
        bundle_path=bundle_path,
        manifest_path=manifest_file,
        manifest=manifest,
        error=error,
        problems=tuple(problems),
        is_helper=is_helper,
        actor=actor,
        parent_invocation_id=parent_invocation_id,
        raw=raw_payload,
    )


def read_run_manifests(artifacts_dir: str | Path) -> list[RunManifest]:
    """Return the shadow records under ``<artifacts>/instructions/`` by seq."""
    instructions_dir = Path(artifacts_dir) / "instructions"
    try:
        names = sorted(child.name for child in instructions_dir.iterdir())
    except OSError:
        return []
    groups: dict[tuple[int, str], dict[str, Path]] = {}
    for name in names:
        parsed = _parse_instruction_name(name)
        if parsed is None:
            continue
        seq, role = parsed
        groups.setdefault((seq, role), {})[name.partition("-")[2]] = (
            instructions_dir / name
        )
    records: list[RunManifest] = []
    for seq, role in sorted(groups, key=lambda item: (item[0], item[1] != "root")):
        files = groups[(seq, role)]
        records.append(
            _record_from_group(
                seq=seq,
                is_helper=role == "helper",
                files=files,
                prefix=f"{seq:02d}",
            )
        )
    return records


def _payload(entry: RunManifest) -> dict[str, Any] | None:
    if isinstance(entry.manifest, dict):
        return entry.manifest
    if isinstance(entry.raw, dict):
        return entry.raw
    return None


def _delivery_status(entry: RunManifest) -> str:
    """Return the recorded delivery status, or ``""`` when absent."""
    payload = _payload(entry)
    if not isinstance(payload, dict):
        return ""
    delivery = payload.get("delivery")
    if not isinstance(delivery, dict):
        return ""
    raw = delivery.get("status")
    return raw if isinstance(raw, str) else ""


def delivery_channel(entry: RunManifest) -> str:
    """Return the recorded delivery channel, or ``""`` when absent."""
    payload = _payload(entry)
    if not isinstance(payload, dict):
        return ""
    delivery = payload.get("delivery")
    if not isinstance(delivery, dict):
        return ""
    raw = delivery.get("channel")
    return raw if isinstance(raw, str) else ""


def bundle_size(entry: RunManifest) -> int:
    """Return the recorded bundle byte count, or ``0`` when absent."""
    payload = _payload(entry)
    if not isinstance(payload, dict):
        return 0
    bundle = payload.get("bundle")
    if not isinstance(bundle, dict):
        return 0
    raw = bundle.get("bytes")
    return raw if isinstance(raw, int) else 0


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read_bytes(path: Path) -> bytes | None:
    try:
        return path.read_bytes()
    except OSError:
        return None


def check_bundle_integrity(entry: RunManifest) -> BundleIntegrity:
    """Sha256 the run copy, falling back to ``bundle.store_path``."""
    expected = ""
    store_path: str | None = None
    payload = _payload(entry)
    if isinstance(payload, dict):
        bundle = payload.get("bundle")
        if isinstance(bundle, dict):
            raw_sha = bundle.get("sha256")
            if isinstance(raw_sha, str):
                expected = raw_sha
            raw_store = bundle.get("store_path")
            if isinstance(raw_store, str) and raw_store:
                store_path = raw_store
    data: bytes | None = None
    source = "missing"
    if entry.bundle_path is not None:
        data = _read_bytes(entry.bundle_path)
        if data is not None:
            source = "run"
    if data is None and store_path:
        data = _read_bytes(Path(store_path).expanduser())
        if data is not None:
            source = "store"
    if data is None:
        return BundleIntegrity(
            label="missing",
            data=None,
            source=source,
            expected_sha=expected,
            actual_sha=None,
        )
    actual = _sha256_bytes(data)
    label = "bytes match" if expected and actual == expected else "MISMATCH"
    if not expected:
        label = "MISMATCH"
    return BundleIntegrity(
        label=label,
        data=data,
        source=source,
        expected_sha=expected,
        actual_sha=actual,
    )


def run_bundle_paths(artifacts_dir: str | Path) -> tuple[str, ...]:
    """Return root-then-helper bundle paths under ``<artifacts>/instructions/``."""
    return tuple(
        str(entry.bundle_path)
        for entry in read_run_manifests(artifacts_dir)
        if entry.bundle_path is not None
    )


def launch_root_bundle(artifacts_dir: str | Path) -> LaunchRootBundle | None:
    """Return the lowest-sequence non-helper recorded bundle, if any.

    Helpers are skipped. A root record without a bundle path is skipped so
    a later root that still has bytes can win. Integrity is always
    computed for the chosen record.
    """
    candidates = [
        entry
        for entry in read_run_manifests(artifacts_dir)
        if not entry.is_helper and entry.bundle_path is not None
    ]
    if not candidates:
        return None
    chosen = min(candidates, key=lambda entry: entry.seq)
    return LaunchRootBundle(
        entry=chosen,
        delivery_status=_delivery_status(chosen),
        integrity=check_bundle_integrity(chosen),
    )


__all__ = [
    "BundleIntegrity",
    "LaunchRootBundle",
    "RunManifest",
    "bundle_size",
    "check_bundle_integrity",
    "delivery_channel",
    "launch_root_bundle",
    "read_run_manifests",
    "run_bundle_paths",
]
