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


#: Bumped to 2 when the `contexts` block joined the manifest.
MANIFEST_SCHEMA = 2

SELECTION_DIRECTORY = Path(".pytest_cache") / "sase-selection"
GRAPH_CACHE_FILENAME = "graph.json"
MANIFEST_FILENAME = "manifest.json"

_SASE_CORE_DIR_ENV_VARS = (
    "SASE_CORE_DIR",
    "SASE_LINKED_REPO_SASE_CORE_DIR",
    "SASE_SIBLING_REPO_SASE_CORE_DIR",
    "SASE_SIBLING_REPO_CORE_DIR",
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
    for name in _SASE_CORE_DIR_ENV_VARS:
        value = environ.get(name)
        if value:
            candidate = Path(value)
            return candidate if candidate.is_absolute() else root / candidate
    workspace_checkout = root / _WORKSPACE_SASE_CORE_DIR
    if workspace_checkout.exists():
        return workspace_checkout
    return root.parent / "sase-core"


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


def environment_fingerprint(root: Path) -> str | None:
    """Digest the installed environment, including the ``sase_core_rs`` identity.

    The Rust extension's identity is invisible to ``git diff`` — the wheel
    lives in the venv and its source lives in a sibling repo — so the selector
    reuses the fingerprint ``tools/validate_test_environment`` already computes
    rather than inventing a second, divergent one. An unavailable fingerprint
    is recorded as ``None``, never as a change.
    """
    module = _load_validator_module(root)
    if module is None:
        return None
    try:
        return str(
            module._input_fingerprint(
                venv_dir=root / ".venv",
                pyproject=root / "pyproject.toml",
                uv_lock=root / "uv.lock",
                sase_core_dir=sase_core_directory(root),
            )
        )
    except Exception:
        return None
