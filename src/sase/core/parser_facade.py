"""sase.core facade for ChangeSpec parsing.

:func:`parse_project_bytes` calls ``sase_core_rs.parse_project_bytes``
directly through :func:`sase.core.rust.require_rust_binding` and rehydrates
the returned dicts into :class:`ChangeSpecWire` records. The Rust extension
is a hard runtime dependency declared in ``pyproject.toml``; a missing or
stale wheel surfaces as :class:`ImportError` / :class:`AttributeError`.

:func:`parse_project_file` returns Python :class:`ChangeSpec` objects from a
file path and stays Python-only host logic — the Rust binding consumes
bytes, and routing the file-path API through it would either re-read the
file or duplicate the Python parser's tokenization work for no measurable
benefit.
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
    """Parse a project file's bytes into wire records via ``sase_core_rs``."""
    rust_parse_project_bytes = require_rust_binding("parse_project_bytes")
    raw: list[dict[str, Any]] = rust_parse_project_bytes(file_path, data)
    return [changespec_wire_from_dict(record) for record in raw]
