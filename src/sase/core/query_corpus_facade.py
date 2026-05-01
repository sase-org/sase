"""Persistent-corpus query facade for Rust-backed batch evaluation.

The legacy :func:`sase.core.query_facade.evaluate_query_many` entry point
intentionally remains on the Python batch path during this phase. This module
exposes the new handle-oriented Rust API so callers can compile a corpus once
for a stable ``list[ChangeSpec]`` object and evaluate many query strings
against it without rebuilding ChangeSpec wire records per keystroke.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sase.ace.changespec.models import ChangeSpec
from sase.core.rust import require_rust_binding
from sase.core.wire import to_json_dict
from sase.core.wire_conversion import changespec_to_wire


# pyvision: tests/test_core_facade/test_query.py
@dataclass(frozen=True)
class QueryCorpus:
    """Python-side cache metadata for a Rust query corpus handle."""

    source_list_id: int
    expected_length: int
    rust_handle: Any

    def validate(self) -> None:
        """Raise if the wrapper no longer matches the owned Rust corpus."""
        actual_length = _rust_corpus_length(self.rust_handle)
        if actual_length != self.expected_length:
            raise ValueError(
                "stale query corpus wrapper: expected "
                f"{self.expected_length} specs but Rust handle contains "
                f"{actual_length}; rebuild the corpus for the current "
                "ChangeSpec list before evaluating"
            )


# pyvision: tests/test_core_facade/test_query.py
def compile_query_corpus(changespecs: list[ChangeSpec]) -> QueryCorpus:
    """Compile ``changespecs`` into a persistent Rust query corpus handle."""
    compile_corpus = require_rust_binding("compile_corpus")
    spec_dicts = [to_json_dict(changespec_to_wire(cs)) for cs in changespecs]
    rust_handle = compile_corpus(spec_dicts)
    corpus = QueryCorpus(
        source_list_id=id(changespecs),
        expected_length=len(changespecs),
        rust_handle=rust_handle,
    )
    corpus.validate()
    return corpus


# pyvision: tests/test_core_facade/test_query.py
def evaluate_query_many_with_corpus(query: str, corpus: QueryCorpus) -> list[bool]:
    """Evaluate ``query`` against a previously compiled query corpus."""
    corpus.validate()
    compile_query = require_rust_binding("compile_query")
    evaluate_many = require_rust_binding("evaluate_many")
    program = compile_query(query)
    return list(evaluate_many(program, corpus.rust_handle))


def _rust_corpus_length(rust_handle: Any) -> int:
    try:
        return len(rust_handle)
    except TypeError as exc:
        raise TypeError(
            "Rust query corpus handle does not expose __len__; reinstall with "
            "`just install` or `just rust-install` before using the persistent "
            "query corpus facade."
        ) from exc
