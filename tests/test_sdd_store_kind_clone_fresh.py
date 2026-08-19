"""``fresh`` threading from ensure_sdd_kind_clone/ensure_beads_sidecar_clone.

Covers the direct path, the owner-anchor recursion for a nested repo that
inherits its SDD record, and the beads path -- and that the default stays
``False`` when omitted.
"""

from __future__ import annotations

from collections.abc import Iterator
import json
from pathlib import Path

import pytest

from sase.sdd._store_records import record_cache
from sase.sdd.store import (
    ensure_beads_sidecar_clone,
    ensure_sdd_kind_clone,
    write_sdd_store_record,
)


@pytest.fixture(autouse=True)
def _clear_store_record_cache() -> Iterator[None]:
    record_cache.clear()
    yield
    record_cache.clear()


def _record_calls(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, object]]:
    calls: list[dict[str, object]] = []

    def fake(
        clone_dir: Path,
        remote_url: str,
        *,
        strict: bool = False,
        fresh: bool = False,
    ) -> None:
        calls.append(
            {
                "clone_dir": clone_dir,
                "remote_url": remote_url,
                "strict": strict,
                "fresh": fresh,
            }
        )

    monkeypatch.setattr("sase.sdd._store_link.ensure_sidecar_sdd_clone", fake)
    return calls


def _write_sidecar_record(primary: Path, *, with_beads: bool) -> None:
    sidecars: dict[str, dict[str, str]] = {
        "plans": {
            "repo": "owner/repo--plans",
            "remote_url": "git@example.test:owner/repo--plans.git",
        },
        "research": {
            "repo": "owner/repo--research",
            "remote_url": "git@example.test:owner/repo--research.git",
        },
    }
    if with_beads:
        sidecars["beads"] = {
            "repo": "owner/repo--beads",
            "remote_url": "git@example.test:owner/repo--beads.git",
        }
    write_sdd_store_record(
        primary,
        {
            "schema_version": 3 if with_beads else 2,
            "storage": "sidecar_repos",
            "provider": "github",
            "sidecars": sidecars,
        },
    )


@pytest.mark.parametrize("fresh", [False, True])
def test_ensure_sdd_kind_clone_threads_fresh_to_sidecar_clone(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fresh: bool,
) -> None:
    primary = tmp_path / "repo"
    primary.mkdir()
    _write_sidecar_record(primary, with_beads=False)
    calls = _record_calls(monkeypatch)

    kwargs = {"fresh": True} if fresh else {}
    ensure_sdd_kind_clone(primary, 1, "research", strict=True, **kwargs)

    assert len(calls) == 1
    assert calls[0]["fresh"] is fresh


def test_ensure_sdd_kind_clone_threads_fresh_through_owner_anchor_recursion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    primary = tmp_path / "repo"
    workspace = tmp_path / "repo_10"
    nested = workspace / "sase" / "repos" / "linked" / "other"
    primary.mkdir()
    nested.mkdir(parents=True)
    marker_dir = workspace / ".sase"
    marker_dir.mkdir()
    (marker_dir / "checkout.json").write_text(
        json.dumps(
            {
                "project_name": "repo",
                "project_key": "repo",
                "workspace_num": 10,
                "primary_workspace_dir": str(primary),
                "registry_path": str(tmp_path / "registry.json"),
                "schema_version": 1,
            }
        ),
        encoding="utf-8",
    )
    _write_sidecar_record(primary, with_beads=False)
    calls = _record_calls(monkeypatch)

    ensure_sdd_kind_clone(nested, 10, "research", strict=True, fresh=True)

    assert len(calls) == 1
    assert calls[0]["fresh"] is True


def test_ensure_sdd_kind_clone_beads_role_threads_fresh(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    primary = tmp_path / "repo"
    primary.mkdir()
    _write_sidecar_record(primary, with_beads=True)
    calls = _record_calls(monkeypatch)

    ensure_sdd_kind_clone(primary, 1, "beads", strict=True, fresh=True)

    assert len(calls) == 1
    assert calls[0]["fresh"] is True


def test_ensure_beads_sidecar_clone_threads_fresh(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    primary = tmp_path / "repo"
    primary.mkdir()
    _write_sidecar_record(primary, with_beads=True)
    calls = _record_calls(monkeypatch)

    ensure_beads_sidecar_clone(primary, 1, fresh=True)

    assert len(calls) == 1
    assert calls[0]["fresh"] is True


def test_ensure_beads_sidecar_clone_default_fresh_is_false(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    primary = tmp_path / "repo"
    primary.mkdir()
    _write_sidecar_record(primary, with_beads=True)
    calls = _record_calls(monkeypatch)

    ensure_beads_sidecar_clone(primary, 1)

    assert len(calls) == 1
    assert calls[0]["fresh"] is False
