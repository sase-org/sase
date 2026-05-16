"""Tests for the Phase 4 index-maintenance adapter (``sase-3r.4``).

The adapter wraps the Rust-backed agent artifact index facade with a
best-effort, coalescing surface that lifecycle / dismiss / revive code
paths can call without worrying about exceptions or write storms.
"""

from __future__ import annotations

import json
import sys
import time
import types
from collections.abc import Iterator
from pathlib import Path

import pytest

from sase.core import agent_artifact_index_maintenance as maintenance


class _FakeRust:
    """Captures calls to the Rust extension methods."""

    def __init__(self) -> None:
        self.upsert_calls: list[tuple[str, str, str]] = []
        self.delete_calls: list[str] = []
        self.dismiss_upserts: list[dict] = []
        self.dismiss_deletes: list[tuple[str, str, str | None]] = []
        self.dismiss_replaces: list[list[dict]] = []
        self.fail_next_upsert: bool = False

    def upsert_agent_artifact_index_row(
        self, index_path: str, projects_root: str, artifact_dir: str, options: dict
    ) -> dict:
        if self.fail_next_upsert:
            self.fail_next_upsert = False
            raise RuntimeError("simulated index failure")
        self.upsert_calls.append((index_path, projects_root, artifact_dir))
        return {"index_path": index_path, "row_count": 1, "schema_version": 1}

    def delete_agent_artifact_index_row(
        self, index_path: str, artifact_dir: str
    ) -> dict:
        self.delete_calls.append(artifact_dir)
        return {"index_path": index_path, "row_count": 0, "schema_version": 1}

    def upsert_dismissed_agent_visibility(
        self, index_path: str, identity: dict
    ) -> dict:
        self.dismiss_upserts.append(identity)
        return {"index_path": index_path, "row_count": 1, "schema_version": 1}

    def delete_dismissed_agent_visibility(
        self,
        index_path: str,
        agent_type: str,
        cl_name: str,
        raw_suffix: str | None,
    ) -> dict:
        self.dismiss_deletes.append((agent_type, cl_name, raw_suffix))
        return {"index_path": index_path, "row_count": 0, "schema_version": 1}

    def replace_dismissed_agent_visibility(
        self, index_path: str, identities: list[dict]
    ) -> dict:
        self.dismiss_replaces.append(list(identities))
        return {
            "index_path": index_path,
            "row_count": len(identities),
            "schema_version": 1,
        }


def _reset_module_state() -> None:
    maintenance._last_upsert_time.clear()
    maintenance._last_dismissed_signature = maintenance._DISMISSED_SIGNATURE_UNSET


@pytest.fixture(autouse=True)
def _reset_state() -> Iterator[None]:
    _reset_module_state()
    yield
    _reset_module_state()


@pytest.fixture()
def fake_rust(monkeypatch: pytest.MonkeyPatch) -> _FakeRust:
    """Install a fake ``sase_core_rs`` exposing the maintenance APIs."""
    from sase.core.rust import RUST_EXTENSION_MODULE_NAME

    fake = _FakeRust()
    module = types.ModuleType(RUST_EXTENSION_MODULE_NAME)
    module.upsert_agent_artifact_index_row = fake.upsert_agent_artifact_index_row
    module.delete_agent_artifact_index_row = fake.delete_agent_artifact_index_row
    module.upsert_dismissed_agent_visibility = fake.upsert_dismissed_agent_visibility
    module.delete_dismissed_agent_visibility = fake.delete_dismissed_agent_visibility
    module.replace_dismissed_agent_visibility = fake.replace_dismissed_agent_visibility
    monkeypatch.setitem(sys.modules, RUST_EXTENSION_MODULE_NAME, module)
    return fake


@pytest.fixture()
def index_path(tmp_path: Path) -> Path:
    path = tmp_path / "agent_artifact_index.sqlite"
    path.write_bytes(b"placeholder")  # passes is_file() guard
    return path


def test_upsert_artifact_dir_calls_rust_facade(
    fake_rust: _FakeRust, tmp_path: Path, index_path: Path
) -> None:
    artifact_dir = tmp_path / "proj" / "artifacts" / "ace-run" / "20260516120000"
    artifact_dir.mkdir(parents=True)

    ok = maintenance.upsert_artifact_dir(
        artifact_dir,
        projects_root=tmp_path,
        index_path=index_path,
    )

    assert ok is True
    assert len(fake_rust.upsert_calls) == 1
    assert fake_rust.upsert_calls[0][2] == str(artifact_dir)


def test_upsert_artifact_dir_no_index_skips_call(
    fake_rust: _FakeRust, tmp_path: Path
) -> None:
    """Missing index returns True without invoking Rust."""
    artifact_dir = tmp_path / "proj" / "artifacts" / "ace-run" / "ts"
    artifact_dir.mkdir(parents=True)

    ok = maintenance.upsert_artifact_dir(
        artifact_dir,
        projects_root=tmp_path,
        index_path=tmp_path / "missing.sqlite",
    )

    assert ok is True
    assert fake_rust.upsert_calls == []


def test_upsert_artifact_dir_swallows_rust_errors(
    fake_rust: _FakeRust, tmp_path: Path, index_path: Path
) -> None:
    fake_rust.fail_next_upsert = True

    ok = maintenance.upsert_artifact_dir(
        tmp_path / "proj" / "artifacts" / "ace-run" / "ts",
        projects_root=tmp_path,
        index_path=index_path,
    )

    assert ok is False


def test_upsert_artifact_dir_coalesces_repeat_calls(
    fake_rust: _FakeRust, tmp_path: Path, index_path: Path
) -> None:
    """Two upserts in the coalesce window only commit one Rust call."""
    artifact_dir = tmp_path / "proj" / "artifacts" / "ace-run" / "ts"
    artifact_dir.mkdir(parents=True)

    maintenance.upsert_artifact_dir(
        artifact_dir, projects_root=tmp_path, index_path=index_path
    )
    maintenance.upsert_artifact_dir(
        artifact_dir, projects_root=tmp_path, index_path=index_path
    )
    maintenance.upsert_artifact_dir(
        artifact_dir, projects_root=tmp_path, index_path=index_path
    )

    assert len(fake_rust.upsert_calls) == 1


def test_upsert_artifact_dir_coalesce_false_always_calls(
    fake_rust: _FakeRust, tmp_path: Path, index_path: Path
) -> None:
    artifact_dir = tmp_path / "proj" / "artifacts" / "ace-run" / "ts"
    artifact_dir.mkdir(parents=True)

    maintenance.upsert_artifact_dir(
        artifact_dir,
        projects_root=tmp_path,
        index_path=index_path,
        coalesce=False,
    )
    maintenance.upsert_artifact_dir(
        artifact_dir,
        projects_root=tmp_path,
        index_path=index_path,
        coalesce=False,
    )

    assert len(fake_rust.upsert_calls) == 2


def test_delete_artifact_dir_clears_coalesce_state(
    fake_rust: _FakeRust, tmp_path: Path, index_path: Path
) -> None:
    artifact_dir = tmp_path / "proj" / "artifacts" / "ace-run" / "ts"
    artifact_dir.mkdir(parents=True)

    maintenance.upsert_artifact_dir(
        artifact_dir, projects_root=tmp_path, index_path=index_path
    )
    maintenance.delete_artifact_dir(artifact_dir, index_path=index_path)
    # Subsequent upsert should not be coalesced because the delete cleared state.
    maintenance.upsert_artifact_dir(
        artifact_dir, projects_root=tmp_path, index_path=index_path
    )

    assert fake_rust.delete_calls == [str(artifact_dir)]
    assert len(fake_rust.upsert_calls) == 2


def test_sync_dismissed_visibility_replaces_sidecar(
    fake_rust: _FakeRust, index_path: Path
) -> None:
    identities = [("workflow", "cl", "ts"), ("running", "other", None)]
    maintenance.sync_dismissed_visibility(identities, index_path=index_path)

    assert len(fake_rust.dismiss_replaces) == 1
    replaced = fake_rust.dismiss_replaces[0]
    assert {
        (entry["agent_type"], entry["cl_name"], entry["raw_suffix"])
        for entry in replaced
    } == {
        ("workflow", "cl", "ts"),
        ("running", "other", None),
    }


def test_maybe_sync_dismissed_from_file_signature_gates(
    fake_rust: _FakeRust, tmp_path: Path, index_path: Path
) -> None:
    dismissed_file = tmp_path / "dismissed_agents.json"
    dismissed_file.write_text(json.dumps([["workflow", "cl", "ts"]]))

    maintenance.maybe_sync_dismissed_from_file(
        dismissed_file=dismissed_file, index_path=index_path
    )
    # Second call with unchanged file should skip the rust call.
    maintenance.maybe_sync_dismissed_from_file(
        dismissed_file=dismissed_file, index_path=index_path
    )

    assert len(fake_rust.dismiss_replaces) == 1


def test_maybe_sync_dismissed_from_file_detects_mtime_change(
    fake_rust: _FakeRust, tmp_path: Path, index_path: Path
) -> None:
    dismissed_file = tmp_path / "dismissed_agents.json"
    dismissed_file.write_text(json.dumps([["workflow", "cl", "ts"]]))

    maintenance.maybe_sync_dismissed_from_file(
        dismissed_file=dismissed_file, index_path=index_path
    )

    # Rewrite with a different mtime to invalidate the cached signature.
    time.sleep(0.01)
    dismissed_file.write_text(json.dumps([["workflow", "cl_two", "ts2"]]))

    maintenance.maybe_sync_dismissed_from_file(
        dismissed_file=dismissed_file, index_path=index_path
    )

    assert len(fake_rust.dismiss_replaces) == 2


def test_maybe_sync_dismissed_from_file_missing_file_clears(
    fake_rust: _FakeRust, tmp_path: Path, index_path: Path
) -> None:
    """A missing dismissed_agents.json syncs an empty sidecar."""
    maintenance.maybe_sync_dismissed_from_file(
        dismissed_file=tmp_path / "absent.json",
        index_path=index_path,
    )

    assert fake_rust.dismiss_replaces == [[]]


def test_maybe_sync_dismissed_from_file_load_failure_keeps_sidecar(
    fake_rust: _FakeRust,
    tmp_path: Path,
    index_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A bad legacy read must not replace indexed dismissals with empty state."""
    dismissed_file = tmp_path / "dismissed_agents.json"
    dismissed_file.write_text(json.dumps([["workflow", "cl", "ts"]]))
    monkeypatch.setattr(
        "sase.ace.dismissed_agents_state.load_dismissed_agents",
        lambda path: (_ for _ in ()).throw(ValueError("bad json")),
    )

    ok = maintenance.maybe_sync_dismissed_from_file(
        dismissed_file=dismissed_file,
        index_path=index_path,
    )

    assert ok is False
    assert fake_rust.dismiss_replaces == []


def test_maybe_sync_dismissed_from_file_no_index_skips(
    fake_rust: _FakeRust, tmp_path: Path
) -> None:
    ok = maintenance.maybe_sync_dismissed_from_file(
        dismissed_file=tmp_path / "absent.json",
        index_path=tmp_path / "missing.sqlite",
    )

    assert ok is True
    assert fake_rust.dismiss_replaces == []
