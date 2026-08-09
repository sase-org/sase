"""A drop-in ``yaml.safe_load`` that prefers the LibYAML C loader.

``yaml.safe_load`` always parses with the pure-Python ``SafeLoader``, even
when the ``libyaml`` C bindings are installed. For trusted, JSON-shaped
configuration such as ``default_config.yml`` and ``sase.yml``, parsing with
``yaml.CSafeLoader`` instead is an order of magnitude faster and raises the
same ``yaml.YAMLError`` subclasses on malformed input, so callers can switch
loaders without changing behavior.
"""

from __future__ import annotations

from copy import deepcopy
from functools import lru_cache
from typing import IO, Any

import yaml  # type: ignore[import-untyped]


def _safe_loader() -> type[yaml.SafeLoader]:
    """Return the fastest available safe loader for this environment."""

    return getattr(yaml, "CSafeLoader", yaml.SafeLoader)


def yaml_safe_load(stream: str | bytes | IO[str] | IO[bytes]) -> Any:
    """Parse trusted YAML, preferring the LibYAML C loader when available.

    Falls back to the pure-Python ``yaml.SafeLoader`` when ``libyaml`` was not
    compiled into this environment's ``pyyaml`` install.
    """

    return yaml.load(stream, Loader=_safe_loader())


@lru_cache(maxsize=256)
def _cached_yaml_safe_load_text(text: str | bytes) -> Any:
    return yaml_safe_load(text)


def yaml_safe_load_cached_text(text: str | bytes) -> Any:
    """Parse trusted YAML text with a content-keyed cache.

    The cached value is deep-copied before returning so callers can preserve the
    long-standing "fresh parse result" behavior even when repeated config-cache
    clears read identical bytes.
    """

    return deepcopy(_cached_yaml_safe_load_text(text))


__all__ = [
    "yaml_safe_load",
    "yaml_safe_load_cached_text",
]
