"""Lazy fetch, availability states, and badges for bead attachments.

``read``, ``show``, and ``attachment path`` resolve each attachment in this
order: local tombstone, local CAS hit, then the shared git stores ordered by
descriptor visibility. ``attachment_should_auto_fetch`` (core policy) decides
whether the read fetches under the ``auto_fetch_max_bytes`` cap;
``-d/--download`` lifts the cap for one invocation and ``attachment path``
always fetches. ``attachment list`` never fetches and reports the state it
can see.

A fetch or preview failure never fails ``show`` or ``read``: the state falls
back to ``unavailable`` (``corrupt`` on a digest mismatch, ``no_access`` on a
git fetch access denial, ``blocked`` for secret-scanning rejections, and
``origin_only`` for oversized local-only objects) and the command still
exits 0.
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
    "origin_only",
    "no_access",
    "blocked",
    "unavailable",
    "purged",
    "corrupt",
)
"""Every availability state. ``remote`` is transient: fetching callers never
leave it user-visible. ``origin_only`` is a local-only object larger than
the git tier that can only be fetched from its origin machine; ``no_access``
is a git fetch access denial; ``blocked`` is a secret-scanning push
rejection recorded in the local outbox."""


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
class _FetchContext:
    """One command's shared fetch inputs: stores, outbox, cap, and mode."""

    mode: FetchMode = "never"
    project_key: str | None = None
    store: Any | None = None
    stores: list[Any] = field(default_factory=list)
    outbox: dict[str, Any] = field(default_factory=dict)
    cap_bytes: int = 26214400
    failed: set[str] = field(default_factory=set)
    corrupt: set[str] = field(default_factory=set)
    no_access: dict[str, str] = field(default_factory=dict)
    discover: bool = False


_current: ContextVar[_FetchContext | None] = ContextVar(
    "attachment_fetch_context", default=None
)


def _current_fetch_context() -> _FetchContext | None:
    """Return the ambient fetch context, or None outside one."""
    return _current.get()


def _get_auto_fetch_cap() -> int:
    """Return the configured auto-fetch ceiling, failing open to 25 MiB."""
    try:
        from sase.bead.config import get_attachment_auto_fetch_max_bytes

        return get_attachment_auto_fetch_max_bytes()
    except Exception:
        return 26214400


def _should_auto_fetch(size_bytes: int, cap_bytes: int) -> bool:
    """Return the core auto-fetch policy, failing open to True."""
    try:
        from sase.core.rust import require_rust_binding

        return bool(
            require_rust_binding("attachment_should_auto_fetch")(size_bytes, cap_bytes)
        )
    except Exception:
        return True


def _build_fetch_context(*, mode: FetchMode = "never") -> _FetchContext:
    """Discover the shared stores and outbox once for one command.

    Never raises: a missing store or unreadable outbox degrades to local
    observation instead of failing the read.
    """
    cap = _get_auto_fetch_cap()
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

            outbox = {}
            for entry in read_outbox(project_key):
                existing = outbox.get(entry.digest)
                if existing is None:
                    outbox[entry.digest] = entry
                    continue
                # Two rows may share one digest across stores; a pending row
                # still counts as pending_upload while a blocked row does not.
                existing_blocked = getattr(existing, "state", "pending") == "blocked"
                entry_blocked = getattr(entry, "state", "pending") == "blocked"
                if existing_blocked and not entry_blocked:
                    outbox[entry.digest] = entry
        except Exception as exc:
            log.debug("attachment outbox read skipped: %s", exc)
            outbox = {}
    return _FetchContext(
        mode=mode,
        project_key=project_key,
        store=store,
        stores=stores,
        outbox=outbox,
        cap_bytes=cap,
    )


def _ordered_stores(
    context: _FetchContext,
    size_bytes: int | None,
    *,
    visibility: str | None = None,
) -> list[Any]:
    """Return the context stores ordered by descriptor visibility.

    Public descriptors probe ``public``, ``git``, ``large``; private (and
    absent visibility) probe ``git``, ``large``, ``public``. Readers try
    every store; visibility only sets the order.
    """
    del size_bytes
    seen: list[Any] = []
    for store in list(getattr(context, "stores", None) or []):
        if store is not None and not any(store is known for known in seen):
            seen.append(store)
    primary = getattr(context, "store", None)
    if primary is not None and not any(primary is known for known in seen):
        seen.insert(0, primary)
    order = (
        ("public", "git", "large")
        if visibility == "public"
        else ("git", "large", "public")
    )
    rank = {name: index for index, name in enumerate(order)}
    return sorted(seen, key=lambda item: rank.get(getattr(item, "name", ""), 99))


@contextlib.contextmanager
def fetch_context(*, mode: FetchMode = "never") -> Iterator[_FetchContext]:
    """Set the ambient fetch context for one command's render.

    Discovery stays lazy: no store, outbox, or ``upload`` import happens
    here. The first :func:`attachment_state` or :func:`resolve_badge_origin`
    call inside the context discovers them via :func:`_ensure_discovered`.
    """
    context = _FetchContext(mode=mode, cap_bytes=_get_auto_fetch_cap(), discover=True)
    token = _current.set(context)
    try:
        yield context
    finally:
        _current.reset(token)


def _ensure_discovered(context: _FetchContext | None) -> None:
    """Run one-time lazy discovery for a ``fetch_context`` context.

    No-op unless ``discover`` is true, so contexts built by tests or by the
    ``context is None`` fallback never replace an injected ``store``. Clears
    the flag first, then copies ``project_key``, ``store``, and ``outbox``
    from today's eager discovery body. Leaves ``mode``, ``cap_bytes``,
    ``failed``, ``corrupt``, and ``no_access`` alone. Never raises: a
    discovery failure leaves ``store`` as ``None``, matching the eager path.
    """
    if context is None or not context.discover:
        return
    context.discover = False
    try:
        discovered = _build_fetch_context(mode=context.mode)
    except Exception as exc:
        log.debug("attachment shared-store lazy discovery skipped: %s", exc)
        return
    context.project_key = discovered.project_key
    context.store = discovered.store
    context.stores = discovered.stores
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


_ACCESS_DENIED_MARKERS = (
    "repository not found",
    "permission denied",
    "could not read username",
    "could not read password",
    "authentication failed",
    "access denied",
    "http 401",
    "http 403",
    "http 404",
    "status 401",
    "status 403",
    "status 404",
    "error: 401",
    "error: 403",
    "error: 404",
)
"""Case-insensitive git fetch fragments that mean an access denial.

A reader without a grant sees ``no_access`` instead of ``unavailable`` so
the state stays honest about whose copy is missing.
"""


def _is_access_denied(exc: BaseException) -> bool:
    """Return whether *exc* reads as a git fetch access denial."""
    try:
        message = str(exc).casefold()
    except Exception:
        return False
    return any(marker in message for marker in _ACCESS_DENIED_MARKERS)


def _store_label(store: Any) -> str:
    """Return a human-readable repo label for *store*, never raising."""
    for probe in ("describe",):
        try:
            label = getattr(store, probe)()
        except Exception:
            continue
        if isinstance(label, str) and label.strip():
            return label.strip()
    try:
        name = getattr(store, "name", None)
        if isinstance(name, str) and name.strip():
            return name.strip()
    except Exception:
        pass
    return "the shared store"


def _get_git_max_bytes() -> int:
    """Return the configured git-tier ceiling, failing open to 50 MiB."""
    try:
        from sase.bead.config import get_attachment_git_max_bytes

        return get_attachment_git_max_bytes()
    except Exception:
        return 52428800


def local_object_verified(sha256: str) -> bool:
    """Return whether the local CAS holds a digest-verified *sha256*."""
    cas = _local_store()
    if cas is None:
        return False
    try:
        return bool(cas.has(sha256) and cas.verify(sha256))
    except Exception:
        return False


def _ensure_fetched(
    context: _FetchContext,
    sha256: str,
    *,
    size_bytes: int | None = None,
    name: str | None = None,
    visibility: str | None = None,
) -> bool:
    """Fetch *sha256* into the local CAS through the ordered tier stores.

    Returns True when the local object is present and digest-verified. A
    digest mismatch records ``corrupt`` and installs nothing; an access
    denial records ``no_access`` with the denying repo's label and moves on
    to the next store; a miss moves on to the next store; any other
    transient failure moves on and the digest is ``failed`` only after every
    store has failed. Downloads above 8 MiB draw a TTY progress bar. Never
    raises.
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
    stores = _ordered_stores(context, size_bytes, visibility=visibility)
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
            if bool(getattr(exc, "missing", False)):
                log.debug(
                    "attachment fetch of %s… missed in store: %s", sha256[:12], exc
                )
                continue
            if _is_access_denied(exc):
                context.no_access.setdefault(sha256, _store_label(store))
                log.debug(
                    "attachment fetch of %s… denied by %s: %s",
                    sha256[:12],
                    context.no_access[sha256],
                    exc,
                )
                continue
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
    context: _FetchContext | None = None,
    visibility: str | None = None,
) -> str:
    """Return the availability state for one attachment digest.

    Never raises and never fails the caller: unexpected errors degrade to
    ``unavailable`` (or ``cached`` when the local object verifies). With no
    shared store the legacy two states hold: a verified local object is
    ``cached``, anything else ``unavailable``. ``remote`` is never returned;
    observation-only callers see ``not_downloaded`` for store-held objects.
    A secret-scanning rejection recorded in the local outbox reads
    ``blocked`` even when the bytes are local; a local-only object larger
    than the git tier reads ``origin_only``; a git fetch access denial reads
    ``no_access``.
    """
    del origin  # Badge input; state also uses the name for fetch progress.
    from sase.bead.attachments.store import validate_sha256

    try:
        validate_sha256(sha256)
    except Exception:
        return "unavailable"
    context = context if context is not None else _current.get()
    if context is None:
        context = _FetchContext()
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
    stores = _ordered_stores(context, size_bytes, visibility=visibility)
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
    pending_entry = context.outbox.get(sha256)
    if (
        pending_entry is not None
        and getattr(pending_entry, "state", "pending") != "blocked"
    ):
        return "pending_upload"
    if pending_entry is not None and (
        getattr(pending_entry, "state", "pending") == "blocked"
    ):
        return "blocked"
    if local_present:
        if size_bytes is not None and size_bytes > _get_git_max_bytes():
            return "origin_only"
        return "local_only"
    if remote_has:
        if context.mode == "force" or (
            context.mode == "auto"
            and size_bytes is not None
            and _should_auto_fetch(size_bytes, context.cap_bytes)
        ):
            if _ensure_fetched(
                context,
                sha256,
                size_bytes=size_bytes,
                name=name,
                visibility=visibility,
            ):
                return "cached"
            if sha256 in context.corrupt:
                return "corrupt"
            if sha256 in context.no_access:
                return "no_access"
            return "unavailable"
        return "not_downloaded"
    if sha256 in context.no_access:
        return "no_access"
    return "unavailable"


def resolve_badge_origin(
    sha256: str,
    attachment_origin: str | None,
    context: _FetchContext | None = None,
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


def resolve_badge_repo(
    sha256: str,
    context: _FetchContext | None = None,
) -> str | None:
    """Return the denying repo label recorded for *sha256*, if any."""
    context = context if context is not None else _current.get()
    if context is not None:
        try:
            label = context.no_access.get(sha256)
        except Exception:
            label = None
        if isinstance(label, str) and label.strip():
            return label.strip()
    return None


def attachment_badge(
    state: str,
    *,
    size_bytes: int | None = None,
    bead_id: str | None = None,
    name: str | None = None,
    origin: str | None = None,
    repo: str | None = None,
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
    if state == "origin_only":
        return f"⧉ on {origin or 'this machine'}"
    if state == "no_access":
        return f"🔒 no access ({repo})" if repo else "🔒 no access"
    if state == "blocked":
        return "⛔ blocked by secret scanning"
    if state == "unavailable":
        return "✕ unavailable offline"
    if state == "purged":
        return "(purged)"
    if state == "corrupt":
        return "‼ digest mismatch"
    return None


__all__ = [
    "AVAILABILITY_STATES",
    "_FetchContext",
    "FetchMode",
    "attachment_badge",
    "attachment_state",
    "_build_fetch_context",
    "_current_fetch_context",
    "_ensure_fetched",
    "fetch_context",
    "format_attachment_size",
    "_get_auto_fetch_cap",
    "local_object_verified",
    "resolve_badge_origin",
    "resolve_badge_repo",
    "_should_auto_fetch",
]
