"""A drop-in ``yaml.safe_load`` that prefers the LibYAML C loader.

``yaml.safe_load`` always parses with the pure-Python ``SafeLoader``, even
when the ``libyaml`` C bindings are installed. For trusted, JSON-shaped
configuration such as ``default_config.yml`` and ``sase.yml``, parsing with
``yaml.CSafeLoader`` instead is an order of magnitude faster and raises the
same ``yaml.YAMLError`` subclasses on malformed input, so callers can switch
loaders without changing behavior.
"""

from __future__ import annotations

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


__all__ = ["yaml_safe_load"]
