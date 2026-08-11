"""Capture and fingerprint the process-global state observed around a test."""

from __future__ import annotations

from collections.abc import Mapping
import hashlib
import os
import re
import sys
from types import ModuleType

from tests._global_state_leaks.models import (
    _CacheFingerprint,
    _Snapshot,
    _ValueFingerprint,
)


_PATTERN_TYPE = type(re.compile(""))
_ENV_KEYS_TO_IGNORE = frozenset(
    {
        "PYTEST_CURRENT_TEST",
        "SASE_PYTEST_SANDBOX_DIR",
    }
)


def _snapshot() -> _Snapshot:
    global_values: dict[str, _ValueFingerprint] = {}
    caches: dict[str, _CacheFingerprint] = {}
    for module_name, module in _loaded_sase_modules():
        for attr_name, value in vars(module).items():
            if _is_private_global_name(attr_name):
                fingerprint = _global_fingerprint(value)
                if fingerprint is not None:
                    global_values[f"{module_name}.{attr_name}"] = fingerprint
            cache = _cache_fingerprint(value)
            if cache is not None:
                caches.setdefault(f"{module_name}.{attr_name}", cache)
    return _Snapshot(
        globals=global_values,
        caches=caches,
        environ=_fingerprint_environment(
            {
                key: value
                for key, value in os.environ.items()
                if key not in _ENV_KEYS_TO_IGNORE
            }
        ),
        sys_path=_fingerprint_list(sys.path),
        cwd=_safe_getcwd(),
    )


def _safe_getcwd() -> str:
    try:
        return os.getcwd()
    except FileNotFoundError:
        return "<deleted>"


def _loaded_sase_modules() -> list[tuple[str, ModuleType]]:
    modules: list[tuple[str, ModuleType]] = []
    for name, module in sys.modules.items():
        if name != "sase" and not name.startswith("sase."):
            continue
        if isinstance(module, ModuleType):
            modules.append((name, module))
    return sorted(modules, key=lambda item: item[0])


def _is_private_global_name(name: str) -> bool:
    return name.startswith("_") and not (name.startswith("__") and name.endswith("__"))


def _global_fingerprint(value: object) -> _ValueFingerprint | None:
    if value is None:
        return _ValueFingerprint(
            kind="none",
            length=None,
            digest=_digest("None"),
            preview="None",
        )
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
    cache_clear = getattr(value, "cache_clear", None)
    if not callable(cache_info) or not callable(cache_clear):
        return None
    try:
        info = cache_info()
    except Exception:
        return None
    required = ("hits", "misses", "maxsize", "currsize")
    if not all(hasattr(info, name) for name in required):
        return None
    return _CacheFingerprint(
        hits=int(info.hits),
        misses=int(info.misses),
        maxsize=None if info.maxsize is None else int(info.maxsize),
        currsize=int(info.currsize),
    )


def _fingerprint_dict(value: Mapping[object, object]) -> _ValueFingerprint:
    entries = tuple(
        sorted(
            (f"{_safe_repr(key)} => {_safe_repr(entry_value)}")
            for key, entry_value in value.items()
        )
    )
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
    entries = tuple(sorted(_safe_repr(item) for item in value))
    text = "\n".join(entries)
    return _ValueFingerprint(
        kind=kind,
        length=len(value),
        digest=_digest(text),
        preview=_preview(entries),
        entries=frozenset(entries),
    )


def _fingerprint_list(value: list[object]) -> _ValueFingerprint:
    sequence = tuple(_safe_repr(item) for item in value)
    text = "\n".join(sequence)
    return _ValueFingerprint(
        kind="list",
        length=len(value),
        digest=_digest(text),
        preview=_preview(sequence),
        sequence=sequence,
    )


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
