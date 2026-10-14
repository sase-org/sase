"""Read back per-run shadow instruction manifests (E2 decision 9).

:func:`read_run_manifests` lists one :class:`_RunManifest` per ``NN``
root invocation and, when present, a second record for the matching
``NN-<provider>.helper.json`` helper bundle. Records are sorted by
sequence then root-before-helper. Missing and corrupt files are
tolerated and flagged on the record instead of raising, so the
scoreboard can report coverage over partial runs. Manifests validate
through the Rust-backed adapter and may be v1 or v2 documents.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_HELPER_MARKER = ".helper."


@dataclass(frozen=True)
class _RunManifest:
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
) -> _RunManifest:
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
    return _RunManifest(
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


def read_run_manifests(artifacts_dir: str | Path) -> list[_RunManifest]:
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
    records: list[_RunManifest] = []
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


__all__ = ["read_run_manifests"]
