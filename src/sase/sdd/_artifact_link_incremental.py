"""Cheap input fingerprints that let the hourly artifact-link jobs skip no-op work.

The ``artifact_link_backfill`` chop repeats three expensive passes every hour
even when nothing they read has changed:

- the derivation sweep walks every ``plan:``/``research:`` document;
- the cross-workspace aggregate reconcile re-reduces every durable and pending
  link event of every reconciliation store (tens of seconds on a large
  project);
- the dangling-ref repair runs a full-history ``git log -M`` rename scan.

Each function here folds what one pass reads into a short digest built from
file identities (path, size, mtime, inode) and git ref heads, never from file
contents, so computing it costs a stat walk instead of the pass itself. The
chop persists the digest a pass finished with and skips the pass while the
digest is unchanged; a daily full pass stays as the backstop for anything a
fingerprint cannot see.

Every function fails open: an error yields ``None``, which never matches a
recorded digest, so the caller simply runs the full pass.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
from typing import Any

from sase.sdd._artifact_link_store_support import is_projected_row
from sase.sdd.referenced_by_index import REFERENCED_BY_LINKS_DIR

# Bump when the set of inputs a fingerprint covers changes, so a digest an
# older chop recorded can never vouch for a newer pass.
_FINGERPRINT_VERSION = "1"
_LINK_EVENTS_DIRNAME = "link-events"
_BEAD_TRUTH_SKIP_NAMES = frozenset({"pages", "assets"})
_BEAD_TRUTH_SKIP_PREFIXES = ("beads.db",)
FULL_PASS_INTERVAL_SECONDS = 24 * 60 * 60
"""A pass whose last full run is this old runs again even when unchanged."""


@dataclass
class ArtifactLinkReconcileMemo:
    """Persisted per-project skip state for ``reconcile_and_repair``.

    ``input_fingerprint`` is the reconcile-input digest plus the store-backed
    aggregate digest that the last complete reconcile left behind;
    ``unrepairable_refs`` is the dangling-ref set plus sidecar ref heads whose
    rename scan last found nothing to repair; ``full_pass_at`` is the wall
    time of the last complete, non-skipped reconcile.
    """

    input_fingerprint: str | None = None
    unrepairable_refs: str | None = None
    full_pass_at: float | None = None

    def full_pass_due(self, *, now: float) -> bool:
        return (
            self.full_pass_at is None
            or now - self.full_pass_at >= FULL_PASS_INTERVAL_SECONDS
        )

    def to_json(self) -> dict[str, Any]:
        return {
            "input_fingerprint": self.input_fingerprint,
            "unrepairable_refs": self.unrepairable_refs,
            "full_pass_at": self.full_pass_at,
        }

    @classmethod
    def from_json(cls, value: object) -> ArtifactLinkReconcileMemo:
        if not isinstance(value, Mapping):
            return cls()
        return cls(
            input_fingerprint=_optional_str(value.get("input_fingerprint")),
            unrepairable_refs=_optional_str(value.get("unrepairable_refs")),
            full_pass_at=_optional_float(value.get("full_pass_at")),
        )


def document_sweep_fingerprint(store: Any) -> str | None:
    """Digest the document paths the derivation sweep's ``rglob`` could see.

    Covers every ``*.md`` path under each configured ``plan``/``research``
    sidecar root, minus dot directories and the ``links/`` indexes. Only
    paths count: the sweep keys its checkpoint by ref, so editing an
    already-swept document never makes it pending again, while adding,
    removing, or renaming one does.
    """

    try:
        digest = _new_digest("sweep")
        for kind in ("plan", "research"):
            root = store.sidecar_roots.get(kind)
            digest.update(f"root\0{kind}\0".encode())
            if root is None:
                digest.update(b"none\0")
                continue
            _fold_tree(
                digest,
                Path(root).expanduser().resolve(strict=False),
                skip_names=frozenset({REFERENCED_BY_LINKS_DIR}),
                suffix=".md",
                paths_only=True,
            )
        return digest.hexdigest()
    except Exception:  # noqa: BLE001 - fail open into a full sweep.
        return None


def reconcile_input_fingerprint(store: Any) -> str | None:
    """Digest every input ``reconcile_aggregate`` reduces, minus projection.

    For each reconciliation store (the hidden clones plus the primary
    checkout) this folds the store identity, every file under each event
    root's ``link-events/`` tree (durable objects, quarantine, admission
    records), the legacy ``links/`` indexes while they are still read, and
    the bead store's event truth. The local store also contributes its
    pending outbox version. Projection inputs (agents sidecar, primary repo)
    are deliberately excluded: the skip path recomputes projected rows on
    its own, so their churn never forces the expensive event reduction.
    """

    try:
        from sase.sdd._artifact_link_event_local_store import (
            artifact_link_local_event_root,
        )
        from sase.sdd._artifact_link_outbox_io import artifact_link_outbox_read_scope

        digest = _new_digest("reconcile")
        project_key = str(store.project_key)
        for candidate in store._iter_reconciliation_stores():  # noqa: SLF001
            digest.update(repr(candidate._store_identity()).encode())  # noqa: SLF001
            roots = [
                Path(root).expanduser().resolve(strict=False)
                for _kind, root in sorted(candidate.sidecar_roots.items())
            ]
            roots.append(
                artifact_link_local_event_root(project_key).resolve(strict=False)
            )
            seen: set[Path] = set()
            for root in roots:
                if root in seen:
                    continue
                seen.add(root)
                digest.update(f"events\0{root}\0".encode())
                _fold_tree(digest, root / _LINK_EVENTS_DIRNAME)
            legacy_imported = bool(candidate._legacy_indexes_imported())  # noqa: SLF001
            digest.update(f"legacy\0{legacy_imported}\0".encode())
            if not legacy_imported:
                for _kind, root in sorted(candidate.sidecar_roots.items()):
                    _fold_tree(
                        digest,
                        Path(root).expanduser().resolve(strict=False)
                        / REFERENCED_BY_LINKS_DIR,
                    )
            beads_dir = candidate.beads_dir
            digest.update(f"beads\0{beads_dir}\0".encode())
            if beads_dir is not None:
                _fold_tree(
                    digest,
                    Path(beads_dir).expanduser().resolve(strict=False),
                    skip_names=_BEAD_TRUTH_SKIP_NAMES,
                    skip_prefixes=_BEAD_TRUTH_SKIP_PREFIXES,
                )
        with artifact_link_outbox_read_scope(project_key) as (
            path,
            file_version,
            _read_records,
        ):
            if file_version is None:
                return None
            digest.update(f"outbox\0{path}\0{file_version}\0".encode())
        return digest.hexdigest()
    except Exception:  # noqa: BLE001 - fail open into a full reconcile.
        return None


def store_backed_rows_digest(rows: Iterable[Mapping[str, Any]]) -> str:
    """Digest the aggregate rows a reconcile decides, in their written order.

    Projected rows are excluded: the skip path recomputes them, so they never
    need to match for a recorded reconcile to stay valid.
    """

    digest = _new_digest("aggregate")
    for row in rows:
        if is_projected_row(row):
            continue
        digest.update(
            json.dumps(row, sort_keys=True, separators=(",", ":")).encode("utf-8")
        )
        digest.update(b"\n")
    return digest.hexdigest()


def combine_reconcile_fingerprint(inputs: str | None, aggregate: str) -> str | None:
    """Join the input and aggregate digests into the recorded fingerprint."""

    if inputs is None:
        return None
    return f"{inputs}:{aggregate}"


def unrepairable_refs_fingerprint(store: Any, refs: Iterable[str]) -> str | None:
    """Digest a dangling-ref set plus every ref head of the repairable roots.

    The rename scan reads ``git log --all`` of each ``plan``/``research``
    sidecar root, so its answer can change only when the dangling set or one
    of those repositories' refs moves.
    """

    try:
        from sase.sdd._artifact_link_renames import REPAIRABLE_RENAME_KINDS
        from sase.sdd._git import run_sdd_git

        digest = _new_digest("renames")
        for ref in sorted(set(refs)):
            digest.update(ref.encode("utf-8"))
            digest.update(b"\n")
        for kind in sorted(REPAIRABLE_RENAME_KINDS):
            root = store.sidecar_roots.get(kind)
            digest.update(f"root\0{kind}\0{root}\0".encode())
            if root is None or not Path(root).is_dir():
                continue
            result = run_sdd_git(
                ["rev-parse", "HEAD", "--all"],
                cwd=Path(root),
                check=False,
                capture_output=True,
                text=True,
                op="sdd.artifact_links.rename_memo_heads",
            )
            # A root git cannot read yields no rename history for the scan
            # either, so its exit status is the whole answer.
            digest.update(f"rc\0{result.returncode}\0".encode())
            if result.returncode == 0:
                digest.update(str(result.stdout or "").encode("utf-8"))
        return digest.hexdigest()
    except Exception:  # noqa: BLE001 - fail open into a full rename scan.
        return None


def _new_digest(label: str) -> Any:
    digest = hashlib.blake2b(digest_size=20)
    digest.update(f"{_FINGERPRINT_VERSION}\0{label}\0".encode())
    return digest


def _fold_tree(
    digest: Any,
    root: Path,
    *,
    skip_names: frozenset[str] = frozenset(),
    skip_prefixes: tuple[str, ...] = (),
    suffix: str | None = None,
    paths_only: bool = False,
) -> None:
    """Fold the identity of every file under *root* into *digest*.

    Dot entries (``.git``, staging and temp files) and *skip_names* are
    skipped at any depth; *suffix* keeps only matching file names, and
    *paths_only* folds relative paths without their stat identity. A missing
    root folds a fixed marker, so a root appearing or disappearing still
    changes the digest.
    """

    if not root.is_dir():
        digest.update(f"missing\0{root}\0".encode())
        return
    entries: list[tuple[str, int, int, int]] = []
    errors: list[str] = []
    stack = [root]
    while stack:
        current = stack.pop()
        try:
            with os.scandir(current) as iterator:
                for entry in iterator:
                    name = entry.name
                    if name.startswith(".") or name in skip_names:
                        continue
                    if skip_prefixes and name.startswith(skip_prefixes):
                        continue
                    if entry.is_dir(follow_symlinks=False):
                        stack.append(Path(entry.path))
                        continue
                    if suffix is not None and not name.endswith(suffix):
                        continue
                    if paths_only:
                        entries.append((os.path.relpath(entry.path, root), 0, 0, 0))
                        continue
                    stat = entry.stat(follow_symlinks=False)
                    entries.append(
                        (
                            os.path.relpath(entry.path, root),
                            stat.st_size,
                            stat.st_mtime_ns,
                            stat.st_ino,
                        )
                    )
        except OSError as exc:
            errors.append(f"{os.path.relpath(current, root)}: {exc.errno}")
    entries.sort()
    for relpath, size, mtime_ns, inode in entries:
        digest.update(f"{relpath}\0{size}\0{mtime_ns}\0{inode}\n".encode())
    for error in sorted(errors):
        digest.update(f"error\0{error}\n".encode())


def _optional_str(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _optional_float(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


__all__ = [
    "FULL_PASS_INTERVAL_SECONDS",
    "ArtifactLinkReconcileMemo",
    "combine_reconcile_fingerprint",
    "document_sweep_fingerprint",
    "reconcile_input_fingerprint",
    "store_backed_rows_digest",
    "unrepairable_refs_fingerprint",
]
