"""Phase 1F cross-repo parity smoke test.

Python-side counterpart to
``../sase-core/crates/sase_core/tests/golden_corpus_parity.rs``. When the
optional ``sase_core_rs`` PyO3 extension is importable, parse the in-tree
golden ``.gp`` corpus through both backends — both via direct
``sase_core_rs.parse_project_bytes`` and through the
``SASE_CORE_BACKEND=rust`` facade route wired up in Phase 1D — and compare
the JSON shape byte-for-byte after the documented
``source_span.end_line`` normalization (see
``plans/202604/rust_backend_phase1.md``).

The test is skipped when the extension is not installed, so pure-Python
``just check`` is unaffected.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.core import parser_facade
from sase.core.backend import BACKEND_ENV_VAR, DUAL_RUN_ENV_VAR
from sase.core.wire import to_json_dict
from sase.core.wire_conversion import changespec_to_wire

_CORPUS_DIR = Path(__file__).parent / "core_golden"
_PROJECT_GP = _CORPUS_DIR / "myproj.gp"
_ARCHIVE_GP = _CORPUS_DIR / "myproj-archive.gp"

sase_core_rs = pytest.importorskip(
    "sase_core_rs",
    reason="Rust extension not installed; run `just rust-install` from sase_100 "
    "or `maturin develop --release` from ../sase-core/crates/sase_core_py.",
)


def _python_payload(path: Path) -> list[dict]:
    """Python facade output projected to JSON-safe dicts with basenames."""
    specs = parser_facade.parse_project_file(str(path))
    out: list[dict] = []
    for cs in specs:
        wire = changespec_to_wire(cs)
        d = to_json_dict(wire)
        d["file_path"] = Path(d["file_path"]).name
        d["source_span"]["file_path"] = Path(d["source_span"]["file_path"]).name
        out.append(d)
    return out


def _normalize_end_line(payload: list[dict]) -> list[dict]:
    """Normalize ``source_span.end_line`` to ``start_line`` (Python parity).

    Rust tracks real end lines while Python's ``changespec_to_wire`` defaults
    ``end_line == start_line``. Phase 1F decision: keep the normalization at
    the parity boundary; do not backfill Python end-line tracking. See
    ``plans/202604/rust_backend_phase1_handoff.md``.
    """
    for spec in payload:
        spec["source_span"]["end_line"] = spec["source_span"]["start_line"]
    return payload


def _rust_direct_payload(path: Path) -> list[dict]:
    raw = sase_core_rs.parse_project_bytes(path.name, path.read_bytes())
    return _normalize_end_line(raw)


def _rust_facade_payload(path: Path, monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    """Drive Phase 1D's ``SASE_CORE_BACKEND=rust`` route end-to-end.

    This is the production code path for callers that opt into the Rust
    backend, including the dict→``ChangeSpecWire`` rehydration step.
    """
    monkeypatch.setenv(BACKEND_ENV_VAR, "rust")
    monkeypatch.delenv(DUAL_RUN_ENV_VAR, raising=False)
    wires = parser_facade.parse_project_bytes(path.name, path.read_bytes())
    out = [to_json_dict(w) for w in wires]
    return _normalize_end_line(out)


@pytest.mark.parametrize("corpus", [_PROJECT_GP, _ARCHIVE_GP], ids=lambda p: p.name)
def test_rust_direct_matches_python_golden(corpus: Path) -> None:
    py = _python_payload(corpus)
    rs = _rust_direct_payload(corpus)
    # Compare via JSON dumps so dict ordering differences fail loudly with a
    # pretty diff rather than silently passing on equal-but-reordered keys.
    assert json.dumps(rs, sort_keys=True) == json.dumps(py, sort_keys=True)


@pytest.mark.parametrize("corpus", [_PROJECT_GP, _ARCHIVE_GP], ids=lambda p: p.name)
def test_rust_facade_matches_python_golden(
    corpus: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """End-to-end facade route (Phase 1D wiring): bytes → PyO3 → wire dataclass → JSON."""
    py = _python_payload(corpus)
    rs = _rust_facade_payload(corpus, monkeypatch)
    assert json.dumps(rs, sort_keys=True) == json.dumps(py, sort_keys=True)


def test_rust_reports_real_end_line_beyond_python_placeholder() -> None:
    """Sanity check the documented improvement: Rust's ``end_line`` is real.

    At least one spec in the project corpus spans multiple lines. If Rust
    were also defaulting ``end_line == start_line`` the normalization would
    be hiding a regression, so we assert the unnormalized Rust output here.
    """
    raw = sase_core_rs.parse_project_bytes(_PROJECT_GP.name, _PROJECT_GP.read_bytes())
    alpha = next(s for s in raw if s["name"] == "alpha")
    span = alpha["source_span"]
    assert span["end_line"] > span["start_line"], (
        "Rust parser should track real end_line; got "
        f"start={span['start_line']} end={span['end_line']}"
    )
