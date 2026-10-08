"""Read back per-run shadow instruction manifests (E2 decision 9).

:func:`read_run_manifests` lists one :class:`_RunManifest` per ``NN`` sequence
in ``<artifacts>/instructions/``, sorted by sequence. Missing and corrupt
files are tolerated and flagged on the record instead of raising, so the
scoreboard can report coverage over partial runs. Manifests validate
through the Rust-backed adapter.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


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


def _read_json(path: Path) -> tuple[Any | None, str | None]:
    """Return ``(payload, problem)`` for *path*; never raises."""
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle), None
    except FileNotFoundError:
        return None, f"missing {path.name}"
    except (json.JSONDecodeError, OSError, ValueError) as exc:
        return None, f"corrupt {path.name}: {exc}"


def read_run_manifests(artifacts_dir: str | Path) -> list[_RunManifest]:
    """Return the shadow records under ``<artifacts>/instructions/`` by seq."""
    from sase.core.instruction_manifest import normalize_instruction_manifest

    instructions_dir = Path(artifacts_dir) / "instructions"
    try:
        names = sorted(child.name for child in instructions_dir.iterdir())
    except OSError:
        return []
    groups: dict[str, dict[str, Path]] = {}
    for name in names:
        prefix, _, rest = name.partition("-")
        if len(prefix) != 2 or not prefix.isdigit():
            continue
        groups.setdefault(prefix, {})[rest] = instructions_dir / name
    records: list[_RunManifest] = []
    for prefix in sorted(groups):
        files = groups[prefix]
        seq = int(prefix)
        manifest_file: Path | None = None
        manifest: dict[str, Any] | None = None
        error: dict[str, Any] | None = None
        problems: list[str] = []
        provider = "unknown"
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
                try:
                    manifest = normalize_instruction_manifest(payload)
                except Exception as exc:  # noqa: BLE001 - flagged, not raised.
                    problems.append(f"invalid {manifest_path.name}: {exc}")
            else:
                problems.append(f"corrupt {manifest_path.name}: not an object")
            if manifest is not None:
                facts = manifest.get("facts")
                if isinstance(facts, dict):
                    raw = facts.get("provider")
                    if isinstance(raw, str) and raw:
                        provider = raw
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
            problems.append(f"no manifest or error record for sequence {prefix}")
        records.append(
            _RunManifest(
                seq=seq,
                provider=provider,
                bundle_path=bundle_path,
                manifest_path=manifest_file,
                manifest=manifest,
                error=error,
                problems=tuple(problems),
            )
        )
    return records


__all__ = ["_RunManifest", "read_run_manifests"]
