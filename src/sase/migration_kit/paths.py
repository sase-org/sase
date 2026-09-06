"""Filesystem locations the migration kit reads and writes.

TEMPORARY MODULE: deletion owner sase-x7.14.
"""

from __future__ import annotations

import os
from pathlib import Path

CUTOVER_BACKUP_DIR_ENV_VAR = "SASE_CUTOVER_BACKUP_DIR"
DEFAULT_CUTOVER_BACKUP_DIRNAME = "cutover-backups"
CUTOVER_BACKUP_ROOT_MODE = 0o700

# Home-relative prefixes every SASE runtime root shares. The cutover backup
# root must never fall under any of these, so no discovery glob and no purge
# operation can ever reach a backup. Expanded against the real home directory
# at check time in :func:`is_contained_backup_root`, since the check is a
# path-prefix check (not a filesystem check) that must catch the mistake even
# when the directories involved do not yet exist.
RUNTIME_ROOT_PREFIXES: tuple[str, ...] = (
    "~/.sase",
    "~/.local/state/sase",
    "~/sase",
)


def _default_cutover_backup_root() -> Path:
    """Return the unresolved default backup root, ignoring any override.

    Exists so the write-containment invariant test can check the *default*
    independently of whatever a caller's environment happens to override.
    """
    return Path("~") / DEFAULT_CUTOVER_BACKUP_DIRNAME


def is_contained_backup_root(root: Path) -> bool:
    """Return whether *root* shares no path prefix with any runtime root.

    Both sides are expanded (``~`` resolved against the real home directory)
    before comparing, so this gives the same answer whether *root* is the
    unexpanded default or an already-expanded, already-created directory.
    """
    root_str = str(Path(root).expanduser())
    prefixes = (str(Path(prefix).expanduser()) for prefix in RUNTIME_ROOT_PREFIXES)
    return not any(
        root_str == prefix or root_str.startswith(prefix + os.sep)
        for prefix in prefixes
    )


def _cutover_backup_root() -> Path:
    """Return the root every backup and run manifest is written under.

    Honors ``$SASE_CUTOVER_BACKUP_DIR`` when set; otherwise defaults to
    ``$HOME/cutover-backups``. Deliberately outside every SASE runtime root
    (``$SASE_HOME``, ``~/.local/state/sase``, ``~/sase`` checkouts). Created
    with mode 0700 on first resolution.
    """
    override = os.environ.get(CUTOVER_BACKUP_DIR_ENV_VAR, "").strip()
    root = (
        Path(override).expanduser()
        if override
        else _default_cutover_backup_root().expanduser()
    )
    root.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(root, CUTOVER_BACKUP_ROOT_MODE)
    except OSError:
        pass
    return root


def _ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def backups_dir() -> Path:
    """Return the directory holding every captured backup, by backup id."""
    return _ensure_dir(_cutover_backup_root() / "backups")


def restores_dir() -> Path:
    """Return the directory holding staged (and, once applied, prior) restores."""
    return _ensure_dir(_cutover_backup_root() / "restores")


def runs_dir() -> Path:
    """Return the directory holding migration manifests, journals, and receipts."""
    return _ensure_dir(_cutover_backup_root() / "runs")


def backup_dir(backup_id: str) -> Path:
    """Return the directory for one specific backup id."""
    return backups_dir() / backup_id


def backup_payload_dir(backup_id: str) -> Path:
    """Return the payload subtree of one backup, mirroring the source root."""
    return backup_dir(backup_id) / "payload"


def run_dir(run_id: str) -> Path:
    """Return the durable directory for one planned or applied migration run."""
    return runs_dir() / run_id


def run_manifest_path(run_id: str) -> Path:
    """Return the manifest path for one migration run."""
    return run_dir(run_id) / "manifest.json"


def run_journal_path(run_id: str) -> Path:
    """Return the append-only journal path for one migration run."""
    return run_dir(run_id) / "journal.jsonl"


def run_lock_path(run_id: str) -> Path:
    """Return the bounded lock path for one migration run."""
    return run_dir(run_id) / "run.lock"


def run_receipt_path(run_id: str) -> Path:
    """Return the final receipt path for one migration run."""
    return run_dir(run_id) / "receipt.json"


def operation_archive_dir(
    backup_id: str,
    *,
    run_id: str,
    operation: str,
    action_id: str,
) -> Path:
    """Return the per-action archive directory inside a verified backup tree."""
    return backup_dir(backup_id) / "migration-archives" / run_id / operation / action_id
