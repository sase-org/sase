"""Lifecycle and boot identity tests for runner failure facts."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.axe import runner_lifecycle_phase as lifecycle_mod
from sase.axe.run_agent_directive_metadata import preserved_agent_metadata
from tests.axe._runner_failure_facts_helpers import clean_lifecycle as clean_lifecycle


# --- lifecycle breadcrumbs ---------------------------------------------------


def test_breadcrumbs_are_written_in_order_and_bounded(tmp_path: Path) -> None:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    (artifacts / "agent_meta.json").write_text("{}", encoding="utf-8")

    lifecycle_mod.mark_lifecycle_phase(str(artifacts), "booting")
    lifecycle_mod.mark_lifecycle_phase(str(artifacts), "waiting")
    assert lifecycle_mod.current_lifecycle_phase() == "waiting"
    meta = json.loads((artifacts / "agent_meta.json").read_text(encoding="utf-8"))
    assert [entry["phase"] for entry in meta["lifecycle_phases"]] == [
        "booting",
        "waiting",
    ]

    for _ in range(20):
        lifecycle_mod.mark_lifecycle_phase(str(artifacts), "preparing")
    meta = json.loads((artifacts / "agent_meta.json").read_text(encoding="utf-8"))
    assert meta["lifecycle_phase"] == "preparing"
    assert meta["lifecycle_phase_at"]
    assert len(meta["lifecycle_phases"]) == lifecycle_mod.MAX_HISTORY_ENTRIES
    assert {entry["phase"] for entry in meta["lifecycle_phases"]} == {"preparing"}


def test_mark_with_missing_meta_updates_memory_only(tmp_path: Path) -> None:
    missing = tmp_path / "nope"
    assert lifecycle_mod.mark_lifecycle_phase(str(missing), "booting") == "booting"
    assert lifecycle_mod.current_lifecycle_phase() == "booting"
    assert not (missing / "agent_meta.json").exists()


def test_mark_rejects_unknown_phases() -> None:
    lifecycle_mod.mark_lifecycle_phase(None, "booting")
    assert lifecycle_mod.mark_lifecycle_phase(None, "nope") == "booting"
    assert lifecycle_mod.current_lifecycle_phase() == "booting"


def test_mark_never_raises_on_unwritable_dir(tmp_path: Path) -> None:
    block = tmp_path / "block"
    block.write_text("not a dir", encoding="utf-8")
    assert lifecycle_mod.mark_lifecycle_phase(str(block), "waiting") == "waiting"


# --- boot identity -----------------------------------------------------------


def test_boot_code_identity_covers_host_core_and_plugins(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(lifecycle_mod, "_boot_cache", None)
    try:
        identity, booted_at, elapsed_ms = lifecycle_mod.boot_code_identity()
    finally:
        monkeypatch.setattr(lifecycle_mod, "_boot_cache", None)
    assert identity["schema_version"] == 1
    assert identity["captured_at"]
    assert booted_at
    assert elapsed_ms >= 0
    by_role = {root["role"] for root in identity["roots"]}
    assert {"host", "core"} <= by_role
    host = next(root for root in identity["roots"] if root["role"] == "host")
    assert host["name"] == "sase"
    assert host["version"]
    assert host["install_type"] in {"editable", "wheel", "unknown"}
    for root in identity["roots"]:
        assert set(root) == {
            "name",
            "role",
            "version",
            "commit",
            "source_root",
            "install_type",
        }


def test_boot_code_identity_is_memoized(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(lifecycle_mod, "_boot_cache", None)
    try:
        first = lifecycle_mod.boot_code_identity(startup_commit="abc")
        second = lifecycle_mod.boot_code_identity()
    finally:
        monkeypatch.setattr(lifecycle_mod, "_boot_cache", None)
    assert first[0] is second[0]


def test_boot_code_identity_uses_first_distribution_record_on_sys_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import importlib.metadata

    class _Distribution:
        def __init__(self, name: str, version: str) -> None:
            self.metadata = {"Name": name, "Version": version}

    first_host = _Distribution("sase", "first-host")
    first_core = _Distribution("sase-core-rs", "first-core")
    first_plugin = _Distribution("sase-plugin-example", "first-plugin")
    records = [
        first_host,
        _Distribution("sase", "later-host"),
        first_core,
        _Distribution("sase-core-rs", "later-core"),
        first_plugin,
        _Distribution("sase-plugin-example", "later-plugin"),
    ]
    selected: list[tuple[str, str]] = []

    def package_record(
        dist: _Distribution,
        distribution_name: str,
        *,
        role: str,
        **_kwargs: object,
    ) -> dict[str, str]:
        selected.append((role, dist.metadata["Version"]))
        return {
            "name": distribution_name,
            "role": role,
            "version": dist.metadata["Version"],
        }

    monkeypatch.setattr(importlib.metadata, "distributions", lambda: records)
    monkeypatch.setattr(lifecycle_mod, "_package_root_from_dist", package_record)
    monkeypatch.setattr(lifecycle_mod, "_boot_cache", None)
    try:
        identity = lifecycle_mod._capture_boot_code_identity(startup_commit=None)
    finally:
        monkeypatch.setattr(lifecycle_mod, "_boot_cache", None)

    assert selected == [
        ("host", "first-host"),
        ("core", "first-core"),
        ("plugin", "first-plugin"),
    ]
    assert len(identity["roots"]) == 3


def test_preserved_metadata_keeps_identity_and_breadcrumbs(
    tmp_path: Path,
) -> None:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    (artifacts / "agent_meta.json").write_text(
        json.dumps(
            {
                "code_identity": {"schema_version": 1, "roots": []},
                "booted_at": "2026-10-09T00:00:00+00:00",
                "lifecycle_phase": "waiting",
                "lifecycle_phase_at": "2026-10-09T00:01:00+00:00",
                "lifecycle_phases": [{"phase": "waiting", "at": "x"}],
            }
        ),
        encoding="utf-8",
    )
    preserved = preserved_agent_metadata(str(artifacts))
    assert preserved["code_identity"] == {"schema_version": 1, "roots": []}
    assert preserved["booted_at"] == "2026-10-09T00:00:00+00:00"
    assert preserved["lifecycle_phase"] == "waiting"
    assert preserved["lifecycle_phase_at"] == "2026-10-09T00:01:00+00:00"
    assert preserved["lifecycle_phases"] == [{"phase": "waiting", "at": "x"}]
