"""App-scoped memory-history queries for ACE.

One :class:`AceMemoryHistory` per ACE app wraps the process-wide
:func:`~sase.memory.history.service.shared_history_service`. Every
method blocks, so callers run them in thread workers or pump-free
tasks, never on the event loop or a keystroke path (epic design
``plan:202610/memory_history_tui.md`` §5.2).

- Timelines use stale-while-revalidate plus explicit invalidation
  plus stat-only change tokens; the UI repaints only when the
  fingerprint changed.
- Bodies and committed comparisons are cached by blob OID, so those
  caches can never go stale. Anything involving now or staged is
  never cached.
- Concurrent requests for the same key share one in-flight call
  (single-flight).
- No query calls ``sync()`` first: core queries sync internally.
  Only the quiet-time warm-up syncs.
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sase.ace.tui.util.trace import tui_trace
from sase.memory.history.service import shared_history_service

#: A timeline memo older than this revalidates in the background while
#: the stale snapshot still renders immediately.
_TIMELINE_STALE_S = 2.0

#: Bounded content caches (guidance sizes from the epic plan §5.2).
_BODY_LRU_SIZE = 128
_COMPARISON_LRU_SIZE = 64

_LIVE_VERSIONS = frozenset({"", "now", "stg", "staged", "uncommitted"})


@dataclass
class _TimelineEntry:
    """One memoized timeline: the wire plus its freshness markers."""

    wire: dict[str, Any]
    fingerprint: tuple[Any, ...]
    validated_at: float


@dataclass
class _Flight:
    """One in-flight single-flight call shared by concurrent waiters."""

    event: threading.Event = field(default_factory=threading.Event)
    result: Any = None
    error: BaseException | None = None


def _timeline_fingerprint(wire: dict[str, Any]) -> tuple[Any, ...]:
    """Return a cheap change marker for a timeline wire dict."""
    try:
        versions = wire.get("versions", ())
        committed = [
            row
            for row in versions
            if isinstance(row, dict) and int(row.get("ordinal", 0) or 0) > 0
        ]
        newest: dict[str, Any] = {}
        for row in committed:
            try:
                ordinal = int(row.get("ordinal", 0) or 0)
            except (TypeError, ValueError):
                continue
            try:
                best = int(newest.get("ordinal", 0) or 0)
            except (TypeError, ValueError):
                best = 0
            if ordinal >= best:
                newest = row
        return (
            str(wire.get("state", "") or ""),
            str(wire.get("tip", "") or wire.get("head", "") or ""),
            len(committed),
            int(newest.get("ordinal", 0) or 0),
            str(newest.get("commit", "") or ""),
            str(newest.get("blob_oid", "") or ""),
        )
    except Exception:
        return ("unavailable",)


def _stat_token(path: Path) -> tuple[int, int] | None:
    """Return ``(mtime_ns, size)`` for *path*, or ``None`` when unreadable."""
    try:
        stat = path.stat()
    except OSError:
        return None
    return (stat.st_mtime_ns, stat.st_size)


def _head_ref_name(git_dir: Path) -> str | None:
    """Return the ref file ``HEAD`` names (``refs/heads/x``), if any."""
    try:
        text = (git_dir / "HEAD").read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if text.startswith("ref:"):
        ref = text[len("ref:") :].strip()
        if ref and ".." not in ref and not ref.startswith("/"):
            return ref
    return None


class AceMemoryHistory:
    """Memoized, single-flight history queries for one ACE app."""

    def __init__(
        self,
        service: Any | None = None,
        *,
        _clock: Callable[[], float] | None = None,
    ) -> None:
        import time as _time

        self._service = service if service is not None else shared_history_service()
        self._clock = _clock or _time.monotonic
        self._lock = threading.RLock()
        self._timeline_memo: dict[tuple[str, str, bool], _TimelineEntry] = {}
        self._flights: dict[tuple[Any, ...], _Flight] = {}
        self._revalidating: set[tuple[str, str, bool]] = set()
        self._body_lru: OrderedDict[tuple[str, str], dict[str, Any]] = OrderedDict()
        self._comparison_lru: OrderedDict[tuple[str, str, str], dict[str, Any]] = (
            OrderedDict()
        )
        self._known_blobs: dict[tuple[str, str, str], str | None] = {}
        self._subjects_memo: dict[str, tuple[tuple[Any, ...], dict[str, Any]]] = {}
        self._feed_memo: dict[
            tuple[str, ...], tuple[tuple[Any, ...], dict[str, Any]]
        ] = {}
        self._seen_tokens: dict[tuple[str, str], tuple[Any, ...]] = {}
        self._git_dirs: dict[str, Path | None] = {}

    @property
    def service(self) -> Any:
        """Return the wrapped (shared) history service."""
        return self._service

    # --- scopes -----------------------------------------------------

    def scope_for_ref(self, ref: Any) -> Any | None:
        """Return the history scope for a panel scope-ring entry.

        Project entries build from ``content_root``; the home entry
        uses the chezmoi home scope (``None`` when home has no VCS).
        ``None`` when the scope cannot be built.
        """
        try:
            kind = getattr(ref, "kind", "project")
            if kind == "home":
                try:
                    return self._service.home_scope()
                except Exception:
                    return None
            content_root = getattr(ref, "content_root", "") or ""
            if not content_root:
                return None
            return self._service.project_scope(Path(content_root))
        except Exception:
            return None

    # --- single-flight ----------------------------------------------

    def _join_flight(self, key: tuple[Any, ...]) -> tuple[bool, _Flight]:
        """Enter the single-flight for *key*; True when this call owns it."""
        with self._lock:
            flight = self._flights.get(key)
            if flight is not None:
                return (False, flight)
            flight = _Flight()
            self._flights[key] = flight
            return (True, flight)

    def _settle_flight(
        self, key: tuple[Any, ...], flight: _Flight, *, result: Any = None
    ) -> None:
        """Publish a flight result (or ``flight.error``) and wake waiters."""
        with self._lock:
            self._flights.pop(key, None)
            flight.result = result
            flight.event.set()

    # --- timelines ----------------------------------------------------

    def timeline(
        self, scope: Any, selector: str, *, include_hidden: bool = False
    ) -> dict[str, Any]:
        """Return one subject's timeline wire dict (stale-while-revalidate).

        *selector* is the core selector (panel selectors are
        translated before this call). A memo hit renders immediately;
        when the entry is older than about 2 s a background
        revalidation refreshes the memo without blocking this call.
        """
        scope_key = str(getattr(scope, "scope_key", "") or "")
        key = (scope_key, str(selector), bool(include_hidden))
        with tui_trace("memory.history.query", op="timeline") as extra:
            with self._lock:
                entry = self._timeline_memo.get(key)
            if entry is not None:
                extra["hit"] = True
                if self._clock() - entry.validated_at > _TIMELINE_STALE_S:
                    self._spawn_timeline_revalidation(key, scope, str(selector))
                return entry.wire
            extra["hit"] = False
            return self._fetch_timeline(key, scope, str(selector), bool(include_hidden))

    def _fetch_timeline(
        self,
        key: tuple[str, str, bool],
        scope: Any,
        selector: str,
        include_hidden: bool,
    ) -> dict[str, Any]:
        """Fetch and memoize one timeline through the single-flight."""
        owner, flight = self._join_flight(("timeline", *key))
        if not owner:
            flight.event.wait()
            if flight.error is not None:
                raise flight.error
            return flight.result
        try:
            wire = dict(
                self._service.timeline(scope, selector, include_hidden=include_hidden)
            )
        except Exception as exc:
            flight.error = exc
            self._settle_flight(("timeline", *key), flight)
            raise
        entry = _TimelineEntry(
            wire=wire,
            fingerprint=_timeline_fingerprint(wire),
            validated_at=self._clock(),
        )
        with self._lock:
            self._timeline_memo[key] = entry
        self._settle_flight(("timeline", *key), flight, result=wire)
        return wire

    def _spawn_timeline_revalidation(
        self, key: tuple[str, str, bool], scope: Any, selector: str
    ) -> None:
        """Refresh a stale memo entry off-thread without blocking."""
        with self._lock:
            if key in self._revalidating or ("timeline", *key) in self._flights:
                return
            self._revalidating.add(key)

        def _revalidate() -> None:
            try:
                wire = dict(
                    self._service.timeline(scope, selector, include_hidden=key[2])
                )
            except Exception:
                return
            finally:
                with self._lock:
                    self._revalidating.discard(key)
            try:
                entry = _TimelineEntry(
                    wire=wire,
                    fingerprint=_timeline_fingerprint(wire),
                    validated_at=self._clock(),
                )
            except Exception:
                return
            with self._lock:
                self._timeline_memo[key] = entry

        thread = threading.Thread(
            target=_revalidate,
            name="ace-memory-history-revalidate",
            daemon=True,
        )
        thread.start()

    # --- bodies and comparisons (content-addressed) --------------------

    @staticmethod
    def _is_live_version(version: str) -> bool:
        """Return whether *version* names now/staged (never cached)."""
        return str(version).strip().lower() in _LIVE_VERSIONS

    def version_body(self, scope: Any, selector: str, version: str) -> dict[str, Any]:
        """Return one version wire with its body.

        Committed bodies cache by blob OID in a 128-entry LRU; now
        and staged always refetch and are never cached.
        """
        scope_key = str(getattr(scope, "scope_key", "") or "")
        version_arg = str(version)
        with tui_trace("memory.history.query", op="version_body") as extra:
            if self._is_live_version(version_arg):
                extra["hit"] = False
                return dict(
                    self._service.version(
                        scope, selector, version_arg, include_body=True
                    )
                )
            memo_key = (scope_key, str(selector), version_arg)
            with self._lock:
                blob = self._known_blobs.get(memo_key)
                if blob is not None:
                    cached = self._body_lru.get((scope_key, blob))
                    if cached is not None:
                        self._body_lru.move_to_end((scope_key, blob))
                        extra["hit"] = True
                        return cached
            extra["hit"] = False
            owner, flight = self._join_flight(("body", *memo_key))
            if not owner:
                flight.event.wait()
                if flight.error is not None:
                    raise flight.error
                return flight.result
            try:
                wire = dict(
                    self._service.version(
                        scope, selector, version_arg, include_body=True
                    )
                )
            except Exception as exc:
                flight.error = exc
                self._settle_flight(("body", *memo_key), flight)
                raise
            learned = self._learn_blob(scope_key, str(selector), version_arg, wire)
            if learned is not None:
                with self._lock:
                    self._body_lru[(scope_key, learned)] = wire
                    self._body_lru.move_to_end((scope_key, learned))
                    while len(self._body_lru) > _BODY_LRU_SIZE:
                        self._body_lru.popitem(last=False)
            self._settle_flight(("body", *memo_key), flight, result=wire)
            return wire

    def _learn_blob(
        self, scope_key: str, selector: str, version: str, wire: dict[str, Any]
    ) -> str | None:
        """Remember a version wire's blob OID; None when unknown."""
        try:
            blob = wire.get("blob_oid")
            blob_str = str(blob) if isinstance(blob, str) and blob else None
        except AttributeError:
            blob_str = None
        with self._lock:
            self._known_blobs[(scope_key, selector, str(version))] = blob_str
        return blob_str

    def _blob_for(
        self, scope: Any, scope_key: str, selector: str, version: str
    ) -> str | None:
        """Return the known blob OID for a version, learning it if needed."""
        with self._lock:
            if (scope_key, selector, str(version)) in self._known_blobs:
                return self._known_blobs[(scope_key, selector, str(version))]
        try:
            wire = dict(
                self._service.version(scope, selector, str(version), include_body=False)
            )
        except Exception:
            with self._lock:
                self._known_blobs[(scope_key, selector, str(version))] = None
            return None
        return self._learn_blob(scope_key, selector, str(version), wire)

    def comparison(
        self,
        scope: Any,
        selector: str,
        base: str,
        target: str,
        *,
        target_selector: str | None = None,
    ) -> dict[str, Any]:
        """Return the word-diff comparison wire for two versions.

        Committed pairs cache by ``(scope, base blob, target blob)``
        in a 64-entry LRU. Anything involving now or staged always
        refetches and is never cached.
        """
        scope_key = str(getattr(scope, "scope_key", "") or "")
        target_sel = (
            str(target_selector) if target_selector is not None else str(selector)
        )
        with tui_trace("memory.history.query", op="comparison") as extra:
            if self._is_live_version(base) or self._is_live_version(target):
                extra["hit"] = False
                compared = self._service.compare(
                    scope, str(selector), str(base), target_sel, str(target)
                )
                return dict(compared.get("comparison", compared))
            base_blob = self._blob_for(scope, scope_key, str(selector), str(base))
            target_blob = self._blob_for(scope, scope_key, target_sel, str(target))
            if base_blob is None or target_blob is None:
                extra["hit"] = False
                compared = self._service.compare(
                    scope, str(selector), str(base), target_sel, str(target)
                )
                return dict(compared.get("comparison", compared))
            cache_key = (scope_key, base_blob, target_blob)
            with self._lock:
                cached = self._comparison_lru.get(cache_key)
                if cached is not None:
                    self._comparison_lru.move_to_end(cache_key)
                    extra["hit"] = True
                    return cached
            extra["hit"] = False
            owner, flight = self._join_flight(("comparison", *cache_key))
            if not owner:
                flight.event.wait()
                if flight.error is not None:
                    raise flight.error
                return flight.result
            try:
                compared = self._service.compare(
                    scope, str(selector), str(base), target_sel, str(target)
                )
                wire = dict(compared.get("comparison", compared))
            except Exception as exc:
                flight.error = exc
                self._settle_flight(("comparison", *cache_key), flight)
                raise
            with self._lock:
                self._comparison_lru[cache_key] = wire
                self._comparison_lru.move_to_end(cache_key)
                while len(self._comparison_lru) > _COMPARISON_LRU_SIZE:
                    self._comparison_lru.popitem(last=False)
            self._settle_flight(("comparison", *cache_key), flight, result=wire)
            return wire

    # --- subjects and feed (change-token memos) ------------------------

    def subjects(self, scope: Any) -> dict[str, Any]:
        """Return one scope's subjects, memoized by its change token."""
        scope_key = str(getattr(scope, "scope_key", "") or "")
        with tui_trace("memory.history.query", op="subjects") as extra:
            token = self.change_token(scope)
            with self._lock:
                memo = self._subjects_memo.get(scope_key)
                if memo is not None and memo[0] == token:
                    extra["hit"] = True
                    return memo[1]
            extra["hit"] = False
            owner, flight = self._join_flight(("subjects", scope_key))
            if not owner:
                flight.event.wait()
                if flight.error is not None:
                    raise flight.error
                return flight.result
            try:
                result = dict(self._service.subjects(scope))
            except Exception as exc:
                flight.error = exc
                self._settle_flight(("subjects", scope_key), flight)
                raise
            with self._lock:
                self._subjects_memo[scope_key] = (self.change_token(scope), result)
            self._settle_flight(("subjects", scope_key), flight, result=result)
            return result

    def feed(self, scopes: list[Any]) -> dict[str, Any]:
        """Return the merged changesets feed, memoized by change tokens."""
        keys = tuple(str(getattr(scope, "scope_key", "") or "") for scope in scopes)
        with tui_trace("memory.history.query", op="feed") as extra:
            tokens = tuple(self.change_token(scope) for scope in scopes)
            with self._lock:
                memo = self._feed_memo.get(keys)
                if memo is not None and memo[0] == tokens:
                    extra["hit"] = True
                    return memo[1]
            extra["hit"] = False
            owner, flight = self._join_flight(("feed", *keys))
            if not owner:
                flight.event.wait()
                if flight.error is not None:
                    raise flight.error
                return flight.result
            try:
                result = dict(
                    self._service.feed(
                        scopes, since=None, limit=None, include_hidden=True
                    )
                )
            except Exception as exc:
                flight.error = exc
                self._settle_flight(("feed", *keys), flight)
                raise
            with self._lock:
                self._feed_memo[keys] = (
                    tuple(self.change_token(scope) for scope in scopes),
                    result,
                )
            self._settle_flight(("feed", *keys), flight, result=result)
            return result

    # --- change tokens and invalidation ----------------------------------

    def _git_dir_for_scope(self, scope: Any) -> Path | None:
        """Return the scope repo's git dir, resolving ``.git`` files once."""
        scope_key = str(getattr(scope, "scope_key", "") or "")
        with self._lock:
            if scope_key in self._git_dirs:
                return self._git_dirs[scope_key]
        repo_root = Path(str(getattr(scope, "repo_root", "") or ""))
        git_dir: Path | None = None
        try:
            dot_git = repo_root / ".git"
            if dot_git.is_dir():
                git_dir = dot_git
            elif dot_git.is_file():
                text = dot_git.read_text(encoding="utf-8").strip()
                if text.startswith("gitdir:"):
                    target = text[len("gitdir:") :].strip()
                    candidate = Path(target)
                    git_dir = (
                        candidate
                        if candidate.is_absolute()
                        else (repo_root / candidate)
                    )
        except OSError:
            git_dir = None
        with self._lock:
            self._git_dirs[scope_key] = git_dir
        return git_dir

    def change_token(
        self, scope: Any, subject: str | Path | None = None
    ) -> tuple[Any, ...]:
        """Return a stat-only change token for a scope (plus subject file).

        Covers the scope repo's HEAD file, the ref it names,
        ``packed-refs``, and the index (mtime_ns and size), plus the
        selected subject's worktree file when given. Pure stat calls:
        no git subprocess, no core query.
        """
        parts: list[Any] = []
        git_dir = self._git_dir_for_scope(scope)
        if git_dir is not None:
            parts.append(_stat_token(git_dir / "HEAD"))
            ref = _head_ref_name(git_dir)
            parts.append(_stat_token(git_dir / ref) if ref else None)
            parts.append(_stat_token(git_dir / "packed-refs"))
            parts.append(_stat_token(git_dir / "index"))
        else:
            parts.append(None)
        if subject is not None:
            candidate = Path(str(subject))
            if not candidate.is_absolute():
                candidate = Path(str(getattr(scope, "repo_root", "") or "")) / candidate
            parts.append(_stat_token(candidate))
        return tuple(parts)

    @staticmethod
    def _subject_file(scope: Any, selector: str) -> Path | None:
        """Return the subject's worktree file when *selector* is a path."""
        try:
            candidate = Path(selector)
            if not candidate.is_absolute():
                candidate = Path(str(getattr(scope, "repo_root", "") or "")) / candidate
            return candidate if candidate.is_file() else None
        except OSError:
            return None

    def poll_changed(self, scope: Any, selector: str) -> bool:
        """Return whether the scope/subject drifted since the last poll.

        The token covers the scope git state plus the selected
        subject's worktree file whenever the selector names one. The
        first poll establishes the baseline and returns False, so the
        quiet-time probe never fires spuriously on startup.
        """
        scope_key = str(getattr(scope, "scope_key", "") or "")
        key = (scope_key, str(selector))
        token = self.change_token(scope, self._subject_file(scope, str(selector)))
        with self._lock:
            seen = self._seen_tokens.get(key)
            self._seen_tokens[key] = token
            if seen is None:
                return False
            return seen != token

    def invalidate_subject(self, scope_key: str, selector: str) -> None:
        """Drop a subject's memoized entries and refetch on next use."""
        with self._lock:
            for key in [
                key for key in self._timeline_memo if key[:2] == (scope_key, selector)
            ]:
                del self._timeline_memo[key]
            self._seen_tokens.pop((scope_key, selector), None)
            for memo_key in [
                key for key in self._known_blobs if key[:2] == (scope_key, selector)
            ]:
                del self._known_blobs[memo_key]
            self._subjects_memo.pop(scope_key, None)
            for feed_key in [key for key in self._feed_memo if scope_key in key]:
                del self._feed_memo[feed_key]

    def invalidate_scope(self, scope_key: str) -> None:
        """Drop every memoized entry for a scope key."""
        with self._lock:
            for key in [key for key in self._timeline_memo if key[0] == scope_key]:
                del self._timeline_memo[key]
            for memo_key in [key for key in self._known_blobs if key[0] == scope_key]:
                del self._known_blobs[memo_key]
            self._seen_tokens = {
                key: token
                for key, token in self._seen_tokens.items()
                if key[0] != scope_key
            }
            self._subjects_memo.pop(scope_key, None)
            for feed_key in [key for key in self._feed_memo if scope_key in key]:
                del self._feed_memo[feed_key]

    # --- warm-up -----------------------------------------------------------

    def warm(self, scopes: list[Any]) -> dict[str, bool]:
        """Sync each scope once; per-scope failures report False, never raise."""
        outcome: dict[str, bool] = {}
        for scope in scopes:
            key = str(getattr(scope, "scope_key", "") or "")
            try:
                self._service.sync(scope)
            except Exception:
                outcome[key] = False
            else:
                outcome[key] = True
        return outcome


def ace_memory_history(app: Any) -> AceMemoryHistory:
    """Return the app-scoped :class:`AceMemoryHistory`, creating it lazily.

    Stored on the app, so tests get a fresh instance per app. Wraps
    the process-wide shared service.
    """
    history = getattr(app, "_ace_memory_history", None)
    if isinstance(history, AceMemoryHistory):
        return history
    history = AceMemoryHistory()
    try:
        app._ace_memory_history = history
    except AttributeError:
        pass
    return history


def schedule_history_warmup(app: Any, *, scopes: list[Any] | None = None) -> bool:
    """Schedule the once-per-app history warm-up off-thread; never blocks.

    Syncs the launch project scope and home after ACE's startup
    stopwatch ends, so the first ``H`` never pays the cold index
    cost. First paint never waits on it: this only queues a thread
    worker and returns.
    """
    if bool(getattr(app, "_history_warm_scheduled", False)):
        return False
    try:
        app._history_warm_scheduled = True
    except AttributeError:
        return False

    def _scopes() -> list[Any]:
        if scopes is not None:
            return list(scopes)
        found: list[Any] = []
        try:
            service = shared_history_service()
        except Exception:
            return found
        try:
            found.append(service.project_scope(Path.cwd()))
        except Exception:
            pass
        try:
            home = service.home_scope()
        except Exception:
            home = None
        if home is not None:
            found.append(home)
        return found

    def task() -> None:
        try:
            history = ace_memory_history(app)
        except Exception:
            return
        try:
            history.warm(_scopes())
        except Exception:
            pass

    try:
        app.run_worker(
            task,
            thread=True,
            exclusive=False,
            group="ace-memory-history-warm",
            exit_on_error=False,
        )
    except Exception:
        return False
    return True


__all__ = [
    "AceMemoryHistory",
    "ace_memory_history",
    "schedule_history_warmup",
]
