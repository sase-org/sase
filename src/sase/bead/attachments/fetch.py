"""Lazy fetch, availability states, and badges for bead attachments.

``read``, ``show``, and ``attachment path`` resolve each attachment in this
order: local tombstone, local CAS hit, then the ``attachments-private`` git
store. ``attachment_should_auto_fetch`` (core policy) decides whether the
read fetches under the ``auto_fetch_max_bytes`` cap; ``-d/--download`` lifts
the cap for one invocation and ``attachment path`` always fetches.
``attachment list`` never fetches and reports the state it can see.

A fetch or preview failure never fails ``show`` or ``read``: the state falls
back to ``unavailable`` (or ``corrupt`` on a digest mismatch) and the command
still exits 0.
"""

from __future__ import annotations

import contextlib
import logging
from collections.abc import Iterator
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, Literal

log = logging.getLogger(__name__)

FetchMode = Literal["auto", "never", "force"]
"""``auto`` fetches under the cap, ``never`` only observes, ``force`` always."""

AVAILABILITY_STATES = (
    "cached",
    "remote",
    "not_downloaded",
    "pending_upload",
    "local_only",
    "unavailable",
    "purged",
    "corrupt",
)
"""Every availability state. ``remote`` is transient: fetching callers never
leave it user-visible."""


def format_attachment_size(size_bytes: int | None) -> str:
    """Format a byte count the way the write echo does."""
    if size_bytes is None or size_bytes < 0:
        return "unknown size"
    if size_bytes < 1024:
        return f"{size_bytes} bytes"
    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:g} KiB"
    if size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):g} MiB"
    return f"{size_bytes / (1024 * 1024 * 1024):g} GiB"


@dataclass
class FetchContext:
    """One command's shared fetch inputs: stores, outbox, cap, and mode."""

    mode: FetchMode = "never"
    project_key: str | None = None
    store: Any | None = None
    stores: list[Any] = field(default_factory=list)
    outbox: dict[str, Any] = field(default_factory=dict)
    cap_bytes: int = 26214400
    failed: set[str] = field(default_factory=set)
    corrupt: set[str] = field(default_factory=set)
    discover: bool = False


_current: ContextVar[FetchContext | None] = ContextVar(
    "attachment_fetch_context", default=None
)


def current_fetch_context() -> FetchContext | None:
    """Return the ambient fetch context, or None outside one."""
    return _current.get()


def get_auto_fetch_cap() -> int:
    """Return the configured auto-fetch ceiling, failing open to 25 MiB."""
    try:
        from sase.bead.config import get_attachment_auto_fetch_max_bytes

        return get_attachment_auto_fetch_max_bytes()
    except Exception:
        return 26214400


def should_auto_fetch(size_bytes: int, cap_bytes: int) -> bool:
    """Return the core auto-fetch policy, failing open to True."""
    try:
        from sase.core.rust import require_rust_binding

        return bool(
            require_rust_binding("attachment_should_auto_fetch")(size_bytes, cap_bytes)
        )
    except Exception:
        return True


def build_fetch_context(*, mode: FetchMode = "never") -> FetchContext:
    """Discover the shared stores and outbox once for one command.

    Never raises: a missing store or unreadable outbox degrades to local
    observation instead of failing the read.
    """
    cap = get_auto_fetch_cap()
    project_key: str | None = None
    store: Any | None = None
    stores: list[Any] = []
    outbox: dict[str, Any] = {}
    try:
        from sase.bead.attachments.upload import (
            discover_stores,
            resolve_project_key,
        )

        project_key = resolve_project_key(None)
    except Exception as exc:
        log.debug("attachment fetch project resolution skipped: %s", exc)
        project_key = None
    if project_key:
        try:
            stores = list(discover_stores(None).values())
            store = stores[0] if stores else None
        except Exception as exc:
            log.debug("attachment shared-store discovery skipped: %s", exc)
            store = None
            stores = []
        try:
            from sase.bead.attachments.outbox import read_outbox

            outbox = {entry.digest: entry for entry in read_outbox(project_key)}
        except Exception as exc:
            log.debug("attachment outbox read skipped: %s", exc)
            outbox = {}
    return FetchContext(
        mode=mode,
        project_key=project_key,
        store=store,
        stores=stores,
        outbox=outbox,
        cap_bytes=cap,
    )


def _ordered_stores(context: FetchContext, size_bytes: int | None) -> list[Any]:
    """Return the context stores ordered by the size-routed tier first.

    Placement is deterministic by size, so the tier that should hold the
    object probes first; the other tier is still probed on a miss (the
    caps may have changed since the upload). A missing size probes git
    first, the historical default.
    """
    seen: list[Any] = []
    for store in list(getattr(context, "stores", None) or []):
        if store is not None and not any(store is known for known in seen):
            seen.append(store)
    primary = getattr(context, "store", None)
    if primary is not None and not any(primary is known for known in seen):
        seen.insert(0, primary)
    if size_bytes is None or len(seen) < 2:
        return seen
    try:
        from sase.bead.config import get_attachment_git_max_bytes

        git_max = get_attachment_git_max_bytes()
    except Exception:
        return seen
    if size_bytes > git_max:
        return sorted(
            seen, key=lambda item: 0 if getattr(item, "name", "") == "large" else 1
        )
    return sorted(
        seen, key=lambda item: 1 if getattr(item, "name", "") == "large" else 0
    )


@contextlib.contextmanager
def fetch_context(*, mode: FetchMode = "never") -> Iterator[FetchContext]:
    """Set the ambient fetch context for one command's render.

    Discovery stays lazy: no store, outbox, or ``upload`` import happens
    here. The first :func:`attachment_state` or :func:`resolve_badge_origin`
    call inside the context discovers them via :func:`_ensure_discovered`.
    """
    context = FetchContext(mode=mode, cap_bytes=get_auto_fetch_cap(), discover=True)
    token = _current.set(context)
    try:
        yield context
    finally:
        _current.reset(token)


def _ensure_discovered(context: FetchContext | None) -> None:
    """Run one-time lazy discovery for a ``fetch_context`` context.

    No-op unless ``discover`` is true, so contexts built by tests or by the
    ``context is None`` fallback never replace an injected ``store``. Clears
    the flag first, then copies ``project_key``, ``store``, and ``outbox``
    from today's eager discovery body. Leaves ``mode``, ``cap_bytes``,
    ``failed``, and ``corrupt`` alone. Never raises: a discovery failure
    leaves ``store`` as ``None``, matching the eager path.
    """
    if context is None or not context.discover:
        return
    context.discover = False
    try:
        discovered = build_fetch_context(mode=context.mode)
    except Exception as exc:
        log.debug("attachment shared-store lazy discovery skipped: %s", exc)
        return
    context.project_key = discovered.project_key
    context.store = discovered.store
    context.outbox = discovered.outbox


def _local_store() -> Any | None:
    try:
        from sase.bead.attachments.store import LocalAttachmentStore

        return LocalAttachmentStore()
    except Exception:
        return None


def _has_local_tombstone(cas: Any, sha256: str) -> bool:
    try:
        tombstones = cas.tombstones_dir
    except Exception:
        return False
    try:
        return (tombstones / sha256).exists() or (
            tombstones / f"{sha256}.json"
        ).exists()
    except Exception:
        return False


def _store_has(store: Any, sha256: str) -> bool:
    try:
        return bool(store.has(sha256))
    except Exception:
        return False


def _store_has_tombstone(store: Any, sha256: str) -> bool:
    probe = getattr(store, "has_tombstone", None)
    if probe is None:
        return False
    try:
        return bool(probe(sha256))
    except Exception:
        return False


def ensure_fetched(
    context: FetchContext,
    sha256: str,
    *,
    size_bytes: int | None = None,
    name: str | None = None,
) -> bool:
    """Fetch *sha256* into the local CAS through the ordered tier stores.

    Returns True when the local object is present and digest-verified. A
    digest mismatch records ``corrupt`` and installs nothing; any other
    failure records ``failed``. Downloads above 8 MiB draw a TTY progress
    bar. Never raises.
    """
    from sase.bead.attachments.progress import transfer_progress

    cas = _local_store()
    if cas is None:
        return False
    try:
        if _has_local_tombstone(cas, sha256):
            return False
    except Exception:
        return False
    try:
        if cas.has(sha256) and cas.verify(sha256):
            return True
    except Exception:
        return False
    stores = _ordered_stores(context, size_bytes)
    if not stores or sha256 in context.failed or sha256 in context.corrupt:
        return False
    for store in stores:
        if _store_has_tombstone(store, sha256):
            return False
    label = name or f"{sha256[:12]}…"
    for store in stores:
        try:
            with transfer_progress(label, size_bytes) as progress:
                store.get(sha256, cas.root, progress=progress)
        except Exception as exc:
            transient = bool(getattr(exc, "transient", True))
            message = str(exc).lower()
            if not transient or "mismatch" in message or "hash" in message:
                context.corrupt.add(sha256)
                log.debug("attachment fetch of %s… failed: %s", sha256[:12], exc)
                return False
            log.debug("attachment fetch of %s… failed: %s", sha256[:12], exc)
            continue
        try:
            if cas.has(sha256) and cas.verify(sha256):
                return True
        except Exception:
            pass
    context.failed.add(sha256)
    return False


def attachment_state(
    sha256: str,
    *,
    size_bytes: int | None = None,
    origin: str | None = None,
    name: str | None = None,
    context: FetchContext | None = None,
) -> str:
    """Return the availability state for one attachment digest.

    Never raises and never fails the caller: unexpected errors degrade to
    ``unavailable`` (or ``cached`` when the local object verifies). With no
    shared store the legacy two states hold: a verified local object is
    ``cached``, anything else ``unavailable``. ``remote`` is never returned;
    observation-only callers see ``not_downloaded`` for store-held objects.
    """
    del origin  # Badge input; state also uses the name for fetch progress.
    from sase.bead.attachments.store import validate_sha256

    try:
        validate_sha256(sha256)
    except Exception:
        return "unavailable"
    context = context if context is not None else _current.get()
    if context is None:
        context = FetchContext()
    else:
        _ensure_discovered(context)
    cas = _local_store()
    if cas is None:
        return "unavailable"
    try:
        local_present = bool(cas.has(sha256))
    except Exception:
        return "unavailable"
    try:
        if _has_local_tombstone(cas, sha256):
            return "purged"
    except Exception:
        pass
    stores = _ordered_stores(context, size_bytes)
    remote_has = False
    for store in stores:
        if _store_has(store, sha256):
            remote_has = True
            break
    for store in stores:
        if _store_has_tombstone(store, sha256):
            return "purged"
    if sha256 in context.corrupt:
        return "corrupt"
    try:
        verified = local_present and bool(cas.verify(sha256))
    except Exception:
        verified = False
    if local_present and not verified:
        return "corrupt"
    if local_present and (not stores or remote_has):
        return "cached"
    if sha256 in context.outbox:
        return "pending_upload"
    if local_present:
        return "local_only"
    if remote_has:
        if context.mode == "force" or (
            context.mode == "auto"
            and size_bytes is not None
            and should_auto_fetch(size_bytes, context.cap_bytes)
        ):
            if ensure_fetched(context, sha256, size_bytes=size_bytes, name=name):
                return "cached"
            if sha256 in context.corrupt:
                return "corrupt"
            return "unavailable"
        return "not_downloaded"
    return "unavailable"


def resolve_badge_origin(
    sha256: str,
    attachment_origin: str | None,
    context: FetchContext | None = None,
) -> str:
    """Return the machine name for the pending/local-only badges."""
    context = context if context is not None else _current.get()
    if context is not None:
        _ensure_discovered(context)
        try:
            entry = context.outbox.get(sha256)
            entry_origin = getattr(entry, "origin", None)
            if isinstance(entry_origin, str) and entry_origin.strip():
                return entry_origin.strip()
        except Exception:
            pass
    if isinstance(attachment_origin, str) and attachment_origin.strip():
        return attachment_origin.strip()
    try:
        from sase.config import get_machine_name

        machine = get_machine_name()
        if isinstance(machine, str) and machine.strip():
            return machine.strip()
    except Exception:
        pass
    return "this machine"


def attachment_badge(
    state: str,
    *,
    size_bytes: int | None = None,
    bead_id: str | None = None,
    name: str | None = None,
    origin: str | None = None,
) -> str | None:
    """Return the display badge for *state*, or None for ``cached``/``remote``."""
    if state in ("cached", "remote"):
        return None
    if state == "not_downloaded":
        size = format_attachment_size(size_bytes)
        badge = f"⇣ not downloaded · {size}"
        if bead_id and name:
            badge += f" — sase bead attachment path {bead_id} {name}"
        return badge
    if state == "pending_upload":
        return f"⇡ pending upload ({origin or 'unknown'})"
    if state == "local_only":
        return f"⚠ only on {origin or 'this machine'}"
    if state == "unavailable":
        return "✕ unavailable offline"
    if state == "purged":
        return "(purged)"
    if state == "corrupt":
        return "‼ digest mismatch"
    return None


__all__ = [
    "AVAILABILITY_STATES",
    "FetchContext",
    "FetchMode",
    "attachment_badge",
    "attachment_state",
    "build_fetch_context",
    "current_fetch_context",
    "ensure_fetched",
    "fetch_context",
    "format_attachment_size",
    "get_auto_fetch_cap",
    "resolve_badge_origin",
    "should_auto_fetch",
]
