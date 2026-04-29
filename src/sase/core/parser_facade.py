"""sase.core facade for ChangeSpec parsing.

Phase 0A: thin wrapper around the existing Python parser, plus a
``parse_project_bytes`` convenience that the Rust backend will eventually back.
Phase 0B will route ``sase.ace.changespec.parser.parse_project_file`` through
:func:`parse_project_file`.
"""

from __future__ import annotations

from sase.ace.changespec.models import ChangeSpec
from sase.ace.changespec.parser import parse_project_file as _python_parse_project_file
from sase.core.backend import dispatch
from sase.core.wire import ChangeSpecWire
from sase.core.wire_conversion import changespec_to_wire


def parse_project_file(file_path: str) -> list[ChangeSpec]:
    """Parse all ChangeSpecs from a project file via the active backend."""
    return dispatch(
        operation="parse_project_file",
        python_impl=_python_parse_project_file,
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
            specs = _python_parse_project_file(tmp.name)
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
