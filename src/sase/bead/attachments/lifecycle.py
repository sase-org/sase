"""Shared inventory for attachment purge, doctor, and prune.

All three lifecycle commands scan the same durable state: current note and
+1-evidence manifests across every bead in the project store, the local
content-addressed objects and views, the upload outbox, and the configured
shared stores. Historical events are append-only and stay pinned by policy;
only current manifests are enumerated here, so prune additionally requires
every evicted object to be confirmed present in a shared store.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sase.bead.attachments.store import LocalAttachmentStore

log = logging.getLogger(__name__)

#: Local objects unreferenced by any current manifest become orphans only
#: after this age, so a just-written object is never collected from under
#: an in-flight command.
ORPHAN_AGE_SECONDS = 7 * 24 * 60 * 60


@dataclass(frozen=True)
class _AttachmentReference:
    """One current-manifest reference to an attachment digest."""

    issue_id: str
    source: str
    name: str
    sha256: str


@dataclass
class _AttachmentInventory:
    """One project's current attachment references plus local objects."""

    references: list[_AttachmentReference] = field(default_factory=list)
    local_objects: dict[str, dict[str, Any]] = field(default_factory=dict)

    def digests_referenced(self) -> set[str]:
        """Return every digest named by a current manifest."""
        return {reference.sha256 for reference in self.references}

    def references_for_digest(self, sha256: str) -> list[_AttachmentReference]:
        """Return every current reference to *sha256*, sorted by bead."""
        matches = [
            reference for reference in self.references if reference.sha256 == sha256
        ]
        return sorted(matches, key=lambda item: (item.issue_id, item.source, item.name))


def _manifest_records(issue: Any) -> list[tuple[str, Any]]:
    """Return ``(source, record)`` pairs for every current manifest record."""
    pairs: list[tuple[str, Any]] = []
    for ordinal, note in enumerate(getattr(issue, "notes", ()) or (), start=1):
        for attachment in getattr(note, "attachments", ()) or ():
            pairs.append((f"note#{ordinal}", attachment))
    for index, evidence in enumerate(
        getattr(issue, "plus_one_evidence", ()) or (), start=1
    ):
        for attachment in getattr(evidence, "attachments", ()) or ():
            pairs.append((f"+1#{index}", attachment))
    return pairs


def roster_for_issue(issue: Any) -> dict[str, Any]:
    """Map attachment name to its latest record for one issue.

    The latest note wins per name; +1 evidence overlays notes. This is the
    single roster helper shared by the CLI, the pager resolver, purge, and
    prune, so all surfaces agree on what a bead currently holds.
    """
    roster: dict[str, Any] = {}
    for note in getattr(issue, "notes", ()) or ():
        for attachment in getattr(note, "attachments", ()) or ():
            roster[attachment.name] = attachment
    for evidence in getattr(issue, "plus_one_evidence", ()) or ():
        for attachment in getattr(evidence, "attachments", ()):
            roster[attachment.name] = attachment
    return roster


def _collect_references(issues: list[Any]) -> list[_AttachmentReference]:
    """Collect current-manifest references across *issues*."""
    references: list[_AttachmentReference] = []
    for issue in issues:
        issue_id = str(getattr(issue, "id", "?"))
        for source, record in _manifest_records(issue):
            name = str(getattr(record, "name", ""))
            sha256 = str(getattr(record, "sha256", ""))
            if not name or not sha256:
                continue
            references.append(
                _AttachmentReference(
                    issue_id=issue_id, source=source, name=name, sha256=sha256
                )
            )
    return references


def _scan_local_objects(store: LocalAttachmentStore) -> dict[str, dict[str, Any]]:
    """Map each local digest to its size, mtime, and view names."""
    found: dict[str, dict[str, Any]] = {}
    objects_dir = store.objects_dir
    if not objects_dir.is_dir():
        return found
    for shard in sorted(objects_dir.iterdir()):
        if not shard.is_dir() or len(shard.name) != 2:
            continue
        for path in sorted(shard.iterdir()):
            if not path.is_file() or len(path.name) != 64:
                continue
            try:
                stat = path.stat()
            except OSError:
                continue
            views = store.views_dir / path.name[:16]
            names: list[str] = []
            view_mtime = 0.0
            try:
                if views.is_dir() and not views.is_symlink():
                    for link in sorted(views.iterdir()):
                        names.append(link.name)
                        try:
                            view_mtime = max(view_mtime, link.stat().st_mtime)
                        except OSError:
                            continue
            except OSError:
                names = []
            found[path.name] = {
                "size_bytes": stat.st_size,
                "mtime": max(stat.st_mtime, view_mtime),
                "names": names,
            }
    return found


def collect_inventory(view: Any) -> _AttachmentInventory:
    """Build the current-manifest plus local-object inventory for *view*."""
    from sase.bead.model import Status

    try:
        issues = view.list_issues(
            statuses=[
                Status.OPEN,
                Status.CLAIMED,
                Status.READY,
                Status.SNOOZED,
                Status.IN_PROGRESS,
                Status.CLOSED,
            ],
        )
    except Exception as exc:
        log.debug("attachment inventory listing skipped: %s", exc)
        issues = []
    return _AttachmentInventory(
        references=_collect_references(list(issues)),
        local_objects=_scan_local_objects(LocalAttachmentStore()),
    )


def store_has_digest(stores: dict[str, Any], sha256: str) -> bool:
    """Return whether any configured shared store holds *sha256*."""
    for store in stores.values():
        try:
            if store is not None and bool(store.has(sha256)):
                return True
        except Exception:
            continue
    return False


def store_has_tombstone(stores: dict[str, Any], sha256: str) -> bool:
    """Return whether any configured shared store holds a tombstone."""
    for store in stores.values():
        probe = getattr(store, "has_tombstone", None)
        if probe is None:
            continue
        try:
            if bool(probe(sha256)):
                return True
        except Exception:
            continue
    return False


def orphan_digests(
    inventory: _AttachmentInventory, *, now: float | None = None
) -> list[str]:
    """Return local digests no current manifest references, aged past grace.

    Only digests older than ``ORPHAN_AGE_SECONDS`` are orphans, so objects
    written moments ago (whose note may not be committed yet) are kept.
    """
    moment = time.time() if now is None else now
    referenced = inventory.digests_referenced()
    return sorted(
        digest
        for digest, info in inventory.local_objects.items()
        if digest not in referenced
        and float(info.get("mtime", moment)) <= moment - ORPHAN_AGE_SECONDS
    )


@dataclass
class _PruneCandidate:
    """One evictable cached object, oldest views first."""

    sha256: str
    size_bytes: int
    mtime: float
    names: list[str]


@dataclass
class PrunePlan:
    """A dry-run prune plan: what would be (or was) evicted, and the funnel."""

    budget_bytes: int
    total_bytes: int
    candidates: list[_PruneCandidate] = field(default_factory=list)
    evict: list[_PruneCandidate] = field(default_factory=list)
    skipped_pending: int = 0
    skipped_local_only: int = 0
    evicted_bytes: int = 0

    @property
    def remaining_bytes(self) -> int:
        """Return the cache size after the planned evictions."""
        return self.total_bytes - self.evicted_bytes


def plan_prune(
    inventory: _AttachmentInventory,
    stores: dict[str, Any],
    outbox_digests: set[str],
    budget_bytes: int,
) -> PrunePlan:
    """Plan cache evictions to fit under *budget_bytes*.

    Only cached objects confirmed present in a shared store are candidates.
    Pending-outbox digests and local-only digests (no store copy) are never
    evicted. Candidates go oldest-first; eviction stops once the remaining
    cache fits the budget.
    """
    plan = PrunePlan(
        budget_bytes=budget_bytes,
        total_bytes=sum(
            int(info.get("size_bytes", 0)) for info in inventory.local_objects.values()
        ),
    )
    if not stores:
        plan.skipped_local_only = len(inventory.local_objects)
        return plan
    for digest in sorted(
        inventory.local_objects,
        key=lambda item: float(inventory.local_objects[item].get("mtime", 0.0)),
    ):
        info = inventory.local_objects[digest]
        if digest in outbox_digests:
            plan.skipped_pending += 1
            continue
        if not store_has_digest(stores, digest):
            plan.skipped_local_only += 1
            continue
        plan.candidates.append(
            _PruneCandidate(
                sha256=digest,
                size_bytes=int(info.get("size_bytes", 0)),
                mtime=float(info.get("mtime", 0.0)),
                names=list(info.get("names", [])),
            )
        )
    remaining = plan.total_bytes
    for candidate in plan.candidates:
        if remaining <= budget_bytes:
            break
        plan.evict.append(candidate)
        remaining -= candidate.size_bytes
        plan.evicted_bytes += candidate.size_bytes
    return plan


def apply_prune_evictions(plan: PrunePlan) -> tuple[int, int]:
    """Evict the planned objects; return ``(evicted, evicted_bytes)``."""
    store = LocalAttachmentStore()
    evicted = 0
    evicted_bytes = 0
    for candidate in plan.evict:
        try:
            if store.remove(candidate.sha256):
                evicted += 1
                evicted_bytes += candidate.size_bytes
        except Exception as exc:
            log.debug("prune eviction of %s… skipped: %s", candidate.sha256[:12], exc)
    return (evicted, evicted_bytes)


def quarantine_local_object(sha256: str) -> bool:
    """Move a corrupt local object aside; return True when moved.

    The object leaves ``objects/`` (so reads stop trusting it) and its
    views are removed. A shared-store copy refetches on demand. The bytes
    are kept under ``quarantine/sha256/<xx>/<sha>`` for forensics.
    """
    from sase.bead.attachments.store import validate_sha256

    try:
        validate_sha256(sha256)
    except ValueError:
        return False
    store = LocalAttachmentStore()
    path = store.object_path(sha256)
    if not path.is_file():
        return False
    target_dir = store.root / "quarantine" / "sha256" / sha256[:2]
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / sha256
        path.replace(target)
    except OSError as exc:
        log.debug("quarantine of %s… failed: %s", sha256[:12], exc)
        return False
    views = store.views_dir / sha256[:16]
    try:
        if views.is_dir() and not views.is_symlink():
            import shutil

            shutil.rmtree(views, ignore_errors=True)
    except OSError:
        pass
    return True


def remove_orphan_objects(digests: list[str]) -> tuple[int, int]:
    """Remove orphan local objects and views; return ``(removed, bytes)``."""
    store = LocalAttachmentStore()
    removed = 0
    freed = 0
    for digest in digests:
        try:
            path = store.object_path(digest)
            size = path.stat().st_size if path.is_file() else 0
            if store.remove(digest):
                removed += 1
                freed += size
        except Exception as exc:
            log.debug("orphan removal of %s… skipped: %s", digest[:12], exc)
    return (removed, freed)


def outbox_digests_for_project(project_key: str | None) -> set[str]:
    """Return the queued outbox digests for *project_key*, or empty."""
    if not project_key:
        return set()
    try:
        from sase.bead.attachments.outbox import read_outbox

        return {entry.digest for entry in read_outbox(project_key)}
    except Exception as exc:
        log.debug("attachment outbox read skipped: %s", exc)
        return set()


__all__ = [
    "ORPHAN_AGE_SECONDS",
    "_AttachmentInventory",
    "_AttachmentReference",
    "_PruneCandidate",
    "PrunePlan",
    "apply_prune_evictions",
    "collect_inventory",
    "_collect_references",
    "orphan_digests",
    "outbox_digests_for_project",
    "plan_prune",
    "quarantine_local_object",
    "remove_orphan_objects",
    "roster_for_issue",
    "_scan_local_objects",
    "store_has_digest",
    "store_has_tombstone",
]
