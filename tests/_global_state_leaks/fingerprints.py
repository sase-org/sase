"""Capture and fingerprint the process-global state observed around a test.

``_snapshot`` runs twice per test in the cost lane and walks every binding of
every loaded ``sase`` module, so its per-binding work dominates the lane's
overhead.  The hot loop keeps that work minimal without caching anything that
could go stale between snapshots:

* a binding's exact type is checked first: most values are of a type that can
  never be a tracked kind, so their names are never classified, and the
  tracked kinds dispatch on their exact type instead of an ``isinstance`` chain;
* private-name classification is a pure function of the name, so it is memoized
  in a bounded table;
* immutable builtin types cannot expose the cache protocol, so their values
  skip the probe; everything else gets one ``getattr``, and only an object that
  exposes ``cache_info`` pays for the full ``_cache_fingerprint`` check;
* a private container bound under several names is fingerprinted once per
  snapshot.  The memo holds the object itself, so a concurrent rebinding cannot
  hand a recycled ``id`` someone else's fingerprint;
* a compiled pattern, or a frozenset whose members are all immutable scalars,
  can never change its fingerprint, so a bounded table reuses it by identity.
  The table holds those objects alive; neither kind has a finalizer or a
  mutable member, so holding them changes nothing a test can observe.

Every binding is still visited on every snapshot, and every probe, cache
observation, and mutable fingerprint is recomputed each time.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
import hashlib
from operator import itemgetter
import os
import re
import sys
import threading
from types import BuiltinFunctionType, FunctionType, ModuleType
from typing import Any

from sase.config.core import CONFIG_TOKEN_REFRESH_THREAD_NAME
from tests._global_state_leaks.models import (
    _CacheFingerprint,
    _Snapshot,
    _ValueFingerprint,
)
from tests._sase_global_state_isolation import (
    _ENV_KEYS_TO_IGNORE as _ENV_KEYS_TO_IGNORE,
    _ignore_env_key as _ignore_env_key,
)

LIVE_CONFIG_TOKEN_REFRESH_THREADS_GLOBAL = (
    "sase.config.core._live_config_token_refresh_threads"
)


_PATTERN_TYPE = type(re.compile(""))

#: Exact types whose instances can never be a tracked private-global kind.
#: Each is an immutable builtin whose ``__class__`` resolves through the
#: ``object.__class__`` data descriptor, so ``isinstance`` against ``None``,
#: ``re.Pattern``, ``dict``, ``set``, ``frozenset``, or ``list`` is provably
#: false.  Subclasses and every other type still take the ``isinstance`` chain.
_UNTRACKED_GLOBAL_TYPES: frozenset[type] = frozenset(
    {
        bool,
        bytes,
        complex,
        float,
        int,
        str,
        tuple,
        type,
        BuiltinFunctionType,
        FunctionType,
        ModuleType,
    }
)

#: Exact types whose instances provably cannot expose ``cache_info`` or
#: ``cache_clear``: each is an immutable builtin (no attribute can be added to
#: the type) whose instances have no ``__dict__`` and whose MRO defines neither
#: name.  ``_cache_protocol_free_types`` re-checks those facts at import.
_CACHE_PROTOCOL_FREE_CANDIDATES: tuple[type, ...] = (
    bool,
    bytes,
    complex,
    dict,
    float,
    frozenset,
    int,
    list,
    set,
    str,
    tuple,
    type(None),
    _PATTERN_TYPE,
    BuiltinFunctionType,
)
_IMMUTABLE_TYPE_FLAG = 1 << 8  # Py_TPFLAGS_IMMUTABLETYPE


def _cache_protocol_free_types(candidates: tuple[type, ...]) -> frozenset[type]:
    for candidate in candidates:
        if (
            not candidate.__flags__ & _IMMUTABLE_TYPE_FLAG
            or candidate.__dictoffset__ != 0
            or hasattr(candidate, "cache_info")
            or hasattr(candidate, "cache_clear")
        ):
            raise TypeError(f"{candidate!r} could expose the cache protocol")
    return frozenset(candidates)


_CACHE_PROTOCOL_FREE_TYPES = _cache_protocol_free_types(_CACHE_PROTOCOL_FREE_CANDIDATES)

#: Distinct attribute names whose classification is memoized.  Classification
#: never goes stale, so the bound only limits memory; past it names are
#: classified on every visit.
_PRIVATE_NAME_CACHE_LIMIT = 1 << 17
_PRIVATE_NAME_CACHE: dict[str, bool] = {}

#: Fingerprints of provably immutable values, keyed by ``id``.  Each entry
#: holds its value, so the id cannot be recycled while the entry exists.
_IMMUTABLE_FINGERPRINT_LIMIT = 1 << 14
_IMMUTABLE_FINGERPRINTS: dict[int, tuple[object, _ValueFingerprint]] = {}
#: Exact immutable types whose ``repr`` is fixed for an object's lifetime.
_IMMUTABLE_SCALAR_TYPES: frozenset[type] = frozenset(
    {bool, bytes, complex, float, int, str, type(None)}
)

_REQUIRED_CACHE_INFO_FIELDS = ("hits", "misses", "maxsize", "currsize")
_NONE_TEXT = "None"
_MODULE_NAME = itemgetter(0)


def _snapshot() -> _Snapshot:
    global_values: dict[str, _ValueFingerprint] = {}
    caches: dict[str, _CacheFingerprint] = {}
    # id -> (value, fingerprint) for this snapshot only.  Holding ``value``
    # keeps its id from being recycled until the snapshot is finished.
    aliases: dict[int, tuple[object, _ValueFingerprint | None]] = {}
    private_names = _PRIVATE_NAME_CACHE
    untracked_types = _UNTRACKED_GLOBAL_TYPES
    cache_protocol_free_types = _CACHE_PROTOCOL_FREE_TYPES
    for module_name, module in _loaded_sase_modules():
        for attr_name, value in vars(module).items():
            value_type = type(value)
            if value_type not in untracked_types:
                try:
                    is_private = private_names[attr_name]
                except KeyError:
                    is_private = _is_private_global_name(attr_name)
                if is_private:
                    fingerprint = _aliased_global_fingerprint(value, aliases)
                    if fingerprint is not None:
                        global_values[f"{module_name}.{attr_name}"] = fingerprint
            if value_type in cache_protocol_free_types:
                continue
            # Cheap rejection: an object without ``cache_info`` cannot expose
            # the cache protocol, so the full check runs only for candidates.
            if getattr(value, "cache_info", None) is not None:
                cache = _cache_fingerprint(value)
                if cache is not None:
                    caches.setdefault(f"{module_name}.{attr_name}", cache)
    aliases.clear()
    live_refresh_threads = _live_config_token_refresh_threads()
    if live_refresh_threads:
        global_values[LIVE_CONFIG_TOKEN_REFRESH_THREADS_GLOBAL] = _fingerprint_list(
            live_refresh_threads
        )
    return _Snapshot(
        globals=global_values,
        caches=caches,
        environ=_fingerprint_environment(
            {
                key: value
                for key, value in os.environ.items()
                if not _ignore_env_key(key)
            }
        ),
        sys_path=_fingerprint_list(sys.path),
        cwd=_safe_getcwd(),
    )


def _aliased_global_fingerprint(
    value: object,
    aliases: dict[int, tuple[object, _ValueFingerprint | None]],
) -> _ValueFingerprint | None:
    key = id(value)
    seen = aliases.get(key)
    if seen is not None and seen[0] is value:
        return seen[1]
    fingerprint = _immutable_global_fingerprint(value, key)
    aliases[key] = (value, fingerprint)
    return fingerprint


def _immutable_global_fingerprint(value: object, key: int) -> _ValueFingerprint | None:
    """Fingerprint ``value``, reusing the result when it can never change."""
    known = _IMMUTABLE_FINGERPRINTS.get(key)
    if known is not None and known[0] is value:
        return known[1]
    fingerprint = _global_fingerprint(value)
    if (
        fingerprint is not None
        and len(_IMMUTABLE_FINGERPRINTS) < _IMMUTABLE_FINGERPRINT_LIMIT
        and _has_fixed_fingerprint(value)
    ):
        _IMMUTABLE_FINGERPRINTS[key] = (value, fingerprint)
    return fingerprint


def _has_fixed_fingerprint(value: object) -> bool:
    if type(value) is _PATTERN_TYPE:
        return True
    if isinstance(value, frozenset) and type(value) is frozenset:
        return _IMMUTABLE_SCALAR_TYPES.issuperset(map(type, value))
    return False


def _safe_getcwd() -> str:
    try:
        return os.getcwd()
    except FileNotFoundError:
        return "<deleted>"


def _live_config_token_refresh_threads() -> list[str]:
    """Return live ``sase-config-token-refresh`` workers for leak snapshots."""
    return sorted(
        f"{thread.ident}:{thread.name}"
        for thread in threading.enumerate()
        if thread.name == CONFIG_TOKEN_REFRESH_THREAD_NAME and thread.is_alive()
    )


def _loaded_sase_modules() -> list[tuple[str, ModuleType]]:
    modules: list[tuple[str, ModuleType]] = []
    for name, module in sys.modules.items():
        if name != "sase" and not name.startswith("sase."):
            continue
        if isinstance(module, ModuleType):
            modules.append((name, module))
    return sorted(modules, key=_MODULE_NAME)


def _is_private_global_name(name: str) -> bool:
    cached = _PRIVATE_NAME_CACHE.get(name)
    if cached is not None:
        return cached
    is_private = name.startswith("_") and not (
        name.startswith("__") and name.endswith("__")
    )
    if len(_PRIVATE_NAME_CACHE) < _PRIVATE_NAME_CACHE_LIMIT:
        _PRIVATE_NAME_CACHE[name] = is_private
    return is_private


def _global_fingerprint(value: object) -> _ValueFingerprint | None:
    value_type = type(value)
    if value_type in _UNTRACKED_GLOBAL_TYPES:
        return None
    # Exact types first; subclasses and look-alikes fall through to the
    # original ``isinstance`` order below.
    if value is None:
        return _ValueFingerprint(
            kind="none",
            length=None,
            digest=_NONE_DIGEST,
            preview=_NONE_TEXT,
        )
    if value_type is dict:
        return _fingerprint_dict(value)  # type: ignore[arg-type]
    if value_type is frozenset:
        return _fingerprint_set(value, kind="frozenset")  # type: ignore[arg-type]
    if value_type is list:
        return _fingerprint_list(value)  # type: ignore[arg-type]
    if value_type is set:
        return _fingerprint_set(value, kind="set")  # type: ignore[arg-type]
    if isinstance(value, _PATTERN_TYPE):
        pattern = str(value.pattern)
        flags = int(value.flags)
        text = f"pattern={pattern!r};flags={flags}"
        return _ValueFingerprint(
            kind="re.Pattern",
            length=None,
            digest=_digest(text),
            preview=text,
        )
    if isinstance(value, dict):
        return _fingerprint_dict(value)
    if isinstance(value, set):
        return _fingerprint_set(value, kind="set")
    if isinstance(value, frozenset):
        return _fingerprint_set(value, kind="frozenset")
    if isinstance(value, list):
        return _fingerprint_list(value)
    return None


def _cache_fingerprint(value: object) -> _CacheFingerprint | None:
    cache_info = getattr(value, "cache_info", None)
    if not callable(cache_info):
        return None
    cache_clear = getattr(value, "cache_clear", None)
    if not callable(cache_clear):
        return None
    try:
        info: Any = cache_info()
    except Exception:
        return None
    if not all(hasattr(info, name) for name in _REQUIRED_CACHE_INFO_FIELDS):
        return None
    return _CacheFingerprint(
        hits=int(info.hits),
        misses=int(info.misses),
        maxsize=None if info.maxsize is None else int(info.maxsize),
        currsize=int(info.currsize),
    )


def _fingerprint_dict(value: Mapping[object, object]) -> _ValueFingerprint:
    try:
        rendered = [f"{key!r} => {entry_value!r}" for key, entry_value in value.items()]
    except Exception:
        rendered = [
            f"{_safe_repr(key)} => {_safe_repr(entry_value)}"
            for key, entry_value in value.items()
        ]
    rendered.sort()
    entries = tuple(rendered)
    text = "\n".join(entries)
    return _ValueFingerprint(
        kind="dict",
        length=len(value),
        digest=_digest(text),
        preview=_preview(entries),
        entries=frozenset(entries),
    )


def _fingerprint_environment(value: Mapping[str, str]) -> _ValueFingerprint:
    entries = tuple(
        sorted(
            f"{key}={_digest(_safe_repr(entry_value))}"
            for key, entry_value in value.items()
        )
    )
    text = "\n".join(entries)
    return _ValueFingerprint(
        kind="environment",
        length=len(value),
        digest=_digest(text),
        preview=_preview(tuple(sorted(value))),
        entries=frozenset(entries),
    )


def _fingerprint_set(
    value: set[object] | frozenset[object], *, kind: str
) -> _ValueFingerprint:
    entries = tuple(sorted(_reprs(value)))
    text = "\n".join(entries)
    return _ValueFingerprint(
        kind=kind,
        length=len(value),
        digest=_digest(text),
        preview=_preview(entries),
        entries=frozenset(entries),
    )


def _fingerprint_list(value: Sequence[object]) -> _ValueFingerprint:
    sequence = tuple(_reprs(value))
    text = "\n".join(sequence)
    return _ValueFingerprint(
        kind="list",
        length=len(value),
        digest=_digest(text),
        preview=_preview(sequence),
        sequence=sequence,
    )


def _reprs(values: Iterable[object]) -> list[str]:
    """``repr`` every item, falling back to ``_safe_repr`` if any raises."""
    try:
        return list(map(repr, values))
    except Exception:
        return [_safe_repr(item) for item in values]


def _safe_repr(value: object) -> str:
    try:
        return repr(value)
    except Exception as error:
        return f"<unrepresentable {type(value).__name__}: {error}>"


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", "backslashreplace")).hexdigest()[:16]


def _preview(entries: tuple[str, ...]) -> str:
    if not entries:
        return ""
    preview = ", ".join(entries[:3])
    if len(entries) > 3:
        preview = f"{preview}, ..."
    return preview[:240]


_NONE_DIGEST = _digest(_NONE_TEXT)
