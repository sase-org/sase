"""Tests for bead CLI fast-path routing and safety guards."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

from sase.main import bead_fast_path
from sase.main.bead_fast_path import try_handle_bead_fast_path


def test_fast_path_routes_search_through_rust_executor(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    read_dir = tmp_path / "sdd/beads"
    read_dir.mkdir(parents=True)
    context = bead_fast_path._FastPathContext(
        read_beads_dirs=[read_dir],
        write_beads_dir=read_dir,
        relativize_design_paths=True,
    )
    calls: list[dict[str, Any]] = []

    def fake_binding(
        argv: list[str],
        read_beads_dirs: list[str],
        write_beads_dir: str,
        cwd: str,
        relativize_design_paths: bool,
    ) -> dict[str, object]:
        calls.append(
            {
                "argv": argv,
                "read_beads_dirs": read_beads_dirs,
                "write_beads_dir": write_beads_dir,
                "cwd": cwd,
                "relativize_design_paths": relativize_design_paths,
            }
        )
        return {"handled": True, "stdout": "rust search\n", "exit_code": 0}

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        bead_fast_path,
        "_resolve_fast_path_context",
        lambda argv: context,
    )
    monkeypatch.setattr(
        "sase.core.rust.require_rust_binding",
        lambda name: fake_binding,
    )

    assert try_handle_bead_fast_path(["search", "needle"]) == 0

    assert capsys.readouterr().out == "rust search\n"
    assert calls == [
        {
            "argv": ["search", "needle"],
            "read_beads_dirs": [str(read_dir)],
            "write_beads_dir": str(read_dir),
            "cwd": str(tmp_path),
            "relativize_design_paths": True,
        }
    ]


def test_fast_path_guards_mutations_but_not_reads(tmp_path: Path, monkeypatch) -> None:
    read_dir = tmp_path / "production" / "beads"
    context = bead_fast_path._FastPathContext(
        read_beads_dirs=[read_dir],
        write_beads_dir=read_dir,
        relativize_design_paths=False,
    )
    calls: list[list[str]] = []

    def fake_binding(
        argv: list[str],
        _read_beads_dirs: list[str],
        _write_beads_dir: str,
        _cwd: str,
        _relativize_design_paths: bool,
    ) -> dict[str, object]:
        calls.append(argv)
        return {"handled": True, "exit_code": 0}

    monkeypatch.setattr(
        bead_fast_path,
        "_resolve_fast_path_context",
        lambda _argv: context,
    )
    monkeypatch.setattr(
        "sase.core.rust.require_rust_binding",
        lambda _name: fake_binding,
    )
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "fast-path write guard")
    monkeypatch.setenv("SASE_PYTEST_SANDBOX_DIR", str(tmp_path / "sandbox"))

    assert try_handle_bead_fast_path(["search", "needle"]) == 0
    with pytest.raises(RuntimeError, match="fast-path rm"):
        try_handle_bead_fast_path(["rm", "beads-1"])

    assert calls == [["search", "needle"]]


def test_fast_path_dep_write_guard_is_closed_except_for_read_verbs(
    tmp_path: Path, monkeypatch
) -> None:
    read_dir = tmp_path / "production" / "beads"
    context = bead_fast_path._FastPathContext(
        read_beads_dirs=[read_dir],
        write_beads_dir=read_dir,
        relativize_design_paths=False,
    )

    monkeypatch.setattr(
        bead_fast_path,
        "_resolve_fast_path_context",
        lambda _argv: context,
    )
    monkeypatch.setattr(
        "sase.core.rust.require_rust_binding",
        lambda _name: lambda *_args: {"handled": True, "exit_code": 0},
    )
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "dep fast-path write guard")
    monkeypatch.setenv("SASE_PYTEST_SANDBOX_DIR", str(tmp_path / "sandbox"))

    assert try_handle_bead_fast_path(["dep", "list"]) == 0
    assert try_handle_bead_fast_path(["dep", "tree"]) == 0
    for argv in (
        ["dep"],
        ["dep", "add", "source", "target"],
        ["dep", "rm", "source", "target"],
        ["dep", "future-write"],
    ):
        with pytest.raises(RuntimeError, match="fast-path dep"):
            try_handle_bead_fast_path(argv)


def test_fast_path_ref_write_guard_is_closed_except_for_list(
    tmp_path: Path, monkeypatch
) -> None:
    read_dir = tmp_path / "production" / "beads"
    context = bead_fast_path._FastPathContext(
        read_beads_dirs=[read_dir],
        write_beads_dir=read_dir,
        relativize_design_paths=False,
    )

    monkeypatch.setattr(
        bead_fast_path,
        "_resolve_fast_path_context",
        lambda _argv: context,
    )
    monkeypatch.setattr(
        "sase.core.rust.require_rust_binding",
        lambda _name: lambda *_args: {"handled": True, "exit_code": 0},
    )
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "ref fast-path write guard")
    monkeypatch.setenv("SASE_PYTEST_SANDBOX_DIR", str(tmp_path / "sandbox"))

    assert try_handle_bead_fast_path(["ref", "list"]) == 0
    for argv in (
        ["ref"],
        ["ref", "add", "beads-1", "plans:one.md"],
        ["ref", "rm", "beads-1", "plans:one.md"],
        ["ref", "future-write"],
    ):
        with pytest.raises(RuntimeError, match="fast-path ref"):
            try_handle_bead_fast_path(argv)


def test_fast_path_refuses_unsafe_resolved_location_before_rust(
    tmp_path: Path, monkeypatch
) -> None:
    from sase.bead.cli_common import _BeadsLocation

    unsafe_root = tmp_path / "production"
    unsafe_beads_dir = unsafe_root / "sdd/beads"
    unsafe_beads_dir.mkdir(parents=True)
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()

    def fake_resolve_beads_location(*_args, **_kwargs):
        return _BeadsLocation(root=unsafe_root, beads_dirname="sdd/beads")

    def fail_binding(_name: str):
        raise AssertionError("unsafe bead write reached Rust binding")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "sase.bead.cli_common.resolve_beads_location",
        fake_resolve_beads_location,
    )
    monkeypatch.setattr("sase.bead.sync.bead_refresh_mode", lambda: "background")
    monkeypatch.setattr("sase.core.rust.require_rust_binding", fail_binding)
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "fast-path unsafe resolver")
    monkeypatch.setenv("SASE_PYTEST_SANDBOX_DIR", str(sandbox))

    with pytest.raises(RuntimeError) as exc_info:
        try_handle_bead_fast_path(["rm", "beads-1"])

    message = str(exc_info.value)
    assert "fast-path rm" in message
    assert str(unsafe_beads_dir.resolve()) in message
    assert str(sandbox.resolve()) in message


def test_fast_path_refuses_mutation_from_plain_checkout_sidecar_record(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from sase.sdd.store import write_sdd_store_record

    checkout = tmp_path / "checkout"
    beads_dir = checkout / "sase" / "repos" / "plans" / "beads"
    beads_dir.mkdir(parents=True)
    write_sdd_store_record(
        checkout,
        {
            "schema_version": 2,
            "storage": "sidecar_repos",
            "provider": "github",
            "sidecars": {
                "plans": {
                    "repo": "acme/project--plans",
                    "remote_url": "git@example.com:acme/project--plans.git",
                },
                "research": {
                    "repo": "acme/project--research",
                    "remote_url": "git@example.com:acme/project--research.git",
                },
            },
        },
    )
    monkeypatch.chdir(checkout)
    monkeypatch.setattr(
        "sase.bead.cli_location._resolve_workspace_context",
        lambda _cwd: None,
    )
    monkeypatch.setattr("sase.bead.sync.bead_refresh_mode", lambda: "background")

    def fail_binding(_name: str):
        raise AssertionError("read-only bead mutation reached Rust binding")

    monkeypatch.setattr("sase.core.rust.require_rust_binding", fail_binding)

    with pytest.raises(RuntimeError, match="available for reads only"):
        try_handle_bead_fast_path(["rm", "beads-1"])


def test_fast_path_defers_list_to_argparse(monkeypatch) -> None:
    """``list`` must stay on the argparse path.

    Python's ``_render_list_compact`` (see ``cli_query.py``) is the only
    implementation carrying the type-column compact row grammar; the Rust
    core's ``handle_list`` still emits the old grammar. Routing ``list``
    through the fast path would silently regress the feature this test
    guards against.
    """

    def fail_context(argv: list[str]):
        raise AssertionError(f"context should not resolve for list: {argv}")

    monkeypatch.setattr(bead_fast_path, "_resolve_fast_path_context", fail_context)

    assert try_handle_bead_fast_path(["list"]) is None
    assert try_handle_bead_fast_path(["list", "--status", "closed"]) is None
    assert try_handle_bead_fast_path(["list", "--format", "json"]) is None


def test_fast_path_defers_show_to_argparse(monkeypatch) -> None:
    def fail_context(argv: list[str]):
        raise AssertionError(f"context should not resolve for show: {argv}")

    monkeypatch.setattr(bead_fast_path, "_resolve_fast_path_context", fail_context)

    assert try_handle_bead_fast_path(["show", "beads-1.1"]) is None
    assert try_handle_bead_fast_path(["show", "beads-1", "--format", "json"]) is None


def test_fast_path_defers_create_to_argparse(monkeypatch) -> None:
    def fail_context(argv: list[str]):
        raise AssertionError(f"context should not resolve for create: {argv}")

    monkeypatch.setattr(bead_fast_path, "_resolve_fast_path_context", fail_context)

    assert (
        try_handle_bead_fast_path(["create", "--title", "Probe", "--type", "task"])
        is None
    )


def test_bead_create_dispatch_records_acting_agent_as_created_by(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression test for the Rust fast path swallowing ``create`` attribution.

    Drives the real ``sase.main.entry.main`` dispatch instead of calling
    ``handle_bead_create`` directly, since that direct-call test shape is what
    let the fast path bypass attribution ship undetected.
    """
    from sase.bead.model import IssueType
    from sase.bead.project import BeadProject
    from sase.core.agent_identity_facade import globalize_owned_agent_name
    from sase.main import entry
    from tests.test_bead.resolution_test_helpers import isolate_bead_store_resolution

    with BeadProject.init(tmp_path):
        pass
    isolate_bead_store_resolution(monkeypatch, tmp_path)
    monkeypatch.setenv("SASE_AGENT_NAME", "q8--code")
    monkeypatch.setattr(
        sys,
        "argv",
        ["sase", "bead", "create", "--title", "Probe", "--type", "task"],
    )

    with pytest.raises(SystemExit) as exc_info:
        entry.main()

    assert exc_info.value.code == 0
    with BeadProject(tmp_path) as project:
        task = project.list_issues(issue_types=[IssueType.TASK])[0]
    assert task.created_by == globalize_owned_agent_name("q8--code")


def test_fast_path_dep_reads_skip_write_guard_but_add_remains_guarded(
    tmp_path: Path, monkeypatch
) -> None:
    context = bead_fast_path._FastPathContext(
        read_beads_dirs=[tmp_path / "beads"],
        write_beads_dir=tmp_path / "beads",
        relativize_design_paths=False,
    )
    guarded: list[str] = []
    monkeypatch.setattr(
        bead_fast_path,
        "_resolve_fast_path_context",
        lambda _argv: context,
    )
    monkeypatch.setattr(
        "sase.core.state_write_guard.assert_bead_store_write_sandboxed",
        lambda _path, *, operation, read_only: guarded.append(operation),
    )
    monkeypatch.setattr(
        "sase.core.rust.require_rust_binding",
        lambda _name: lambda *_args: {"handled": False},
    )

    assert try_handle_bead_fast_path(["dep", "list"]) is None
    assert try_handle_bead_fast_path(["dep", "tree"]) is None
    assert guarded == []

    assert try_handle_bead_fast_path(["dep", "add", "a", "b"]) is None
    assert try_handle_bead_fast_path(["dep"]) is None
    assert try_handle_bead_fast_path(["dep", "future-write"]) is None
    assert guarded == ["fast-path dep", "fast-path dep", "fast-path dep"]


def test_fast_path_defers_full_search_to_argparse(monkeypatch) -> None:
    def fail_context(argv: list[str]):
        raise AssertionError(f"context should not resolve for full search: {argv}")

    monkeypatch.setattr(bead_fast_path, "_resolve_fast_path_context", fail_context)

    assert try_handle_bead_fast_path(["search", "needle", "--format", "full"]) is None
    assert try_handle_bead_fast_path(["search", "needle", "--format=full"]) is None
    assert try_handle_bead_fast_path(["search", "needle", "-f", "full"]) is None
    assert try_handle_bead_fast_path(["search", "needle", "-ffull"]) is None


def test_fast_path_defers_search_help_to_argparse(monkeypatch) -> None:
    def fail_context(argv: list[str]):
        raise AssertionError(f"context should not resolve for help: {argv}")

    monkeypatch.setattr(bead_fast_path, "_resolve_fast_path_context", fail_context)

    assert try_handle_bead_fast_path(["search", "--help"]) is None


@pytest.mark.parametrize(
    "argv",
    [
        ["close", "beads-1", "-p", "1"],
        ["close", "beads-1", "--phases=1-2"],
    ],
)
def test_rust_fast_path_defers_close_phase_selectors(
    argv: list[str],
    tmp_path: Path,
) -> None:
    from sase.core.rust import require_rust_binding

    beads_dir = tmp_path / "beads"
    beads_dir.mkdir()
    outcome = dict(
        require_rust_binding("bead_cli_execute")(
            argv,
            [str(beads_dir)],
            str(beads_dir),
            str(tmp_path),
            False,
        )
    )

    assert outcome["handled"] is False
