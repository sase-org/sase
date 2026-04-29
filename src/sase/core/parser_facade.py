"""sase.core facade for ChangeSpec parsing.

This is the Rust-bindable seam for ChangeSpec parsing. Callers go through
:func:`parse_project_file` (returning Python ``ChangeSpec`` objects for
backward compatibility) or :func:`parse_project_bytes` (returning wire
records, the shape Phase 1's Rust ``parse_project_bytes`` will produce).

Both functions delegate through :func:`sase.core.backend.dispatch`, so a
future Rust ``sase_core_rs.parse_project_bytes`` can register itself as the
``rust_impl`` without touching this module's signature.
"""

from __future__ import annotations

from sase.ace.changespec.models import ChangeSpec
from sase.ace.changespec.parser import parse_project_file_python
from sase.core.backend import dispatch
from sase.core.wire import ChangeSpecWire
from sase.core.wire_conversion import changespec_to_wire


def parse_project_file(file_path: str) -> list[ChangeSpec]:
    """Parse all ChangeSpecs from a project file via the active backend."""
    return dispatch(
        operation="parse_project_file",
        python_impl=parse_project_file_python,
        args=(file_path,),
        source_path=file_path,
    )


# pyvision: tests/test_core_facade.py
def parse_project_bytes(file_path: str, data: bytes) -> list[ChangeSpecWire]:
    """Parse a project file's bytes into wire records.

    This is the shape a future Rust ``parse_project_bytes`` will implement.
    The Phase 0A Python implementation writes ``data`` to a temp file (or
    decodes to a string and tee'd lines) and reuses
    :func:`parse_project_file`. We keep that detail behind the facade so the
    contract can be stabilized now.
    """

    def _python_impl() -> list[ChangeSpecWire]:
        # The existing Python parser reads from an open file. Phase 0A keeps
        # the simplest possible bridge: write the bytes to a temporary file
        # and reuse it. The Rust parser will skip this round-trip entirely.
        import tempfile

        with tempfile.NamedTemporaryFile("wb", suffix=".gp", delete=True) as tmp:
            tmp.write(data)
            tmp.flush()
            specs = parse_project_file_python(tmp.name)
        # Rewrite file_path on the wire record to the caller-supplied path so
        # downstream consumers see the canonical project file.
        wires: list[ChangeSpecWire] = []
        for cs in specs:
            cs.file_path = file_path
            wires.append(changespec_to_wire(cs))
        return wires

    return dispatch(
        operation="parse_project_bytes",
        python_impl=_python_impl,
        args=(),
        source_path=file_path,
    )
