"""Withholding, corruption, budgets, and pagination bounds."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.agents_sync.models import ProjectTarget
from sase.agents_sync.publication_state_repair import (
    STATE_REPAIR_MAX_HOODS,
    repair_project_run_states,
)
from tests.agents_sync.git_sync_fixtures import setup_repo, target

from tests.agents_sync.test_publication_state_repair._helpers import (
    OWNER,
    SeedBuilder,
    commit_push,
    inv_run,
    make_loader,
    remote_head,
    remote_state,
    setup_repair,
)


def test_withheld_run_does_not_block_sibling(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    remote, sync_target = setup_repair(
        tmp_path,
        runs=[
            ("foo", "foo.keep", "run-1", "active"),
            ("foo", "foo.victim", "run-2", "active"),
        ],
    )
    import sase.agents_sync._publication_state_repair_payload as repair_payload

    original = repair_payload._state_bytes_publishable

    def scoped_block(
        state_bytes: bytes,
        destination: str,
        scope: object,
        t: ProjectTarget,
        diags: list[str],
        global_name: str,
    ) -> bool:
        if global_name == "alice.athena.foo.victim":
            diags.append(f"{global_name}: state payload blocked; withheld")
            return False
        return original(state_bytes, destination, scope, t, diags, global_name)

    monkeypatch.setattr(repair_payload, "_state_bytes_publishable", scoped_block)
    report = repair_project_run_states(
        sync_target,
        OWNER,
        apply=True,
        inventory_loader=make_loader(
            [
                inv_run("run-1", "foo.keep", "completed"),
                inv_run("run-2", "foo.victim", "completed"),
            ],
            [],
        ),
    )

    assert report.error is None
    assert (report.changed, report.withheld) == (1, 1)
    assert report.pushed
    assert remote_state(remote, "alice.athena.foo.keep") == "completed"
    assert remote_state(remote, "alice.athena.foo.victim") == "active"


def test_corrupt_hood_does_not_block_sibling(tmp_path: Path) -> None:
    remote, _seed, sidecar = setup_repo(tmp_path)
    builder = SeedBuilder(sidecar)
    builder.add_run("foo", "foo.job", "run-1", "active")
    builder.write_manifest(corrupt={"bar": "0" * 64})
    builder.add_corrupt_hood("bar")
    commit_push(sidecar)
    sync_target = target(tmp_path, remote, sidecar)

    report = repair_project_run_states(
        sync_target,
        OWNER,
        apply=True,
        inventory_loader=make_loader([inv_run("run-1", "foo.job", "completed")], []),
    )

    assert report.error is None
    assert report.changed == 1 and report.failed >= 1
    assert any("bar" in diagnostic for diagnostic in report.diagnostics)
    assert remote_state(remote, "alice.athena.foo.job") == "completed"


def test_byte_budget_freezes_cursor(tmp_path: Path) -> None:
    remote, sync_target = setup_repair(
        tmp_path, runs=[("foo", "foo.job", "run-1", "active")]
    )
    before = remote_head(remote)
    report = repair_project_run_states(
        sync_target,
        OWNER,
        apply=True,
        inventory_loader=make_loader([inv_run("run-1", "foo.job", "completed")], []),
        payload_budget_bytes=10,
    )

    assert report.changed == 0
    assert report.next_cursor is None
    assert any("byte limit" in diagnostic for diagnostic in report.diagnostics)
    assert remote_head(remote) == before


def test_second_pass_is_noop(tmp_path: Path) -> None:
    remote, sync_target = setup_repair(
        tmp_path, runs=[("foo", "foo.job", "run-1", "active")]
    )
    loader = make_loader([inv_run("run-1", "foo.job", "completed")], [])
    first = repair_project_run_states(
        sync_target, OWNER, apply=True, inventory_loader=loader
    )
    assert first.changed == 1

    steady = make_loader([inv_run("run-1", "foo.job", "completed")], [])
    second = repair_project_run_states(
        sync_target, OWNER, apply=True, inventory_loader=steady
    )
    assert second.error is None
    assert (second.changed, second.already_current) == (0, 1)
    assert second.committed is False

    preview = repair_project_run_states(
        sync_target, OWNER, apply=False, inventory_loader=steady
    )
    assert (preview.changed, preview.already_current) == (0, 1)


def test_cursor_pagination_and_invalid_cursor(tmp_path: Path) -> None:
    _remote, sync_target = setup_repair(
        tmp_path,
        runs=[
            ("foo", "foo.a", "run-1", "active"),
            ("foo", "foo.b", "run-2", "active"),
            ("foo", "foo.c", "run-3", "active"),
        ],
    )
    loader = make_loader(
        [
            inv_run("run-1", "foo.a", "completed"),
            inv_run("run-2", "foo.b", "completed"),
            inv_run("run-3", "foo.c", "completed"),
        ],
        [],
    )
    first = repair_project_run_states(
        sync_target, OWNER, apply=False, state_limit=2, inventory_loader=loader
    )
    assert first.examined == 2 and first.pass_complete is False
    assert first.next_cursor is not None

    second = repair_project_run_states(
        sync_target,
        OWNER,
        apply=False,
        state_limit=2,
        state_after=first.next_cursor,
        inventory_loader=loader,
    )
    assert second.examined == 1 and second.pass_complete is True

    invalid = repair_project_run_states(
        sync_target, OWNER, apply=False, state_after="bogus", inventory_loader=loader
    )
    assert invalid.error is not None

    too_small = repair_project_run_states(
        sync_target, OWNER, apply=False, state_limit=0, inventory_loader=loader
    )
    assert too_small.error is not None
    too_large = repair_project_run_states(
        sync_target, OWNER, apply=False, state_limit=501, inventory_loader=loader
    )
    assert too_large.error is not None


def test_window_hood_cap(tmp_path: Path) -> None:
    _remote, sync_target = setup_repair(
        tmp_path,
        runs=[
            (f"hood-{suffix}", f"hood-{suffix}.job", f"run-{suffix}", "active")
            for suffix in ("a", "b", "c", "d", "e", "f")
        ],
    )
    loader = make_loader(
        [
            inv_run(f"run-{suffix}", f"hood-{suffix}.job", "completed")
            for suffix in ("a", "b", "c", "d", "e", "f")
        ],
        [],
    )
    report = repair_project_run_states(
        sync_target, OWNER, apply=False, inventory_loader=loader
    )

    assert report.examined == STATE_REPAIR_MAX_HOODS
    assert len({row.local_hood for row in report.window}) == STATE_REPAIR_MAX_HOODS
    assert report.pass_complete is False
    assert report.next_cursor is not None


def test_collect_reads_owner_manifest_constant_times(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import sase.agents_sync.publication_state_repair as repair_module
    import sase.agents_sync.v2_io as v2_io

    def seed(count: int, name: str) -> ProjectTarget:
        workdir = tmp_path / name
        workdir.mkdir()
        remote, _seed, sidecar = setup_repo(workdir)
        builder = SeedBuilder(sidecar)
        for index in range(count):
            hood = f"hood-{index}"
            builder.add_run(hood, f"{hood}.job", f"run-{index}", "active")
        builder.write_manifest()
        commit_push(sidecar)
        return target(workdir, remote, sidecar)

    small_target = seed(2, "small")
    large_target = seed(6, "large")

    original = v2_io.read_owner_manifest
    reads = 0

    def counting(*args, **kwargs):
        nonlocal reads
        reads += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(v2_io, "read_owner_manifest", counting)

    small_loader = make_loader(
        [
            inv_run(f"run-{index}", f"hood-{index}.job", "completed")
            for index in range(2)
        ],
        [],
    )
    repair_module.repair_project_run_states(
        small_target, OWNER, apply=False, inventory_loader=small_loader
    )
    small_reads = reads

    reads = 0
    large_loader = make_loader(
        [
            inv_run(f"run-{index}", f"hood-{index}.job", "completed")
            for index in range(6)
        ],
        [],
    )
    repair_module.repair_project_run_states(
        large_target, OWNER, apply=False, inventory_loader=large_loader
    )
    large_reads = reads

    assert small_reads == large_reads
    assert small_reads <= 2
