"""Golden contract tests for the sase.core facade (Phase 0C).

These snapshots capture the wire shape, query canonical form, query evaluation
results, graph index summary, and pure status helpers over a sanitized in-tree
``.gp`` corpus. A future Rust backend must reproduce these snapshots byte for
byte; until then the snapshots also pin the Python implementation's behavior
so Phase 0B routing changes can't drift silently.

The corpus lives in ``tests/core_golden/`` and intentionally exercises every
section type a ``ChangeSpec`` can carry, plus archive/terminal statuses and
sibling suffixes.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from inline_snapshot import snapshot

from sase.ace.changespec.models import ChangeSpec
from sase.ace.query.types import to_canonical_string
from sase.core import (
    graph_index_facade,
    parser_facade,
    query_facade,
    status_facade,
)
from sase.core.wire import to_json_dict
from sase.core.wire_conversion import changespec_to_wire

pytestmark = pytest.mark.usefixtures("python_core_backend")

_CORPUS_DIR = Path(__file__).parent / "core_golden"
_PROJECT_GP = _CORPUS_DIR / "myproj.gp"
_ARCHIVE_GP = _CORPUS_DIR / "myproj-archive.gp"


def _load(path: Path) -> list[ChangeSpec]:
    return parser_facade.parse_project_file(str(path))


def _wire_dicts(specs: list[ChangeSpec]) -> list[dict]:
    """Project specs to JSON-safe wire dicts with file paths normalized.

    The absolute ``file_path`` is replaced with its basename so snapshots are
    stable across checkouts.
    """
    out: list[dict] = []
    for cs in specs:
        wire = changespec_to_wire(cs)
        d = to_json_dict(wire)
        d["file_path"] = Path(d["file_path"]).name
        d["source_span"]["file_path"] = Path(d["source_span"]["file_path"]).name
        out.append(d)
    return out


def test_corpus_parses_to_expected_names() -> None:
    """Sanity guard: if a corpus file is reformatted by accident, this fails fast."""
    project_specs = _load(_PROJECT_GP)
    archive_specs = _load(_ARCHIVE_GP)
    assert [cs.name for cs in project_specs] == [
        "alpha",
        "beta",
        "beta__260102_010101",
        "gamma",
    ]
    assert [cs.name for cs in archive_specs] == ["archived_one", "reverted_two"]


def test_changespec_wire_json_snapshot() -> None:
    """Full ChangeSpecWire JSON shape for the canonical project corpus."""
    specs = _load(_PROJECT_GP)
    payload = _wire_dicts(specs)
    assert payload == snapshot(
        [
            {
                "schema_version": 1,
                "name": "alpha",
                "project_basename": "myproj",
                "file_path": "myproj.gp",
                "source_span": {
                    "file_path": "myproj.gp",
                    "start_line": 2,
                    "end_line": 2,
                },
                "status": "Submitted",
                "parent": None,
                "cl_or_pr": "https://example.test/repo/pull/1",
                "bug": "BUG-100",
                "description": "Initial feature work.\nSpans multiple lines.",
                "test_targets": ["tests/test_alpha.py"],
                "kickstart": "Kick this off carefully.",
                "commits": [
                    {
                        "number": 1,
                        "note": "[run] Initial Commit",
                        "chat": "~/.sase/chats/alpha.md (0s)",
                        "diff": "~/.sase/diffs/alpha.diff",
                        "plan": None,
                        "proposal_letter": None,
                        "suffix": None,
                        "suffix_type": None,
                        "body": [],
                    }
                ],
                "hooks": [
                    {
                        "command": "just lint",
                        "status_lines": [
                            {
                                "commit_entry_num": "1",
                                "timestamp": "260101_120000",
                                "status": "PASSED",
                                "duration": "3s",
                                "suffix": None,
                                "suffix_type": None,
                                "summary": None,
                            }
                        ],
                    }
                ],
                "comments": [
                    {
                        "reviewer": "critique",
                        "file_path": "~/.sase/comments/alpha.json",
                        "suffix": "Unresolved Critique Comments",
                        "suffix_type": "error",
                    }
                ],
                "mentors": [
                    {
                        "entry_id": "1",
                        "profiles": ["profileA"],
                        "status_lines": [
                            {
                                "profile_name": "profileA",
                                "mentor_name": "mentor1",
                                "status": "PASSED",
                                "timestamp": "260101_130000",
                                "duration": "1m0s",
                                "suffix": None,
                                "suffix_type": "plain",
                            }
                        ],
                        "is_draft": False,
                    }
                ],
                "timestamps": [
                    {
                        "timestamp": "260101_120000",
                        "event_type": "STATUS",
                        "detail": "WIP -> Submitted",
                    }
                ],
                "deltas": [
                    {"path": "src/alpha.py", "change_type": "A"},
                    {"path": "src/util.py", "change_type": "M"},
                ],
            },
            {
                "schema_version": 1,
                "name": "beta",
                "project_basename": "myproj",
                "file_path": "myproj.gp",
                "source_span": {
                    "file_path": "myproj.gp",
                    "start_line": 32,
                    "end_line": 32,
                },
                "status": "WIP",
                "parent": "alpha",
                "cl_or_pr": None,
                "bug": None,
                "description": "Sibling feature.",
                "test_targets": [],
                "kickstart": None,
                "commits": [],
                "hooks": [],
                "comments": [],
                "mentors": [],
                "timestamps": [],
                "deltas": [],
            },
            {
                "schema_version": 1,
                "name": "beta__260102_010101",
                "project_basename": "myproj",
                "file_path": "myproj.gp",
                "source_span": {
                    "file_path": "myproj.gp",
                    "start_line": 39,
                    "end_line": 39,
                },
                "status": "Reverted",
                "parent": "alpha",
                "cl_or_pr": None,
                "bug": None,
                "description": "Reverted retry of beta.",
                "test_targets": [],
                "kickstart": None,
                "commits": [],
                "hooks": [],
                "comments": [],
                "mentors": [],
                "timestamps": [],
                "deltas": [],
            },
            {
                "schema_version": 1,
                "name": "gamma",
                "project_basename": "myproj",
                "file_path": "myproj.gp",
                "source_span": {
                    "file_path": "myproj.gp",
                    "start_line": 46,
                    "end_line": 46,
                },
                "status": "Ready",
                "parent": None,
                "cl_or_pr": None,
                "bug": None,
                "description": "Ready feature with running agent.",
                "test_targets": [],
                "kickstart": None,
                "commits": [],
                "hooks": [
                    {
                        "command": "just test",
                        "status_lines": [
                            {
                                "commit_entry_num": "1",
                                "timestamp": "260103_140000",
                                "status": "RUNNING",
                                "duration": None,
                                "suffix": "ace-260103_140000",
                                "suffix_type": "running_agent",
                                "summary": None,
                            }
                        ],
                    }
                ],
                "comments": [],
                "mentors": [],
                "timestamps": [],
                "deltas": [],
            },
        ]
    )


def test_archive_corpus_wire_json_snapshot() -> None:
    """Archive files only carry terminal-status specs."""
    specs = _load(_ARCHIVE_GP)
    payload = _wire_dicts(specs)
    assert payload == snapshot(
        [
            {
                "schema_version": 1,
                "name": "archived_one",
                "project_basename": "myproj",
                "file_path": "myproj-archive.gp",
                "source_span": {
                    "file_path": "myproj-archive.gp",
                    "start_line": 1,
                    "end_line": 1,
                },
                "status": "Archived",
                "parent": None,
                "cl_or_pr": "https://example.test/repo/pull/99",
                "bug": None,
                "description": "An archived spec.",
                "test_targets": [],
                "kickstart": None,
                "commits": [
                    {
                        "number": 1,
                        "note": "[run] Initial Commit",
                        "chat": "~/.sase/chats/archived_one.md (0s)",
                        "diff": None,
                        "plan": None,
                        "proposal_letter": None,
                        "suffix": None,
                        "suffix_type": None,
                        "body": [],
                    }
                ],
                "hooks": [],
                "comments": [],
                "mentors": [],
                "timestamps": [],
                "deltas": [],
            },
            {
                "schema_version": 1,
                "name": "reverted_two",
                "project_basename": "myproj",
                "file_path": "myproj-archive.gp",
                "source_span": {
                    "file_path": "myproj-archive.gp",
                    "start_line": 11,
                    "end_line": 11,
                },
                "status": "Reverted",
                "parent": None,
                "cl_or_pr": None,
                "bug": None,
                "description": "A reverted spec.",
                "test_targets": [],
                "kickstart": None,
                "commits": [],
                "hooks": [],
                "comments": [],
                "mentors": [],
                "timestamps": [],
                "deltas": [],
            },
        ]
    )


def test_query_canonical_parse_snapshot() -> None:
    """Query parser canonical form is part of the contract."""
    cases = [
        '"alpha"',
        "status:Ready",
        "status:Reverted OR status:Submitted",
        'ancestor:alpha AND NOT "beta"',
        "!!!",
        "@@@",
    ]
    canonical = {q: to_canonical_string(query_facade.parse_query(q)) for q in cases}
    assert canonical == snapshot(
        {
            '"alpha"': '"alpha"',
            "status:Ready": "status:Ready",
            "status:Reverted OR status:Submitted": "status:Reverted OR status:Submitted",
            'ancestor:alpha AND NOT "beta"': 'ancestor:alpha AND NOT "beta"',
            "!!!": "!!!",
            "@@@": "@@@",
        }
    )


def test_query_evaluation_results_snapshot() -> None:
    """Evaluating each canonical query against the corpus yields a stable matrix."""
    specs = _load(_PROJECT_GP)
    queries = [
        '"alpha"',
        "status:Ready",
        "status:Reverted OR status:Submitted",
        "ancestor:alpha",
        'ancestor:alpha AND NOT "beta"',
        "@@@",
    ]
    ctx = query_facade.build_query_context(specs)
    matrix = {
        q: [
            cs.name
            for cs in specs
            if query_facade.evaluate_query_with_context(
                query_facade.parse_query(q), cs, ctx
            )
        ]
        for q in queries
    }
    assert matrix == snapshot(
        {
            '"alpha"': ["alpha", "beta", "beta__260102_010101"],
            "status:Ready": ["gamma"],
            "status:Reverted OR status:Submitted": ["alpha", "beta__260102_010101"],
            "ancestor:alpha": ["alpha", "beta", "beta__260102_010101"],
            'ancestor:alpha AND NOT "beta"': ["alpha"],
            "@@@": ["gamma"],
        }
    )


def test_graph_index_summary_snapshot() -> None:
    """Stable summary of the graph index over the project corpus."""
    specs = _load(_PROJECT_GP)
    index = graph_index_facade.build_changespec_graph_index(specs)
    summary = {
        "names": sorted(index.name_map.keys()),
        "children_of_alpha": [cs.name for cs in index.get_children("alpha")],
        "children_of_gamma": [cs.name for cs in index.get_children("gamma")],
        "siblings_of_beta": [
            cs.name for cs in index.get_siblings_of(index.name_map["beta"])
        ],
        "status_of_beta": index.get_status("beta"),
        "status_of_gamma": index.get_status("gamma"),
        "status_of_unknown": index.get_status("nope"),
        "terminal_count": index.terminal_count,
        "submitted_count": index.submitted_count,
    }
    assert summary == snapshot(
        {
            "names": [
                "alpha",
                "beta",
                "beta__260102_010101",
                "gamma",
            ],
            "children_of_alpha": ["beta", "beta__260102_010101"],
            "children_of_gamma": [],
            "siblings_of_beta": [],
            "status_of_beta": "WIP",
            "status_of_gamma": "Ready",
            "status_of_unknown": "WIP",
            "terminal_count": 1,
            "submitted_count": 1,
        }
    )


def test_status_field_helpers_snapshot() -> None:
    """``read_status_from_lines`` + ``apply_status_update`` over the corpus."""
    lines = _PROJECT_GP.read_text().splitlines(keepends=True)
    reads = {
        "alpha": status_facade.read_status_from_lines(lines, "alpha"),
        "beta": status_facade.read_status_from_lines(lines, "beta"),
        "beta__260102_010101": status_facade.read_status_from_lines(
            lines, "beta__260102_010101"
        ),
        "gamma": status_facade.read_status_from_lines(lines, "gamma"),
        "missing": status_facade.read_status_from_lines(lines, "missing"),
    }
    assert reads == snapshot(
        {
            "alpha": "Submitted",
            "beta": "WIP",
            "beta__260102_010101": "Reverted",
            "gamma": "Ready",
            "missing": None,
        }
    )

    updated = status_facade.apply_status_update(lines, "beta", "Draft")
    # Only beta's STATUS line should change; everything else byte-identical.
    original = "".join(lines)
    assert updated != original
    assert "STATUS: Draft" in updated
    # Other specs untouched.
    assert (
        "NAME: beta__260102_010101\nDESCRIPTION: Reverted retry of beta.\n" in updated
    )
    # Idempotency: applying the current status returns equivalent content.
    same = status_facade.apply_status_update(lines, "alpha", "Submitted")
    assert same == original


def test_dual_run_with_fake_rust_over_corpus(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Fake-Rust ``parse_project_file`` runs against the golden corpus through
    :func:`sase.core.backend.dispatch`, producing a single JSONL record that
    matches the documented schema.

    This is the end-to-end shape Phase 1 will exercise once a real Rust
    backend is registered: the corpus is the input and the dual-run logger
    is what proves parity.
    """
    from sase.core.backend import (
        BACKEND_ENV_VAR,
        DUAL_RUN_ENV_VAR,
        dispatch,
    )
    from sase.core.dual_run import DUAL_RUN_LOG_OVERRIDE_ENV_VAR

    log = tmp_path / "dual.jsonl"
    monkeypatch.setenv(DUAL_RUN_LOG_OVERRIDE_ENV_VAR, str(log))
    monkeypatch.setenv(DUAL_RUN_ENV_VAR, "1")
    monkeypatch.delenv(BACKEND_ENV_VAR, raising=False)

    def fake_rust(file_path: str) -> list[ChangeSpec]:
        # Return identical wire-equivalent specs by reusing the python parser.
        return parser_facade.parse_project_file(file_path)

    result = dispatch(
        operation="parse_project_file",
        python_impl=parser_facade.parse_project_file,
        rust_impl=fake_rust,
        args=(str(_PROJECT_GP),),
        source_path=str(_PROJECT_GP),
    )
    assert [cs.name for cs in result] == [
        "alpha",
        "beta",
        "beta__260102_010101",
        "gamma",
    ]

    [row] = [json.loads(line) for line in log.read_text().splitlines() if line]
    assert row["operation"] == "parse_project_file"
    assert row["source_path"] == str(_PROJECT_GP)
    assert row["match"] is True
    assert row["error_class"] is None
    assert row["schema_version"] == 1


def test_dual_run_with_diverging_fake_rust(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A fake Rust that drops a spec produces a mismatch record with a path."""
    from sase.core.backend import (
        BACKEND_ENV_VAR,
        DUAL_RUN_ENV_VAR,
        dispatch,
    )
    from sase.core.dual_run import DUAL_RUN_LOG_OVERRIDE_ENV_VAR

    log = tmp_path / "dual_mismatch.jsonl"
    monkeypatch.setenv(DUAL_RUN_LOG_OVERRIDE_ENV_VAR, str(log))
    monkeypatch.setenv(DUAL_RUN_ENV_VAR, "1")
    monkeypatch.delenv(BACKEND_ENV_VAR, raising=False)

    def fake_rust_drops_last(file_path: str) -> list[ChangeSpec]:
        specs = parser_facade.parse_project_file(file_path)
        return specs[:-1]  # drop gamma

    def to_jsonable(specs: list[ChangeSpec]) -> list[dict]:
        return [to_json_dict(changespec_to_wire(cs)) for cs in specs]

    result = dispatch(
        operation="parse_project_file",
        python_impl=parser_facade.parse_project_file,
        rust_impl=fake_rust_drops_last,
        args=(str(_PROJECT_GP),),
        source_path=str(_PROJECT_GP),
        kwargs=None,
    )
    # The Python result is always returned even when Rust diverges.
    assert [cs.name for cs in result] == [
        "alpha",
        "beta",
        "beta__260102_010101",
        "gamma",
    ]
    # And the mismatch is logged with a meaningful diff path.
    [row] = [json.loads(line) for line in log.read_text().splitlines() if line]
    assert row["match"] is False
    # The first diff happens at index 3 (the dropped gamma entry).
    assert (
        row["first_diff_path"] is not None
        and row["first_diff_path"].startswith("/3")
        or row["first_diff_path"] == "."
    )
    # Sanity: the json-dictified comparison would have caught it.
    assert to_jsonable(result) != to_jsonable(fake_rust_drops_last(str(_PROJECT_GP)))


def test_explicit_rust_backend_with_fake_impl_uses_rust(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``SASE_CORE_BACKEND=rust`` with a registered fake rust returns its result."""
    from sase.core.backend import BACKEND_ENV_VAR, DUAL_RUN_ENV_VAR, dispatch

    monkeypatch.setenv(BACKEND_ENV_VAR, "rust")
    monkeypatch.delenv(DUAL_RUN_ENV_VAR, raising=False)

    sentinel = object()

    def python_impl() -> object:  # pragma: no cover - must not run
        raise AssertionError("python should not be called when rust=on")

    def rust_impl() -> object:
        return sentinel

    assert (
        dispatch(operation="op", python_impl=python_impl, rust_impl=rust_impl)
        is sentinel
    )


def test_wire_json_is_byte_stable() -> None:
    """Two parses of the same corpus must produce byte-identical JSON.

    This is the property the Rust backend's ``wire_to_json`` must preserve.
    """
    a = json.dumps(_wire_dicts(_load(_PROJECT_GP)), sort_keys=True)
    b = json.dumps(_wire_dicts(_load(_PROJECT_GP)), sort_keys=True)
    assert a == b
