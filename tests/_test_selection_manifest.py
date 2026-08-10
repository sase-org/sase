"""Where the selector caches state, and what identity that state is keyed to.

Split out of :mod:`tests._test_selection` so neither half grows past the
repository's per-file line budget. This half owns the on-disk manifest and the
environment fingerprint the manifest's baseline is stamped with; the selection
policy that reads and writes them lives next door.
"""

from __future__ import annotations

import importlib.util
import json
import os
from collections.abc import Mapping
from importlib.machinery import SourceFileLoader
from pathlib import Path
from types import ModuleType
from typing import Any


#: Bumped to 2 when the `contexts` block joined the manifest, to 3 when
#: `effective_depth` did, to 4 when `contexts.consulted` did, to 5 when the
#: `timings` block — the estimated serial cost of the selection, and the
#: identity of the table it was estimated from — joined it, and to 6 when
#: `baseline.environment` became a per-input map (was a single opaque digest),
#: `baseline.environment_changed_inputs` joined it, `max_serial_seconds` did,
#: and the `timings` block stopped reading `escalated` for a run that escalated
#: on that estimate, to 7 when the `gear` block — whether the middle gear was
#: offered an over-budget selection, and the worker width the suite gate granted
#: it — joined it, and to 8 when stale workspace-scoped `sase-core` env vars
#: stopped contributing the `core-cargo` fingerprint.
MANIFEST_SCHEMA = 8

SELECTION_DIRECTORY = Path(".pytest_cache") / "sase-selection"
GRAPH_CACHE_FILENAME = "graph.json"
MANIFEST_FILENAME = "manifest.json"

_WORKSPACE_SASE_CORE_DIR_ENV_VARS = (
    "SASE_LINKED_REPO_SASE_CORE_DIR",
    "SASE_SIBLING_REPO_SASE_CORE_DIR",
    "SASE_SIBLING_REPO_CORE_DIR",
)
_PRIMARY_SASE_CORE_DIR_ENV_VARS = (
    "SASE_LINKED_REPO_SASE_CORE_PRIMARY_DIR",
    "SASE_SIBLING_REPO_SASE_CORE_PRIMARY_DIR",
    "SASE_SIBLING_REPO_CORE_PRIMARY_DIR",
)
_WORKSPACE_SASE_CORE_DIR = Path("sase/repos/linked/sase-core")


def read_manifest(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def write_manifest(path: Path, manifest: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


def sase_core_directory(root: Path, environ: Mapping[str, str] | None = None) -> Path:
    """Mirror the Justfile's ``sase_core_dir`` resolution order."""
    environ = os.environ if environ is None else environ
    explicit = environ.get("SASE_CORE_DIR")
    if explicit:
        return _resolve_env_path(root, explicit)
    for name in _WORKSPACE_SASE_CORE_DIR_ENV_VARS:
        value = environ.get(name)
        if value:
            candidate = _resolve_env_path(root, value)
            if _is_relative_to(candidate, root):
                return candidate
    for name in _PRIMARY_SASE_CORE_DIR_ENV_VARS:
        value = environ.get(name)
        if value:
            return _resolve_env_path(root, value)
    workspace_checkout = root / _WORKSPACE_SASE_CORE_DIR
    if workspace_checkout.exists():
        return workspace_checkout
    return root.parent / "sase-core"


def _resolve_env_path(root: Path, value: str) -> Path:
    candidate = Path(value)
    return candidate if candidate.is_absolute() else root / candidate


def _is_relative_to(candidate: Path, root: Path) -> bool:
    try:
        candidate.relative_to(root)
    except ValueError:
        return False
    return True


def _load_validator_module(root: Path) -> ModuleType | None:
    script = root / "tools" / "validate_test_environment"
    if not script.exists():
        return None
    loader = SourceFileLoader("sase_validate_test_environment", str(script))
    spec = importlib.util.spec_from_file_location(
        "sase_validate_test_environment", script, loader=loader
    )
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception:
        return None
    return module


#: Environment inputs whose change is worth forcing the whole test suite.
#:
#: Each one either has no representation in ``git diff`` against the merge
#: base at all — the sibling ``sase-core`` repo's ``Cargo.toml``, the compiled
#: ``sase_core_rs`` extension, the venv's interpreter identity — or covers a
#: case a diff-visible rule would otherwise miss: ``pyproject.toml`` and
#: ``uv.lock`` already broaden the selection via ``packaging-config`` when
#: they are part of the current diff, but this fingerprint also catches the
#: same files changing between runs without being part of it, e.g. a
#: ``git pull`` that lands a dependency bump the working diff never touches.
#:
#: Everything else ``tools/validate_test_environment`` digests — its own
#: validator scripts and every installed package's ``dist-info`` metadata —
#: is repository tooling or environment bookkeeping, not something that
#: changes which tests exercise the diff, so it is recorded on the manifest
#: for attribution but does not escalate on its own.
ENVIRONMENT_ESCALATING_INPUTS = frozenset(
    {"pyproject", "uv-lock", "venv-config", "core-cargo", "extension", "python"}
)


def environment_fingerprint(root: Path) -> dict[str, str] | None:
    """Digest the installed environment as a small per-input map.

    Each key is a short bucket name (``pyproject``, ``extension``, the four
    ``validator:*`` scripts, ...). The Rust extension's identity is invisible
    to ``git diff`` — the wheel lives in the venv and its source lives in a
    sibling repo — so the selector reuses the per-input fingerprints
    ``tools/validate_test_environment`` already computes for its own cache
    rather than inventing a second, divergent one. An unavailable fingerprint
    is recorded as ``None``, never as a change.
    """
    module = _load_validator_module(root)
    if module is None:
        return None
    try:
        return {
            str(name): str(value)
            for name, value in module._fingerprint_inputs(
                venv_dir=root / ".venv",
                pyproject=root / "pyproject.toml",
                uv_lock=root / "uv.lock",
                sase_core_dir=sase_core_directory(root),
            ).items()
        }
    except Exception:
        return None


def environment_changed_inputs(
    current: Mapping[str, str] | None,
    previous: object,
) -> frozenset[str]:
    """Bucket names whose digest differs between two fingerprint maps.

    ``previous`` is read back from a persisted manifest, so it may be a plain
    string left by an older single-digest manifest, or missing entirely; both
    read as "nothing to compare", the same as a fresh workspace with no
    baseline at all — never as a change.
    """
    if not current or not isinstance(previous, Mapping):
        return frozenset()
    return frozenset(
        key
        for key in set(current) | set(previous)
        if current.get(key) != previous.get(key)
    )
