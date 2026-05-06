"""Shared helpers for ``sase.core`` facade tests.

Test fixtures live in ``conftest.py``; this module holds plain helpers and
sample text constants so they can be imported normally from the per-facade
test files.
"""

from __future__ import annotations

import importlib
import sys
import types

import pytest

from sase.ace.changespec.parser import parse_project_file_python
from sase.core.rust import RUST_EXTENSION_MODULE_NAME
from sase.core.wire_conversion import changespec_to_wire

SAMPLE_PROJECT_TEXT = """\
NAME: example
DESCRIPTION: Example feature.
PARENT:
PR:
STATUS: WIP

NAME: child
DESCRIPTION: Child of example.
PARENT: example
PR:
STATUS: WIP
"""


ANCESTRY_PROJECT_TEXT = """\
NAME: root
DESCRIPTION: Root of the chain.
PARENT:
PR:
STATUS: Draft

NAME: middle
DESCRIPTION: Middle of the chain.
PARENT: root
PR:
STATUS: WIP

NAME: leaf
DESCRIPTION: Leaf of the chain.
PARENT: middle
PR:
STATUS: Ready

NAME: family
DESCRIPTION: Base member of the family.
PARENT:
PR:
STATUS: WIP

NAME: family__260102_010101
DESCRIPTION: Reverted retry sibling.
PARENT:
PR:
STATUS: Reverted

NAME: unrelated
DESCRIPTION: No relation.
PARENT:
PR:
STATUS: Mailed
"""


def install_fake_status_module(
    monkeypatch: pytest.MonkeyPatch,
    *,
    read_status_from_lines=None,
    apply_status_update=None,
) -> types.ModuleType:
    """Register a fake ``sase_core_rs`` exposing the Phase 4D line helpers."""
    fake = types.ModuleType(RUST_EXTENSION_MODULE_NAME)
    if read_status_from_lines is not None:
        fake.read_status_from_lines = read_status_from_lines  # type: ignore[attr-defined]
    if apply_status_update is not None:
        fake.apply_status_update = apply_status_update  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, RUST_EXTENSION_MODULE_NAME, fake)
    return fake


def install_fake_rust_module(
    monkeypatch: pytest.MonkeyPatch,
    parse_fn,  # callable[[str, bytes], list[dict]]
) -> types.ModuleType:
    """Register a fake ``sase_core_rs`` module exposing ``parse_project_bytes``."""
    fake = types.ModuleType(RUST_EXTENSION_MODULE_NAME)
    fake.parse_project_bytes = parse_fn  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, RUST_EXTENSION_MODULE_NAME, fake)
    return fake


def install_fake_query_module(
    monkeypatch: pytest.MonkeyPatch,
    *,
    parse_query=None,
    evaluate_query_many=None,
    compile_corpus=None,
    compile_query=None,
    evaluate_many=None,
) -> types.ModuleType:
    """Register a fake ``sase_core_rs`` exposing query-related bindings."""
    fake = types.ModuleType(RUST_EXTENSION_MODULE_NAME)
    if parse_query is not None:
        fake.parse_query = parse_query  # type: ignore[attr-defined]
    if evaluate_query_many is not None:
        fake.evaluate_query_many = evaluate_query_many  # type: ignore[attr-defined]
    if compile_corpus is not None:
        fake.compile_corpus = compile_corpus  # type: ignore[attr-defined]
    if compile_query is not None:
        fake.compile_query = compile_query  # type: ignore[attr-defined]
    if evaluate_many is not None:
        fake.evaluate_many = evaluate_many  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, RUST_EXTENSION_MODULE_NAME, fake)
    return fake


def force_no_rust_extension(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delitem(sys.modules, RUST_EXTENSION_MODULE_NAME, raising=False)
    real_import_module = importlib.import_module

    def fail(name: str, *args, **kwargs):  # type: ignore[no-untyped-def]
        if name == RUST_EXTENSION_MODULE_NAME:
            raise ImportError(f"No module named {name!r}")
        return real_import_module(name, *args, **kwargs)

    monkeypatch.setattr(importlib, "import_module", fail)


def python_wire_records_as_dicts(file_path: str, _data: bytes) -> list[dict]:
    """Reuse the Python parser to manufacture the dict shape Rust would emit."""
    specs = parse_project_file_python(file_path)
    wires = []
    for cs in specs:
        cs.file_path = file_path
        wires.append(changespec_to_wire(cs))
    return [
        {
            "schema_version": w.schema_version,
            "name": w.name,
            "project_basename": w.project_basename,
            "file_path": w.file_path,
            "source_span": {
                "file_path": w.source_span.file_path,
                "start_line": w.source_span.start_line,
                "end_line": w.source_span.end_line,
            },
            "status": w.status,
            "parent": w.parent,
            "cl_or_pr": w.cl_or_pr,
            "bug": w.bug,
            "description": w.description,
            "test_targets": list(w.test_targets),
            "kickstart": w.kickstart,
            "commits": [],
            "hooks": [],
            "comments": [],
            "mentors": [],
            "timestamps": [],
            "deltas": [],
        }
        for w in wires
    ]


def basic_plan_request(
    *,
    changespec_name: str = "example",
    old_status: str = "WIP",
    new_status: str = "Draft",
    validate: bool = True,
):
    """Build a minimal :class:`StatusTransitionRequestWire` for facade tests."""
    from sase.core.status_wire import (
        STATUS_WIRE_SCHEMA_VERSION,
        StatusTransitionRequestWire,
    )

    return StatusTransitionRequestWire(
        schema_version=STATUS_WIRE_SCHEMA_VERSION,
        changespec_name=changespec_name,
        old_status=old_status,
        new_status=new_status,
        validate=validate,
        parent_status=None,
    )
