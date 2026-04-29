"""sase.core facade for ChangeSpec parsing.

This is the Rust-bindable seam for ChangeSpec parsing. Callers go through
:func:`parse_project_file` (returning Python ``ChangeSpec`` objects for
backward compatibility) or :func:`parse_project_bytes` (returning wire
records, the shape Phase 1's Rust ``parse_project_bytes`` will produce).

Both functions delegate through :func:`sase.core.backend.dispatch`. Phase 1D
wires the ``sase_core_rs.parse_project_bytes`` PyO3 binding in as the
``rust_impl`` for :func:`parse_project_bytes` whenever the extension module
is importable. :func:`parse_project_file` keeps the Python implementation for
now: switching it to the bytes-via-Rust path would bypass the dual-run
comparison logging by reading the file twice on disk, which is exactly the
metric Phase 1 wants to keep clean.
"""

from __future__ import annotations

from typing import Any

from sase.ace.changespec.models import ChangeSpec
from sase.ace.changespec.parser import parse_project_file_python
from sase.core.backend import dispatch, load_rust_extension
from sase.core.wire import ChangeSpecWire
from sase.core.wire_conversion import changespec_to_wire, changespec_wire_from_dict


def parse_project_file(file_path: str) -> list[ChangeSpec]:
    """Parse all ChangeSpecs from a project file via the active backend.

    Phase 1D keeps this on the Python backend even when ``sase_core_rs`` is
    available. The Rust binding consumes bytes, not file paths; routing
    through it here would either re-read the file (defeating the perf
    rationale) or drop dual-run comparison fidelity. The bytes-shaped
    :func:`parse_project_bytes` is the Rust-eligible entry point.
    """
    return dispatch(
        operation="parse_project_file",
        python_impl=parse_project_file_python,
        args=(file_path,),
        source_path=file_path,
    )


def _rust_parse_project_bytes_impl(file_path: str, data: bytes) -> list[ChangeSpecWire]:
    """Adapter from ``sase_core_rs.parse_project_bytes`` to typed wire records.

    Rebuilt as a function (not a partial / lambda) so :class:`ImportError`
    surfaces with a clear traceback if the extension was uninstalled
    between :func:`is_rust_available`-style probes and an actual call.
    """
    rust_module = load_rust_extension()
    if rust_module is None:
        raise RuntimeError(
            "sase_core_rs is not importable; the Rust backend was registered "
            "but the extension module disappeared at call time."
        )
    raw: list[dict[str, Any]] = rust_module.parse_project_bytes(file_path, data)  # type: ignore[attr-defined]
    return [changespec_wire_from_dict(record) for record in raw]


# pyvision: tests/test_core_facade.py
def parse_project_bytes(file_path: str, data: bytes) -> list[ChangeSpecWire]:
    """Parse a project file's bytes into wire records.

    The Python implementation writes ``data`` to a temp file and reuses the
    on-disk parser, then projects each ``ChangeSpec`` through
    :func:`changespec_to_wire`. The Rust implementation, when
    ``sase_core_rs`` is installed, parses bytes directly and returns plain
    dicts that we rehydrate with :func:`changespec_wire_from_dict`.
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

    rust_module = load_rust_extension()
    rust_impl = _rust_parse_project_bytes_impl if rust_module is not None else None

    return dispatch(
        operation="parse_project_bytes",
        python_impl=_python_impl,
        rust_impl=(
            (lambda: rust_impl(file_path, data)) if rust_impl is not None else None
        ),
        args=(),
        source_path=file_path,
    )
