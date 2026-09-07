"""Name-allocation lock must not enclose archive parsing or filesystem cleanup."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest

from sase.agent.names import (
    _registry,
    _wipe,
    claim_exact_planned_registered_name,
    rebuild_name_registry,
    reserve_registered_name,
    wipe_agent_names_for_reuse,
)
from sase.agent.names._resume import agent_name_allocation_lock as real_lock
from sase.core.agent_identity_facade import AgentIdentitySnapshot, AgentOwnerIdentity

from tests._agent_names_fixtures import make_agent


def _configure_machine(monkeypatch: pytest.MonkeyPatch) -> None:
    identity = AgentIdentitySnapshot(
        AgentOwnerIdentity("alice", "athena"),
        ("athena", "zeus"),
    )
    monkeypatch.setattr(
        AgentIdentitySnapshot,
        "current",
        classmethod(lambda _cls: identity),
    )


def _patch_lock(monkeypatch: pytest.MonkeyPatch, held: list[bool]) -> None:
    @contextmanager
    def tracking_lock() -> Iterator[None]:
        held.append(True)
        try:
            with real_lock():
                yield
        finally:
            held.pop()

    monkeypatch.setattr(
        "sase.agent.names._resume.agent_name_allocation_lock",
        tracking_lock,
    )


def test_rebuild_parses_sources_outside_the_allocation_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configure_machine(monkeypatch)
    make_agent(tmp_path, "proj", "20260724120000", "alpha", done=True)
    held: list[bool] = []
    scans_under_lock = 0
    real_collect = _registry._collect_artifact_entries

    def tracked_collect(*args: Any, **kwargs: Any) -> None:
        nonlocal scans_under_lock
        if held:
            scans_under_lock += 1
        real_collect(*args, **kwargs)

    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    _patch_lock(monkeypatch, held)
    monkeypatch.setattr(_registry, "_collect_artifact_entries", tracked_collect)

    rebuild_name_registry()

    assert scans_under_lock == 0


def test_wipe_does_not_delete_under_the_allocation_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configure_machine(monkeypatch)
    artifact = make_agent(tmp_path, "proj", "20260724120100", "beta", done=True)
    held: list[bool] = []
    deletes_under_lock = 0
    real_rmtree = _wipe.shutil.rmtree

    def tracked_rmtree(path: object, *args: object, **kwargs: object) -> None:
        nonlocal deletes_under_lock
        if held:
            deletes_under_lock += 1
        real_rmtree(path, *args, **kwargs)

    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    rebuild_name_registry()
    _patch_lock(monkeypatch, held)
    monkeypatch.setattr(_wipe.shutil, "rmtree", tracked_rmtree)

    wipe_agent_names_for_reuse(("beta",))

    assert deletes_under_lock == 0
    assert not artifact.exists()


def test_exact_planned_claim_does_not_parse_archives_under_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.agent.names._registry_scan_payloads import read_json_object

    _configure_machine(monkeypatch)
    artifacts_dir = tmp_path / ".sase/projects/proj/artifacts/ace-run/run-a"
    held: list[bool] = []
    parses_under_lock = 0

    def tracked_read(*args: object, **kwargs: object) -> object:
        nonlocal parses_under_lock
        if held:
            parses_under_lock += 1
        return read_json_object(*args, **kwargs)

    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    reserve_registered_name("planned-fast", artifacts_dir)
    artifacts_dir.mkdir(parents=True)
    _patch_lock(monkeypatch, held)
    monkeypatch.setattr(
        "sase.agent.names._registry_scan_payloads.read_json_object",
        tracked_read,
    )

    assert claim_exact_planned_registered_name("planned-fast", artifacts_dir)
    assert parses_under_lock == 0
