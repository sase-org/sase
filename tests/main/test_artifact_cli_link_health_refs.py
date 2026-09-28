"""Kind-scoped dangling-ref checks for rename repair."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from sase.artifact_cli._link_health_refs import dangling_refs
from sase.sdd.artifact_link_store import ArtifactLinkStore
from tests._conftest_environment import redirect_sase_home


def _store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ArtifactLinkStore:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    return ArtifactLinkStore(
        project_key="gh_sase-org__sase",
        sidecar_roots={},
    )


def _recording_resolver(
    calls: list[str],
) -> Any:
    def _resolve(ref: str, **_kwargs: object) -> SimpleNamespace:
        calls.append(ref)
        return SimpleNamespace(resolution=SimpleNamespace(status="exact"))

    return _resolve


def _rows() -> list[dict[str, Any]]:
    return [
        {
            "source_ref": "plan:202608/a.md",
            "target_ref": "research:202608/b.md",
        },
        {
            "source_ref": "agent:worker.athena",
            "target_ref": "file:default:0123456789abcdef01234567",
        },
        {
            "source_ref": "bead:sase-missing",
            "target_ref": "plan:202608/c.md",
        },
    ]


def test_dangling_refs_kinds_filter_skips_unrepairable_refs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.artifact_cli import _link_health_refs as refs_module

    store = _store(tmp_path, monkeypatch)

    def _fail_bead_ids(_store: object) -> set[str]:
        raise AssertionError("known_bead_ids should not run without bead in kinds")

    monkeypatch.setattr(refs_module, "known_bead_ids", _fail_bead_ids)
    calls: list[str] = []

    dangling, unpublished = dangling_refs(
        _rows(),
        store,
        context=SimpleNamespace(),  # type: ignore[arg-type]
        resolve_reference=_recording_resolver(calls),
        kinds={"plan", "research"},
    )

    assert dangling == []
    assert unpublished == []
    assert sorted(calls) == sorted(
        [
            "plan:202608/a.md",
            "research:202608/b.md",
            "plan:202608/c.md",
        ]
    )


def test_dangling_refs_without_kinds_resolves_all_non_bead_refs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.artifact_cli import _link_health_refs as refs_module

    store = _store(tmp_path, monkeypatch)
    monkeypatch.setattr(refs_module, "known_bead_ids", lambda _store: set())
    calls: list[str] = []

    dangling, unpublished = dangling_refs(
        _rows(),
        store,
        context=SimpleNamespace(),  # type: ignore[arg-type]
        resolve_reference=_recording_resolver(calls),
    )

    assert "bead:sase-missing" not in calls
    for ref in (
        "plan:202608/a.md",
        "research:202608/b.md",
        "agent:worker.athena",
        "file:default:0123456789abcdef01234567",
        "plan:202608/c.md",
    ):
        assert ref in calls
    assert dangling == ["bead:sase-missing"]
