"""One store read per CLI command: per-command replay budgets.

Routing (``bead_route_targets``) and target probing
(``bead_probe_target_owner``) never load the store and are excluded from the
counts below. Every other ``bead_*`` binding either replays the event store
or takes the mutation lock's single load, so each counted call is one store
read.
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path
from typing import Any

import pytest

from sase.bead.model import BeadTier, IssueType
from sase.bead.project import BeadProject
from tests.test_bead.resolution_test_helpers import isolate_bead_store_resolution

# Bindings that never load the store: pure routing over passed-in data, or
# filesystem-only ownership stats.
_NON_READING_BINDINGS = frozenset({"bead_route_targets", "bead_probe_target_owner"})


@pytest.fixture
def read_counted_store(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, str]:
    """Seed a small store and return its bead IDs by role."""
    with BeadProject.init(tmp_path):
        pass
    isolate_bead_store_resolution(monkeypatch, tmp_path)
    with BeadProject(tmp_path) as proj:
        first = proj.create("First", IssueType.TASK, task_type="bug", size="small")
        second = proj.create("Second", IssueType.TASK, task_type="bug", size="small")
        plan = proj.create("Owner epic", IssueType.PLAN, tier=BeadTier.EPIC)
        proj.append_note(first.id, "seed note")
        proj.add_dependency(second.id, first.id)
    return {"first": first.id, "second": second.id, "plan": plan.id}


def _counted_bead_bindings() -> tuple[Counter[str], dict[str, Any]]:
    """Wrap every store-reading ``bead_*`` binding with a counter.

    The wrap happens on the extension module itself so every import style
    (module-top or call-time binding lookup) is observed.
    """
    from sase.core import rust as rust_module

    extension = rust_module.require_rust_extension()
    counts: Counter[str] = Counter()
    originals: dict[str, Any] = {}
    for name in dir(extension):
        if name.startswith("bead_") and name not in _NON_READING_BINDINGS:
            original = getattr(extension, name)
            originals[name] = original

            def make_counted(binding_name: str, original_binding: Any) -> Any:
                def counted(*args: Any, **kwargs: Any) -> Any:
                    counts[binding_name] += 1
                    return original_binding(*args, **kwargs)

                return counted

            setattr(extension, name, make_counted(name, original))
    return counts, originals


def _restore_bead_bindings(originals: dict[str, Any]) -> None:
    from sase.core import rust as rust_module

    extension = rust_module.require_rust_extension()
    for name, original in originals.items():
        setattr(extension, name, original)


def _run_command(argv: list[str], capsys: pytest.CaptureFixture[str]) -> int:
    """Run one bead command through production dispatch, returning its exit."""
    from sase.main import entry

    monkeypatch_argv = ["sase", "bead", *argv]
    old_argv = sys.argv
    sys.argv = monkeypatch_argv
    try:
        try:
            entry.main()
        except SystemExit as exc:
            return int(exc.code or 0)
        return 0
    finally:
        sys.argv = old_argv
        capsys.readouterr()


def _assert_read_count(
    argv: list[str],
    expected: int,
    capsys: pytest.CaptureFixture[str],
) -> None:
    counts, originals = _counted_bead_bindings()
    try:
        assert _run_command(argv, capsys) == 0
    finally:
        _restore_bead_bindings(originals)
    total = sum(counts.values())
    assert total == expected, f"{argv}: expected {expected} reads, got {dict(counts)}"


def test_update_reads_store_once(
    read_counted_store: dict[str, str],
    capsys: pytest.CaptureFixture[str],
) -> None:
    _assert_read_count(
        ["update", read_counted_store["first"], "--status", "ready"], 1, capsys
    )


def test_update_with_note_reads_store_three_times(
    read_counted_store: dict[str, str],
    capsys: pytest.CaptureFixture[str],
) -> None:
    _assert_read_count(
        ["update", read_counted_store["first"], "--status", "ready", "--note", "n1"],
        3,
        capsys,
    )


def test_close_reads_store_twice(
    read_counted_store: dict[str, str],
    capsys: pytest.CaptureFixture[str],
) -> None:
    _assert_read_count(["close", read_counted_store["second"]], 2, capsys)


def test_close_with_note_reads_store_twice(
    read_counted_store: dict[str, str],
    capsys: pytest.CaptureFixture[str],
) -> None:
    _assert_read_count(
        ["close", read_counted_store["second"], "--note", "bye"], 2, capsys
    )


def test_note_reads_store_twice(
    read_counted_store: dict[str, str],
    capsys: pytest.CaptureFixture[str],
) -> None:
    _assert_read_count(["note", read_counted_store["first"], "hello"], 2, capsys)


def test_note_remove_reads_store_twice(
    read_counted_store: dict[str, str],
    capsys: pytest.CaptureFixture[str],
) -> None:
    _assert_read_count(
        ["note", read_counted_store["first"], "--remove", "1"], 2, capsys
    )


def test_create_with_parent_reads_store_once(
    read_counted_store: dict[str, str],
    capsys: pytest.CaptureFixture[str],
) -> None:
    _assert_read_count(
        [
            "create",
            "--title",
            "Kid",
            "--type",
            f"phase({read_counted_store['plan']})",
            "--size",
            "small",
            "--reason",
            "read-count probe",
        ],
        1,
        capsys,
    )


def test_open_reads_store_once(
    read_counted_store: dict[str, str],
    capsys: pytest.CaptureFixture[str],
) -> None:
    _assert_read_count(["open", read_counted_store["first"]], 1, capsys)


def test_dep_add_reads_store_once(
    read_counted_store: dict[str, str],
    capsys: pytest.CaptureFixture[str],
) -> None:
    _assert_read_count(
        ["dep", "add", read_counted_store["second"], read_counted_store["plan"]],
        1,
        capsys,
    )


def test_dep_rm_reads_store_once(
    read_counted_store: dict[str, str],
    capsys: pytest.CaptureFixture[str],
) -> None:
    _assert_read_count(
        ["dep", "rm", read_counted_store["second"], read_counted_store["first"]],
        1,
        capsys,
    )


def test_rm_reads_store_once(
    read_counted_store: dict[str, str],
    capsys: pytest.CaptureFixture[str],
) -> None:
    _assert_read_count(["rm", read_counted_store["second"]], 1, capsys)


def test_ref_add_reads_store_once(
    read_counted_store: dict[str, str],
    capsys: pytest.CaptureFixture[str],
) -> None:
    _assert_read_count(
        ["ref", "add", read_counted_store["first"], "doc:readme"], 1, capsys
    )


def test_ref_rm_reads_store_once(
    read_counted_store: dict[str, str],
    capsys: pytest.CaptureFixture[str],
) -> None:
    ids = read_counted_store
    _run_command(["ref", "add", ids["first"], "doc:readme"], capsys)
    _assert_read_count(["ref", "rm", ids["first"], "doc:readme"], 1, capsys)
