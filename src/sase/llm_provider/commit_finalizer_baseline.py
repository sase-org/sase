"""Pre-existing dirty-path baseline capture for commit finalization.

Captured once at runner start, before the agent's first turn, so later
finalizer passes can tell paths that were already dirty in the workspace
apart from paths this agent's own run touched, and stop attributing
pre-existing dirt to the agent (bead sase-lb.1.6).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from .commit_finalizer_git import dirty_path_fingerprints, normalize_path

_logger = logging.getLogger(__name__)

BASELINE_FILENAME = "commit_finalizer_baseline.json"

DirtyBaseline = dict[str, dict[str, tuple[str, "str | None"]]]


def capture_dirty_baseline(project_dir: str, artifacts_dir: str) -> None:
    """Snapshot already-dirty paths before this agent's first turn.

    Best-effort only: any failure leaves no baseline file on disk, which
    makes the finalizer behave exactly as it did before baselines existed.
    """
    try:
        from .commit_finalizer_state import collect_dirty_state

        dirty_state = collect_dirty_state(
            project_dir, artifact_root=Path(artifacts_dir)
        )
        payload = {
            normalize_path(repo.path): {
                path: list(fingerprint)
                for path, fingerprint in dirty_path_fingerprints(repo.path).items()
            }
            for repo in dirty_state.repos
        }
        root = Path(artifacts_dir)
        root.mkdir(parents=True, exist_ok=True)
        (root / BASELINE_FILENAME).write_text(
            json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8"
        )
    except Exception:
        _logger.warning(
            "Failed to capture commit finalizer dirty-path baseline", exc_info=True
        )


def load_dirty_baseline(artifact_root: Path | None) -> DirtyBaseline | None:
    """Load the baseline :func:`capture_dirty_baseline` wrote, if any.

    Returns ``None`` on a missing, unreadable, or malformed baseline file so
    callers degrade to pre-baseline behavior rather than raising.
    """
    if artifact_root is None:
        return None
    try:
        raw = (Path(artifact_root) / BASELINE_FILENAME).read_text(encoding="utf-8")
        data = json.loads(raw)
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None

    baseline: DirtyBaseline = {}
    for repo_path, entries in data.items():
        if not isinstance(repo_path, str) or not isinstance(entries, dict):
            return None
        repo_entries: dict[str, tuple[str, str | None]] = {}
        for path, fingerprint in entries.items():
            if not _is_valid_fingerprint_entry(path, fingerprint):
                return None
            repo_entries[path] = (fingerprint[0], fingerprint[1])
        baseline[repo_path] = repo_entries
    return baseline


def _is_valid_fingerprint_entry(path: object, fingerprint: object) -> bool:
    return (
        isinstance(path, str)
        and isinstance(fingerprint, list)
        and len(fingerprint) == 2
        and isinstance(fingerprint[0], str)
        and (fingerprint[1] is None or isinstance(fingerprint[1], str))
    )
