"""Shared config-key helpers for project glossary readers."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

MEMORY_CONFIG_KEY = "memory"
GLOSSARY_CONFIG_KEY = "glossary"
MEMORY_GLOSSARY_CONFIG_KEY_PATH = (MEMORY_CONFIG_KEY, GLOSSARY_CONFIG_KEY)


@dataclass(frozen=True, slots=True)
class _GlossaryConfigResolution:
    """Resolved glossary config location in one YAML mapping."""

    node: Any | None
    key_path: tuple[str, ...]
    display_path: str
    declared: bool = False
    error: str | None = None


def resolve_glossary_config(config: Mapping[Any, Any]) -> _GlossaryConfigResolution:
    """Resolve ``memory.glossary``."""

    if MEMORY_CONFIG_KEY in config:
        memory = config[MEMORY_CONFIG_KEY]
        if not isinstance(memory, Mapping):
            return _GlossaryConfigResolution(
                None,
                (MEMORY_CONFIG_KEY,),
                MEMORY_CONFIG_KEY,
                declared=True,
                error=f"{MEMORY_CONFIG_KEY} must be a mapping",
            )
        if GLOSSARY_CONFIG_KEY in memory:
            return _GlossaryConfigResolution(
                memory[GLOSSARY_CONFIG_KEY],
                MEMORY_GLOSSARY_CONFIG_KEY_PATH,
                ".".join(MEMORY_GLOSSARY_CONFIG_KEY_PATH),
                declared=True,
            )

    return _GlossaryConfigResolution(
        None,
        MEMORY_GLOSSARY_CONFIG_KEY_PATH,
        ".".join(MEMORY_GLOSSARY_CONFIG_KEY_PATH),
    )


__all__ = [
    "GLOSSARY_CONFIG_KEY",
    "MEMORY_CONFIG_KEY",
    "MEMORY_GLOSSARY_CONFIG_KEY_PATH",
    "resolve_glossary_config",
]
