"""Internal helpers shared by runtime version inventory modules."""

from __future__ import annotations

import re
from pathlib import Path

VERSION_TAG_RE = re.compile(r"^v(?P<version>\d+\.\d+\.\d+(?:[-.a-zA-Z0-9]*)?)$")
DISTRIBUTION_NORMALIZE_RE = re.compile(r"[-_.]+")
IMPORT_MODULE_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*$")


def version_from_tag(tag: str | None) -> str | None:
    if tag is None:
        return None
    match = VERSION_TAG_RE.fullmatch(tag)
    if match is None:
        return None
    return match.group("version")


def normalize_distribution_name(distribution_name: str) -> str:
    return DISTRIBUTION_NORMALIZE_RE.sub("-", distribution_name).lower()


def metadata_value(metadata: object, key: str) -> str | None:
    getter = getattr(metadata, "get", None)
    if not callable(getter):
        return None
    value = getter(key)
    return value if isinstance(value, str) and value else None


def safe_str(value: object, default: str) -> str:
    return value if isinstance(value, str) and value else default


def append_warning(warnings: list[str], warning: str) -> None:
    if warning not in warnings:
        warnings.append(warning)


def path_str(path: Path | None) -> str | None:
    if path is None:
        return None
    return str(path)
