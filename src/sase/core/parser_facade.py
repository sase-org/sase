"""sase.core facade for ChangeSpec parsing.

This is the Rust-bindable seam for ChangeSpec parsing. Callers go through
:func:`parse_project_file` (returning Python ``ChangeSpec`` objects for
backward compatibility) or :func:`parse_project_bytes` (returning wire
records, the shape Rust ``parse_project_bytes`` produces).

Phase 8D rewired :func:`parse_project_bytes` to call ``sase_core_rs``
directly through :func:`sase.core.rust.require_rust_binding` and deleted
the Python tempfile-bridge fallback. The Rust extension is a hard runtime
dependency (declared in ``pyproject.toml``); a missing or stale wheel
surfaces as :class:`ImportError` / :class:`AttributeError` instead of
silently returning Python output.

:func:`parse_project_file` is intentionally Python-only host logic. The
Rust binding consumes bytes; routing the file-path API through it would
either re-read the file or duplicate the Python parser's tokenization
work for no measurable benefit.
"""

from __future__ import annotations

from typing import Any

from sase.ace.changespec.models import ChangeSpec
from sase.ace.changespec.parser import parse_project_file_python
from sase.core.rust import require_rust_binding
from sase.core.wire import ChangeSpecWire
from sase.core.wire_conversion import changespec_wire_from_dict


def parse_project_file(file_path: str) -> list[ChangeSpec]:
    """Parse all ChangeSpecs from a project file using the Python parser."""
    return parse_project_file_python(file_path)


# pyvision: tests/test_core_facade/test_parser.py
def parse_project_bytes(file_path: str, data: bytes) -> list[ChangeSpecWire]:
    """Parse a project file's bytes into wire records via ``sase_core_rs``.

    Calls the Rust ``parse_project_bytes`` binding directly and rehydrates
    the returned dicts into :class:`ChangeSpecWire` records. There is no
    Python fallback — a missing or stale Rust extension raises an
    :class:`ImportError` / :class:`AttributeError` from
    :func:`require_rust_binding` rather than silently switching paths.
    """
    rust_parse_project_bytes = require_rust_binding("parse_project_bytes")
    raw: list[dict[str, Any]] = rust_parse_project_bytes(file_path, data)
    return [changespec_wire_from_dict(record) for record in raw]
