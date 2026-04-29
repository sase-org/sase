"""Golden tests pinning the Git query parser facade contract.

The Phase 5B contract guarantees that
:mod:`sase.core.git_query_facade` produces the exact strings exercised
here. The Phase 5C Rust implementations must match byte-for-byte,
including the rename/copy ``"<old>\\t<new>"`` encoding, the detached-HEAD
sentinel handling, and the workspace-name remote-vs-root priority.

Phase 8E direct-wires every helper to ``sase_core_rs``: the dispatch /
dual-run / env-var tests are gone. The remaining tests assert the
content contract (via the real Rust binding when installed) and the
direct-call wiring (a missing wheel raises :class:`ImportError`; a
stale wheel without the binding raises :class:`AttributeError`; a
registered fake binding is called for every helper). The Python golden
helpers in :mod:`sase.core.git_query_facade` are retained as host-logic
references for the parity test at the bottom.
"""

from __future__ import annotations

import importlib
import importlib.util
import sys
import types
from typing import Any

import pytest

from sase.core.backend import RUST_EXTENSION_MODULE_NAME
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


pytestmark = pytest.mark.skipif(
    importlib.util.find_spec(RUST_EXTENSION_MODULE_NAME) is None,
    reason="sase_core_rs is required for direct-Rust git facade tests.",
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
    stream = "M\0a.py\0M"
    assert parse_git_name_status_z(stream) == [("M", "a.py")]


def test_parse_name_status_truncated_rename_falls_back_to_single_path() -> None:
    """A trailing rename with only one path field degrades to a single-path entry.

    The Python golden parser checks for two paths
    (``i + 1 < len(parts)``) and, when that fails, falls through to the
    single-path branch (``i < len(parts)``) so the rename is recorded
    with just the available path. Rust must preserve this behavior —
    flagged in Phase 5A as forgiving rather than buggy.
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
# Phase 8E — direct-Rust call wiring
# ---------------------------------------------------------------------------

# Fixed inputs used by every wiring test below. Kept tiny so each test
# is dominated by the call path, not the parser.
_NAME_STATUS_INPUT = "M\0a.py\0R100\0old.py\0new.py\0"
_BRANCH_INPUT = "feature/x\n"
_WORKSPACE_REMOTE = "https://github.com/sase-org/sase_100.git"
_CONFLICTED_INPUT = "src/a.py\n\nsrc/b.py\n"
_LOCAL_CHANGES_INPUT = "M src/a.py\n"


def _force_no_rust_extension(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make ``load_rust_extension`` see no module."""
    monkeypatch.delitem(sys.modules, RUST_EXTENSION_MODULE_NAME, raising=False)
    real_import_module = importlib.import_module

    def fail(name: str, *args, **kwargs):  # type: ignore[no-untyped-def]
        if name == RUST_EXTENSION_MODULE_NAME:
            raise ImportError(f"No module named {name!r}")
        return real_import_module(name, *args, **kwargs)

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


def test_facade_calls_rust_binding_for_all_helpers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Each facade entry point routes through the registered binding."""
    calls: dict[str, int] = {}

    def fake_name_status(_stdout: str) -> list[dict[str, str]]:
        calls["parse_git_name_status_z"] = calls.get("parse_git_name_status_z", 0) + 1
        return [{"status": "X", "path": "from-rust.py"}]

    def fake_branch(_stdout: str) -> str | None:
        calls["parse_git_branch_name"] = calls.get("parse_git_branch_name", 0) + 1
        return "rust-branch"

    def fake_workspace(_remote_url: str | None, _root_path: str | None) -> str | None:
        calls["derive_git_workspace_name"] = (
            calls.get("derive_git_workspace_name", 0) + 1
        )
        return "rust-workspace"

    def fake_conflicted(_stdout: str) -> list[str]:
        calls["parse_git_conflicted_files"] = (
            calls.get("parse_git_conflicted_files", 0) + 1
        )
        return ["rust-conflict.py"]

    def fake_local_changes(_stdout: str) -> str | None:
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
def test_missing_extension_raises(
    monkeypatch: pytest.MonkeyPatch, call: Any, operation: str
) -> None:
    """Each helper raises :class:`ImportError` when the extension is gone.

    The ``operation`` parameter is unused for this case (the loader does
    not know which binding the caller wanted yet) but is kept to match
    the parametrize structure of :func:`test_partial_binding_raises_only_for_missing_helpers`.
    """
    del operation
    _force_no_rust_extension(monkeypatch)
    with pytest.raises(ImportError, match=RUST_EXTENSION_MODULE_NAME):
        call()


def test_partial_binding_raises_only_for_missing_helpers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A wheel missing one binding still raises for that helper only."""

    def fake_branch(_stdout: str) -> str | None:
        return "rust-only-branch"

    _install_fake_git_module(monkeypatch, parse_git_branch_name=fake_branch)

    # Helper with the binding routes to Rust.
    assert parse_git_branch_name(_BRANCH_INPUT) == "rust-only-branch"

    # Helpers without bindings raise ``AttributeError`` with the missing op name.
    with pytest.raises(AttributeError, match="parse_git_name_status_z"):
        parse_git_name_status_z(_NAME_STATUS_INPUT)
    with pytest.raises(AttributeError, match="parse_git_local_changes"):
        parse_git_local_changes(_LOCAL_CHANGES_INPUT)


# --- Real-extension parity --------------------------------------------------


def test_rust_extension_parity_for_all_helpers() -> None:
    """When ``sase_core_rs`` is installed, its output matches the Python golden helpers."""
    rust_module = pytest.importorskip(RUST_EXTENSION_MODULE_NAME)
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
