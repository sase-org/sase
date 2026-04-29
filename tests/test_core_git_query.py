"""Golden tests pinning the Git query parser facade contract.

The Phase 5B contract guarantees that
:mod:`sase.core.git_query_facade` produces the exact strings exercised
here. The Phase 5C Rust implementations must match byte-for-byte,
including the rename/copy ``"<old>\\t<new>"`` encoding, the detached-HEAD
sentinel handling, and the workspace-name remote-vs-root priority. The
Phase 5D backend-dispatch tests at the bottom cover the Rust dispatch
wiring with a fake ``sase_core_rs`` module and (when the real extension
is installed) verify parity against the Python facade.
"""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path
from typing import Any

import pytest

from sase.core.backend import (
    BACKEND_ENV_VAR,
    DUAL_RUN_ENV_VAR,
    RUST_EXTENSION_MODULE_NAME,
    RustBackendUnavailableError,
)
from sase.core.dual_run import DUAL_RUN_LOG_OVERRIDE_ENV_VAR
from sase.core.git_query_facade import (
    derive_git_workspace_name,
    derive_git_workspace_name_python,
    parse_git_branch_name,
    parse_git_branch_name_python,
    parse_git_conflicted_files,
    parse_git_conflicted_files_python,
    parse_git_local_changes,
    parse_git_local_changes_python,
    parse_git_name_status_z,
    parse_git_name_status_z_python,
)
from sase.core.git_query_wire import (
    GIT_QUERY_WIRE_SCHEMA_VERSION,
    GitNameStatusEntryWire,
    git_name_status_entry_from_dict,
    git_query_wire_to_json_dict,
)

# ---------------------------------------------------------------------------
# parse_git_name_status_z
# ---------------------------------------------------------------------------


def test_parse_name_status_empty_stream_returns_empty_list() -> None:
    assert parse_git_name_status_z("") == []


def test_parse_name_status_trailing_nul_is_ignored() -> None:
    # Real ``git diff -z`` output terminates every field with a NUL,
    # leaving an empty trailing token after split.
    stream = "M\0src/a.py\0"
    assert parse_git_name_status_z(stream) == [("M", "src/a.py")]


def test_parse_name_status_simple_status_letters() -> None:
    stream = "A\0added.py\0M\0modified.py\0D\0deleted.py\0T\0type_changed.py\0U\0conflicted.py\0"
    assert parse_git_name_status_z(stream) == [
        ("A", "added.py"),
        ("M", "modified.py"),
        ("D", "deleted.py"),
        ("T", "type_changed.py"),
        ("U", "conflicted.py"),
    ]


def test_parse_name_status_rename_with_score_carries_paired_paths() -> None:
    stream = "R100\0old_name.py\0new_name.py\0"
    assert parse_git_name_status_z(stream) == [("R100", "old_name.py\tnew_name.py")]


def test_parse_name_status_copy_with_score_carries_paired_paths() -> None:
    stream = "C75\0src/orig.py\0src/copy.py\0"
    assert parse_git_name_status_z(stream) == [("C75", "src/orig.py\tsrc/copy.py")]


def test_parse_name_status_mixed_simple_and_rename_in_one_stream() -> None:
    stream = "M\0a.py\0R100\0b_old.py\0b_new.py\0D\0c.py\0"
    assert parse_git_name_status_z(stream) == [
        ("M", "a.py"),
        ("R100", "b_old.py\tb_new.py"),
        ("D", "c.py"),
    ]


def test_parse_name_status_truncated_status_only_drops_entry() -> None:
    """A trailing status with no following path is silently dropped."""
    # Status ``M`` with no path field — the current Python parser
    # tolerates this and skips the entry.
    stream = "M\0a.py\0M"
    assert parse_git_name_status_z(stream) == [("M", "a.py")]


def test_parse_name_status_truncated_rename_falls_back_to_single_path() -> None:
    """A trailing rename with only one path field degrades to a single-path entry.

    The current Python parser checks for two paths (``i + 1 < len(parts)``)
    and, when that fails, falls through to the single-path branch
    (``i < len(parts)``) so the rename is recorded with just the
    available path. Rust must preserve this behavior — flagged in
    Phase 5A as forgiving rather than buggy.
    """
    stream = "M\0a.py\0R100\0only_one_path.py"
    assert parse_git_name_status_z(stream) == [
        ("M", "a.py"),
        ("R100", "only_one_path.py"),
    ]


def test_parse_name_status_skips_empty_status_tokens() -> None:
    """Stray empty fields between entries are skipped."""
    stream = "\0M\0a.py\0"
    assert parse_git_name_status_z(stream) == [("M", "a.py")]


# ---------------------------------------------------------------------------
# parse_git_branch_name
# ---------------------------------------------------------------------------


def test_parse_branch_name_simple_value() -> None:
    assert parse_git_branch_name("feature-x\n") == "feature-x"


def test_parse_branch_name_detached_head_returns_none() -> None:
    assert parse_git_branch_name("HEAD\n") is None


def test_parse_branch_name_empty_stdout_returns_none() -> None:
    assert parse_git_branch_name("") is None


def test_parse_branch_name_whitespace_only_returns_none() -> None:
    assert parse_git_branch_name("   \n") is None


def test_parse_branch_name_strips_surrounding_whitespace() -> None:
    assert parse_git_branch_name("  feature-x  \n") == "feature-x"


# ---------------------------------------------------------------------------
# derive_git_workspace_name
# ---------------------------------------------------------------------------


def test_derive_workspace_name_https_remote_with_dot_git_suffix() -> None:
    assert (
        derive_git_workspace_name("https://github.com/sase-org/sase_100.git", None)
        == "sase_100"
    )


def test_derive_workspace_name_https_remote_without_dot_git_suffix() -> None:
    assert (
        derive_git_workspace_name("https://github.com/sase-org/sase_100", None)
        == "sase_100"
    )


def test_derive_workspace_name_ssh_remote_with_dot_git_suffix() -> None:
    assert (
        derive_git_workspace_name("git@github.com:sase-org/sase_100.git", None)
        == "sase_100"
    )


def test_derive_workspace_name_path_like_remote() -> None:
    assert derive_git_workspace_name("/srv/git/sase_100.git", None) == "sase_100"


def test_derive_workspace_name_falls_back_to_root_path_when_remote_blank() -> None:
    assert derive_git_workspace_name("", "/home/user/projects/sase_100") == "sase_100"


def test_derive_workspace_name_falls_back_to_root_path_when_remote_none() -> None:
    assert derive_git_workspace_name(None, "/home/user/projects/sase_100") == "sase_100"


def test_derive_workspace_name_remote_takes_priority_over_root() -> None:
    assert (
        derive_git_workspace_name(
            "https://github.com/sase-org/repo_a.git", "/tmp/repo_b"
        )
        == "repo_a"
    )


def test_derive_workspace_name_returns_none_when_both_inputs_empty() -> None:
    assert derive_git_workspace_name(None, None) is None
    assert derive_git_workspace_name("", "") is None


def test_derive_workspace_name_remote_dot_git_only_returns_none() -> None:
    """A remote URL of just ``.git`` strips to empty; fall through to root."""
    assert derive_git_workspace_name(".git", "/tmp/fallback") is None


# ---------------------------------------------------------------------------
# parse_git_conflicted_files
# ---------------------------------------------------------------------------


def test_parse_conflicted_files_empty_stdout_returns_empty_list() -> None:
    assert parse_git_conflicted_files("") == []


def test_parse_conflicted_files_strips_blank_lines() -> None:
    stdout = "src/a.py\n\nsrc/b.py\n\n"
    assert parse_git_conflicted_files(stdout) == ["src/a.py", "src/b.py"]


def test_parse_conflicted_files_preserves_path_order() -> None:
    stdout = "z.py\na.py\nm.py\n"
    assert parse_git_conflicted_files(stdout) == ["z.py", "a.py", "m.py"]


def test_parse_conflicted_files_only_blank_lines_returns_empty() -> None:
    assert parse_git_conflicted_files("\n\n   \n") == []


# ---------------------------------------------------------------------------
# parse_git_local_changes
# ---------------------------------------------------------------------------


def test_parse_local_changes_clean_tree_returns_none() -> None:
    assert parse_git_local_changes("") is None


def test_parse_local_changes_whitespace_only_returns_none() -> None:
    assert parse_git_local_changes("   \n") is None


def test_parse_local_changes_dirty_tree_returns_stripped_text() -> None:
    """Whitespace at both ends is stripped; interior content is preserved verbatim."""
    stdout = "M src/a.py\n?? new.py\n"
    assert parse_git_local_changes(stdout) == "M src/a.py\n?? new.py"


# ---------------------------------------------------------------------------
# Wire helpers
# ---------------------------------------------------------------------------


def test_git_query_wire_schema_version_is_one() -> None:
    assert GIT_QUERY_WIRE_SCHEMA_VERSION == 1


def test_git_query_wire_to_json_dict_round_trip_for_entry() -> None:
    entry = GitNameStatusEntryWire(status="R100", path="old.py\tnew.py")
    payload = git_query_wire_to_json_dict(entry)
    assert payload == {"status": "R100", "path": "old.py\tnew.py"}
    assert git_name_status_entry_from_dict(payload) == entry


def test_git_query_wire_to_json_dict_handles_lists() -> None:
    entries = [
        GitNameStatusEntryWire(status="A", path="a.py"),
        GitNameStatusEntryWire(status="M", path="b.py"),
    ]
    payload = git_query_wire_to_json_dict(entries)
    assert payload == [
        {"status": "A", "path": "a.py"},
        {"status": "M", "path": "b.py"},
    ]


# ---------------------------------------------------------------------------
# Phase 5D — Backend dispatch wiring
# ---------------------------------------------------------------------------

# Fixed inputs used by every dispatch test below. Kept tiny so each test
# is dominated by the dispatch path, not the parser.
_NAME_STATUS_INPUT = "M\0a.py\0R100\0old.py\0new.py\0"
_NAME_STATUS_EXPECTED = [("M", "a.py"), ("R100", "old.py\tnew.py")]
_BRANCH_INPUT = "feature/x\n"
_BRANCH_EXPECTED = "feature/x"
_WORKSPACE_REMOTE = "https://github.com/sase-org/sase_100.git"
_WORKSPACE_EXPECTED = "sase_100"
_CONFLICTED_INPUT = "src/a.py\n\nsrc/b.py\n"
_CONFLICTED_EXPECTED = ["src/a.py", "src/b.py"]
_LOCAL_CHANGES_INPUT = "M src/a.py\n"
_LOCAL_CHANGES_EXPECTED = "M src/a.py"


def _force_no_rust_extension(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make ``load_rust_extension`` and ``is_rust_available`` see no module."""
    monkeypatch.delitem(sys.modules, RUST_EXTENSION_MODULE_NAME, raising=False)

    def fail(name: str) -> object:
        if name == RUST_EXTENSION_MODULE_NAME:
            raise ImportError(f"No module named {name!r}")
        return _real_import(name)

    import importlib

    _real_import = importlib.import_module
    monkeypatch.setattr(importlib, "import_module", fail)


def _install_fake_git_module(
    monkeypatch: pytest.MonkeyPatch, **bindings: Any
) -> types.ModuleType:
    """Install a fake ``sase_core_rs`` exposing the given Git bindings."""
    fake = types.ModuleType(RUST_EXTENSION_MODULE_NAME)
    for name, fn in bindings.items():
        setattr(fake, name, fn)
    monkeypatch.setitem(sys.modules, RUST_EXTENSION_MODULE_NAME, fake)
    return fake


# --- explicit Python backend -------------------------------------------------


def test_dispatch_python_backend_uses_python_for_all_helpers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With no Rust extension and ``SASE_CORE_BACKEND=python``, every helper stays Python."""
    monkeypatch.setenv(BACKEND_ENV_VAR, "python")
    _force_no_rust_extension(monkeypatch)

    assert parse_git_name_status_z(_NAME_STATUS_INPUT) == _NAME_STATUS_EXPECTED
    assert parse_git_branch_name(_BRANCH_INPUT) == _BRANCH_EXPECTED
    assert derive_git_workspace_name(_WORKSPACE_REMOTE, None) == _WORKSPACE_EXPECTED
    assert parse_git_conflicted_files(_CONFLICTED_INPUT) == _CONFLICTED_EXPECTED
    assert parse_git_local_changes(_LOCAL_CHANGES_INPUT) == _LOCAL_CHANGES_EXPECTED


def test_dispatch_python_backend_ignores_fake_rust_module(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A registered Rust binding is never called under explicit Python mode."""
    monkeypatch.setenv(BACKEND_ENV_VAR, "python")
    rust_calls: list[str] = []

    def boom(*_args: Any, **_kwargs: Any) -> Any:
        rust_calls.append("called")
        raise AssertionError("rust impl must not run under explicit python mode")

    _install_fake_git_module(
        monkeypatch,
        parse_git_name_status_z=boom,
        parse_git_branch_name=boom,
        derive_git_workspace_name=boom,
        parse_git_conflicted_files=boom,
        parse_git_local_changes=boom,
    )

    assert parse_git_name_status_z(_NAME_STATUS_INPUT) == _NAME_STATUS_EXPECTED
    assert parse_git_branch_name(_BRANCH_INPUT) == _BRANCH_EXPECTED
    assert derive_git_workspace_name(_WORKSPACE_REMOTE, None) == _WORKSPACE_EXPECTED
    assert parse_git_conflicted_files(_CONFLICTED_INPUT) == _CONFLICTED_EXPECTED
    assert parse_git_local_changes(_LOCAL_CHANGES_INPUT) == _LOCAL_CHANGES_EXPECTED
    assert rust_calls == []


# --- Rust backend with fake module -----------------------------------------


def test_dispatch_rust_backend_calls_rust_impl_for_all_helpers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``SASE_CORE_BACKEND=rust`` routes every helper through the fake binding."""
    calls: dict[str, int] = {}

    def fake_name_status(stdout: str) -> list[dict[str, str]]:
        calls["parse_git_name_status_z"] = calls.get("parse_git_name_status_z", 0) + 1
        # Rust binding returns dicts; the facade flattens them to tuples.
        return [{"status": "X", "path": "from-rust.py"}]

    def fake_branch(stdout: str) -> str | None:
        calls["parse_git_branch_name"] = calls.get("parse_git_branch_name", 0) + 1
        return "rust-branch"

    def fake_workspace(remote_url: str | None, root_path: str | None) -> str | None:
        calls["derive_git_workspace_name"] = (
            calls.get("derive_git_workspace_name", 0) + 1
        )
        return "rust-workspace"

    def fake_conflicted(stdout: str) -> list[str]:
        calls["parse_git_conflicted_files"] = (
            calls.get("parse_git_conflicted_files", 0) + 1
        )
        return ["rust-conflict.py"]

    def fake_local_changes(stdout: str) -> str | None:
        calls["parse_git_local_changes"] = calls.get("parse_git_local_changes", 0) + 1
        return "rust-dirty"

    _install_fake_git_module(
        monkeypatch,
        parse_git_name_status_z=fake_name_status,
        parse_git_branch_name=fake_branch,
        derive_git_workspace_name=fake_workspace,
        parse_git_conflicted_files=fake_conflicted,
        parse_git_local_changes=fake_local_changes,
    )
    monkeypatch.setenv(BACKEND_ENV_VAR, "rust")

    assert parse_git_name_status_z(_NAME_STATUS_INPUT) == [("X", "from-rust.py")]
    assert parse_git_branch_name(_BRANCH_INPUT) == "rust-branch"
    assert derive_git_workspace_name(_WORKSPACE_REMOTE, None) == "rust-workspace"
    assert parse_git_conflicted_files(_CONFLICTED_INPUT) == ["rust-conflict.py"]
    assert parse_git_local_changes(_LOCAL_CHANGES_INPUT) == "rust-dirty"

    assert calls == {
        "parse_git_name_status_z": 1,
        "parse_git_branch_name": 1,
        "derive_git_workspace_name": 1,
        "parse_git_conflicted_files": 1,
        "parse_git_local_changes": 1,
    }


# --- Rust backend without binding -------------------------------------------


@pytest.mark.parametrize(
    ("call", "operation"),
    [
        (
            lambda: parse_git_name_status_z(_NAME_STATUS_INPUT),
            "parse_git_name_status_z",
        ),
        (lambda: parse_git_branch_name(_BRANCH_INPUT), "parse_git_branch_name"),
        (
            lambda: derive_git_workspace_name(_WORKSPACE_REMOTE, None),
            "derive_git_workspace_name",
        ),
        (
            lambda: parse_git_conflicted_files(_CONFLICTED_INPUT),
            "parse_git_conflicted_files",
        ),
        (
            lambda: parse_git_local_changes(_LOCAL_CHANGES_INPUT),
            "parse_git_local_changes",
        ),
    ],
)
def test_dispatch_rust_backend_without_binding_raises(
    monkeypatch: pytest.MonkeyPatch, call: Any, operation: str
) -> None:
    """Each helper raises :class:`RustBackendUnavailableError` under Rust mode."""
    _force_no_rust_extension(monkeypatch)
    monkeypatch.setenv(BACKEND_ENV_VAR, "rust")

    with pytest.raises(RustBackendUnavailableError) as excinfo:
        call()
    assert operation in str(excinfo.value)


def test_dispatch_rust_backend_partial_binding_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A Rust extension missing one binding still raises for that helper only."""

    def fake_branch(stdout: str) -> str | None:
        return "rust-only-branch"

    _install_fake_git_module(monkeypatch, parse_git_branch_name=fake_branch)
    monkeypatch.setenv(BACKEND_ENV_VAR, "rust")

    # Helper with the binding routes to Rust.
    assert parse_git_branch_name(_BRANCH_INPUT) == "rust-only-branch"

    # Helpers without bindings still raise.
    with pytest.raises(RustBackendUnavailableError):
        parse_git_name_status_z(_NAME_STATUS_INPUT)
    with pytest.raises(RustBackendUnavailableError):
        parse_git_local_changes(_LOCAL_CHANGES_INPUT)


# --- Dual-run logging --------------------------------------------------------


def test_dispatch_dual_run_logs_match_for_all_helpers(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Dual-run runs both impls, logs one record per call, returns Python output."""
    log_path = tmp_path / "core_dual_run.jsonl"
    monkeypatch.setenv(DUAL_RUN_LOG_OVERRIDE_ENV_VAR, str(log_path))
    monkeypatch.setenv(DUAL_RUN_ENV_VAR, "1")

    # The fake bindings mirror the Python output so every record matches.
    def fake_name_status(stdout: str) -> list[dict[str, str]]:
        wire = parse_git_name_status_z_python(stdout)
        return [{"status": s, "path": p} for (s, p) in wire]

    _install_fake_git_module(
        monkeypatch,
        parse_git_name_status_z=fake_name_status,
        parse_git_branch_name=parse_git_branch_name_python,
        derive_git_workspace_name=derive_git_workspace_name_python,
        parse_git_conflicted_files=parse_git_conflicted_files_python,
        parse_git_local_changes=parse_git_local_changes_python,
    )

    # Caller sees Python output regardless of dual-run.
    assert parse_git_name_status_z(_NAME_STATUS_INPUT) == _NAME_STATUS_EXPECTED
    assert parse_git_branch_name(_BRANCH_INPUT) == _BRANCH_EXPECTED
    assert derive_git_workspace_name(_WORKSPACE_REMOTE, None) == _WORKSPACE_EXPECTED
    assert parse_git_conflicted_files(_CONFLICTED_INPUT) == _CONFLICTED_EXPECTED
    assert parse_git_local_changes(_LOCAL_CHANGES_INPUT) == _LOCAL_CHANGES_EXPECTED

    records = [
        json.loads(line) for line in log_path.read_text().splitlines() if line.strip()
    ]
    assert [r["operation"] for r in records] == [
        "parse_git_name_status_z",
        "parse_git_branch_name",
        "derive_git_workspace_name",
        "parse_git_conflicted_files",
        "parse_git_local_changes",
    ]
    assert all(r["match"] is True for r in records)
    assert all(r["error_class"] is None for r in records)


def test_dispatch_dual_run_records_mismatch_for_name_status(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A diverging Rust impl is captured as ``match=False`` in the JSONL log."""
    log_path = tmp_path / "core_dual_run.jsonl"
    monkeypatch.setenv(DUAL_RUN_LOG_OVERRIDE_ENV_VAR, str(log_path))
    monkeypatch.setenv(DUAL_RUN_ENV_VAR, "1")

    def diverging(stdout: str) -> list[dict[str, str]]:
        return []

    _install_fake_git_module(monkeypatch, parse_git_name_status_z=diverging)

    # Python output is still returned to the caller.
    assert parse_git_name_status_z(_NAME_STATUS_INPUT) == _NAME_STATUS_EXPECTED

    records = [
        json.loads(line) for line in log_path.read_text().splitlines() if line.strip()
    ]
    assert len(records) == 1
    assert records[0]["operation"] == "parse_git_name_status_z"
    assert records[0]["match"] is False


# --- Real-extension parity --------------------------------------------------


def test_rust_extension_parity_for_all_helpers() -> None:
    """When ``sase_core_rs`` is installed, its output matches the Python facade."""
    rust_module = pytest.importorskip("sase_core_rs")
    for binding in (
        "parse_git_name_status_z",
        "parse_git_branch_name",
        "derive_git_workspace_name",
        "parse_git_conflicted_files",
        "parse_git_local_changes",
    ):
        if not hasattr(rust_module, binding):
            pytest.skip(f"sase_core_rs is too old (no {binding}).")

    name_status_inputs = [
        "",
        "M\0a.py\0",
        "A\0added.py\0M\0modified.py\0D\0deleted.py\0T\0t.py\0U\0u.py\0",
        "R100\0old.py\0new.py\0",
        "C75\0src/orig.py\0src/copy.py\0",
        "M\0a.py\0R100\0only_one_path.py",
        "\0M\0a.py\0",
    ]
    for stdout in name_status_inputs:
        rust_dicts = rust_module.parse_git_name_status_z(stdout)
        rust_flat = [
            (entry.status, entry.path)
            for entry in (git_name_status_entry_from_dict(d) for d in rust_dicts)
        ]
        assert rust_flat == parse_git_name_status_z_python(stdout)

    for stdout in ["feature-x\n", "HEAD\n", "", "   \n", "  feat/x  \n"]:
        assert rust_module.parse_git_branch_name(
            stdout
        ) == parse_git_branch_name_python(stdout)

    workspace_pairs: list[tuple[str | None, str | None]] = [
        ("https://github.com/sase-org/sase_100.git", None),
        ("git@github.com:sase-org/sase_100.git", None),
        ("/srv/git/sase_100.git", None),
        ("", "/home/user/sase_100"),
        (None, "/home/user/sase_100"),
        (".git", "/tmp/fallback"),
        (None, None),
    ]
    for remote, root in workspace_pairs:
        assert rust_module.derive_git_workspace_name(
            remote, root
        ) == derive_git_workspace_name_python(remote, root)

    for stdout in ["", "src/a.py\n\nsrc/b.py\n", "z.py\na.py\nm.py\n", "\n\n   \n"]:
        assert rust_module.parse_git_conflicted_files(
            stdout
        ) == parse_git_conflicted_files_python(stdout)

    for stdout in ["", "   \n", "M src/a.py\n?? new.py\n"]:
        assert rust_module.parse_git_local_changes(
            stdout
        ) == parse_git_local_changes_python(stdout)
