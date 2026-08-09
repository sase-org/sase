"""sase.core facade for Patch parsing.

:func:`parse_patch_project_bytes` calls
``sase_core_rs.parse_patch_project_bytes`` directly through
:func:`sase.core.rust.require_rust_binding` and rehydrates the returned dicts
into :class:`PatchWire` records. :func:`parse_project_bytes` preserves the
legacy ChangeSpec wire shape.

:func:`parse_patch_project_file` returns Python :class:`Patch` objects from a
file path and stays Python-only host logic — the Rust binding consumes
bytes, and routing the file-path API through it would either re-read the
file or duplicate the Python parser's tokenization work for no measurable
benefit.
"""

from __future__ import annotations

from typing import Any

from sase.ace.patch.models import Patch
from sase.ace.patch.parser import parse_patch_project_file_python
from sase.core.rust import require_rust_binding
from sase.core.wire import ChangeSpecWire, PatchWire  # legacy wire type
from sase.core.wire_conversion import (
    changespec_wire_from_dict,  # legacy wire converter
    patch_wire_from_dict,
)


def parse_patch_project_file(file_path: str) -> list[Patch]:
    """Parse all Patches from a project file using the Python parser."""
    return parse_patch_project_file_python(file_path)


def parse_project_file(file_path: str) -> list[Patch]:
    """Legacy alias returning the same objects as :func:`parse_patch_project_file`."""
    return parse_patch_project_file(file_path)


# symvision: tools/validate_sase_core_rs
def parse_patch_project_bytes(file_path: str, data: bytes) -> list[PatchWire]:
    """Parse a project file's bytes into canonical Patch wire records via Rust."""
    rust_parse_patch_project_bytes = require_rust_binding("parse_patch_project_bytes")
    raw: list[dict[str, Any]] = rust_parse_patch_project_bytes(file_path, data)
    return [patch_wire_from_dict(record) for record in raw]


# symvision: tools/validate_sase_core_rs
def parse_project_bytes(file_path: str, data: bytes) -> list[ChangeSpecWire]:
    """Parse a project file's bytes into legacy ChangeSpec wire records via Rust."""
    rust_parse_project_bytes = require_rust_binding("parse_project_bytes")
    raw: list[dict[str, Any]] = rust_parse_project_bytes(file_path, data)
    return [
        changespec_wire_from_dict(record) for record in raw
    ]  # legacy wire converter
