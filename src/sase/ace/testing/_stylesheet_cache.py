"""Fast-policy stylesheet snapshot reuse for :class:`AcePage`."""

from __future__ import annotations

from collections.abc import Hashable
from dataclasses import dataclass
from functools import partial
from hashlib import sha256
from pathlib import Path
import pickle
from typing import Any
import zlib

import textual
from textual.css.model import RuleSet
from textual.css.stylesheet import CssSource, Stylesheet
from textual.css.types import CSSLocation

from sase.ace.tui import AceApp


@dataclass(frozen=True)
class _CssPathSnapshot:
    path: str
    digest: str


@dataclass(frozen=True)
class _FastStylesheetKey:
    app_class: type[AceApp]
    textual_version: str
    variables: tuple[tuple[str, str], ...]
    css_paths: tuple[_CssPathSnapshot, ...]
    default_css: tuple[tuple[Hashable, str, int, str], ...]
    app_css: str


@dataclass(frozen=True)
class _StylesheetSnapshot:
    """One compiled stylesheet, serialized once and never handed out.

    ``state`` is one zlib-compressed pickle of the variables, sources, rules,
    and rule index. Each hydrate unpickles a private copy, which is several
    times cheaper than a ``deepcopy`` of the rule graph, and the cached value
    is immutable bytes, so the global-state leak detector observes it exactly
    at a small fraction of the cost of rendering every ``RuleSet``.
    """

    state: bytes


_StylesheetState = tuple[
    dict[str, str],
    dict[CSSLocation, CssSource],
    list[RuleSet],
    dict[str, list[RuleSet]],
]


@dataclass(frozen=True)
class FastStylesheetCacheStats:
    hits: int
    misses: int
    stores: int


@dataclass(frozen=True)
class FastStylesheetSeed:
    key: _FastStylesheetKey
    original_css_path: list[Path]
    hit: bool


# The fastest zlib level: it already shrinks the pickle about eightfold.
_COMPRESSION_LEVEL = 1

_CACHE: dict[_FastStylesheetKey, _StylesheetSnapshot] = {}
_HITS = 0
_MISSES = 0
_STORES = 0


def clear_fast_stylesheet_cache() -> None:
    """Clear the worker-local fast stylesheet cache and counters."""
    global _HITS, _MISSES, _STORES
    _CACHE.clear()
    _HITS = 0
    _MISSES = 0
    _STORES = 0


def fast_stylesheet_cache_stats() -> FastStylesheetCacheStats:
    """Return cache counters for focused tests."""
    return FastStylesheetCacheStats(hits=_HITS, misses=_MISSES, stores=_STORES)


def seed_fast_stylesheet(app: AceApp) -> FastStylesheetSeed | None:
    """Install a cached stylesheet snapshot on *app* when one is available."""
    global _HITS, _MISSES

    key = _key_for(app)
    if key is None:
        return None

    original_css_path = list(app.css_path)
    snapshot = _CACHE.get(key)
    if snapshot is None:
        _MISSES += 1
        return FastStylesheetSeed(
            key=key, original_css_path=original_css_path, hit=False
        )

    _HITS += 1
    app.stylesheet = _hydrate(snapshot)
    # The cached snapshot already contains app CSS path sources. Leaving
    # ``css_path`` populated would make Textual read the files again and mark
    # the stylesheet dirty, forcing the parse the cache exists to avoid.
    app.css_path = []
    _drop_pending_initial_css_refresh(app)
    return FastStylesheetSeed(key=key, original_css_path=original_css_path, hit=True)


def finish_fast_stylesheet_boot(app: AceApp, seed: FastStylesheetSeed | None) -> None:
    """Restore path metadata and retain the first successful compiled stylesheet."""
    global _STORES

    if seed is None:
        return
    if seed.hit:
        app.css_path = seed.original_css_path
        return
    if seed.key in _CACHE:
        return
    _CACHE[seed.key] = _snapshot(app.stylesheet)
    _STORES += 1


def _key_for(app: AceApp) -> _FastStylesheetKey | None:
    css_paths = _css_path_snapshots(app.css_path)
    if css_paths is None:
        return None
    return _FastStylesheetKey(
        app_class=type(app),
        textual_version=textual.__version__,
        variables=tuple(
            sorted((str(k), str(v)) for k, v in app.stylesheet._variables.items())
        ),
        css_paths=css_paths,
        default_css=tuple(
            (tuple(read_from), css, tie_breaker, scope)
            for read_from, css, tie_breaker, scope in app._get_default_css()
        ),
        app_css=str(app.CSS or ""),
    )


def _css_path_snapshots(paths: list[Path]) -> tuple[_CssPathSnapshot, ...] | None:
    snapshots: list[_CssPathSnapshot] = []
    for path in paths:
        try:
            resolved = path.resolve()
            content = resolved.read_bytes()
        except OSError:
            return None
        snapshots.append(
            _CssPathSnapshot(
                path=str(resolved),
                digest=sha256(content).hexdigest(),
            )
        )
    return tuple(snapshots)


def _snapshot(stylesheet: Stylesheet) -> _StylesheetSnapshot:
    """Serialize *stylesheet*'s compiled state in one pickle.

    ``RuleSet`` hashes by ``id``, and ``Stylesheet.apply`` narrows ``rules`` by
    membership in a set built from ``rules_map``. Serializing the two
    separately would yield equal-but-distinct rule objects, so that membership
    test would match nothing and the app would silently render with no CSS
    applied at all. One pickle of both keeps the map pointing at the very rule
    objects the restored ``rules`` list holds.
    """
    state: _StylesheetState = (
        dict(stylesheet._variables),
        dict(stylesheet.source),
        list(stylesheet.rules),
        {name: list(entry) for name, entry in stylesheet.rules_map.items()},
    )
    serialized = pickle.dumps(state, protocol=pickle.HIGHEST_PROTOCOL)
    return _StylesheetSnapshot(state=zlib.compress(serialized, _COMPRESSION_LEVEL))


def _hydrate(snapshot: _StylesheetSnapshot) -> Stylesheet:
    state: _StylesheetState = pickle.loads(zlib.decompress(snapshot.state))
    variables, source, rules, rules_map = state
    stylesheet = Stylesheet(variables=variables)
    stylesheet.source = source
    stylesheet._rules = rules
    stylesheet._rules_map = rules_map
    stylesheet._require_parse = False
    return stylesheet


def _drop_pending_initial_css_refresh(app: AceApp) -> None:
    callbacks = getattr(app, "_next_callbacks", None)
    if not isinstance(callbacks, list):
        return
    app._next_callbacks = [
        callback
        for callback in callbacks
        if not _is_initial_css_refresh_callback(app, callback)
    ]


def _is_initial_css_refresh_callback(app: AceApp, callback_message: Any) -> bool:
    callback = getattr(callback_message, "callback", None)
    if not isinstance(callback, partial):
        return False
    return (
        callback.func == app.refresh_css
        and callback.args == ()
        and callback.keywords == {"animate": False}
    )
