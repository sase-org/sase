"""Coverage for connect-only SDD store auto-init on a project's first launch."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.sdd._auto_init import auto_connect_sdd_store
from sase.sdd._sidecar_init import _SidecarInitOutcome, SidecarInitSpec
from sase.sdd.store import SddMaterializationError, write_sdd_store_record
from tests.main.repo_init_handler_helpers import _mark_managed_project, _preflight


def _outcome(
    project_root: Path, specs: tuple[SidecarInitSpec, ...]
) -> _SidecarInitOutcome:
    return _SidecarInitOutcome(
        store=None,
        record=None,
        created=frozenset(),
        roots={
            spec.role: project_root / "sase" / "repos" / spec.role for spec in specs
        },
    )


def test_materialized_record_already_present_is_a_noop(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mark_managed_project(tmp_path)
    write_sdd_store_record(
        tmp_path,
        {
            "storage": "separate_repo",
            "provider": "github",
            "remote_url": "https://example.test/widget--plans.git",
            "discovery": "found",
        },
    )
    monkeypatch.setattr(
        "sase.sdd._sidecar_init.preflight_sidecars",
        lambda *_args: pytest.fail("must not preflight an already-materialized store"),
    )
    monkeypatch.setattr(
        "sase.sdd._sidecar_init.initialize_sidecars",
        lambda *_args, **_kwargs: pytest.fail(
            "must not initialize an already-materialized store"
        ),
    )

    assert auto_connect_sdd_store(tmp_path, 1) is True


def test_unmanaged_repo_is_a_noop(tmp_path: Path) -> None:
    _mark_managed_project(tmp_path, config="is_sase_managed: false\n")

    assert auto_connect_sdd_store(tmp_path, 1) is False


def test_non_project_directory_is_a_noop(tmp_path: Path) -> None:
    assert auto_connect_sdd_store(tmp_path, 1) is False


def test_non_remote_backed_policy_is_a_noop(
    tmp_path: Path,
    provider_patch,
) -> None:
    _mark_managed_project(tmp_path)
    provider_patch("bare_git")

    assert auto_connect_sdd_store(tmp_path, 1) is False


def test_all_configured_sidecars_found_connects_without_creation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    provider_patch,
) -> None:
    _mark_managed_project(tmp_path)
    provider_patch("github")
    specs = (SidecarInitSpec(role="plans"), SidecarInitSpec(role="research"))
    monkeypatch.setattr(
        "sase.main._repo_init_config.configured_sidecar_specs",
        lambda _root: specs,
    )
    monkeypatch.setattr(
        "sase.sdd._sidecar_init.preflight_sidecars",
        lambda *_args: {
            "plans": _preflight("plans", status="found"),
            "research": _preflight("research", status="found"),
        },
    )
    calls: list[tuple[tuple[SidecarInitSpec, ...], dict[str, bool] | None, bool]] = []

    def initialize(
        _root: Path,
        _workspace: int,
        selected: tuple[SidecarInitSpec, ...],
        *,
        creation_authorized: dict[str, bool] | None = None,
        publish_sidecar_changes: bool = True,
    ) -> _SidecarInitOutcome:
        calls.append((selected, creation_authorized, publish_sidecar_changes))
        return _outcome(tmp_path, selected)

    monkeypatch.setattr("sase.sdd._sidecar_init.initialize_sidecars", initialize)

    assert auto_connect_sdd_store(tmp_path, 1) is True
    assert calls == [(specs, {}, True)]


def test_missing_non_agents_sidecar_raises_actionable_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    provider_patch,
) -> None:
    _mark_managed_project(tmp_path)
    provider_patch("github")
    specs = (SidecarInitSpec(role="plans"),)
    monkeypatch.setattr(
        "sase.main._repo_init_config.configured_sidecar_specs",
        lambda _root: specs,
    )
    monkeypatch.setattr(
        "sase.sdd._sidecar_init.preflight_sidecars",
        lambda *_args: {"plans": _preflight("plans", status="not_found")},
    )
    monkeypatch.setattr(
        "sase.sdd._sidecar_init.initialize_sidecars",
        lambda *_args, **_kwargs: pytest.fail("must not create a missing sidecar"),
    )

    with pytest.raises(SddMaterializationError) as excinfo:
        auto_connect_sdd_store(tmp_path, 1)

    message = str(excinfo.value)
    assert "sase repo init" in message
    assert str(tmp_path) in message


def test_missing_agents_sidecar_is_dropped_with_a_warning(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    provider_patch,
) -> None:
    _mark_managed_project(tmp_path)
    provider_patch("github")
    specs = (SidecarInitSpec(role="plans"), SidecarInitSpec(role="agents"))
    monkeypatch.setattr(
        "sase.main._repo_init_config.configured_sidecar_specs",
        lambda _root: specs,
    )
    monkeypatch.setattr(
        "sase.sdd._sidecar_init.preflight_sidecars",
        lambda *_args: {
            "plans": _preflight("plans", status="found"),
            "agents": _preflight("agents", status="not_found"),
        },
    )
    calls: list[tuple[SidecarInitSpec, ...]] = []

    def initialize(
        _root: Path,
        _workspace: int,
        selected: tuple[SidecarInitSpec, ...],
        *,
        creation_authorized: dict[str, bool] | None = None,
        publish_sidecar_changes: bool = True,
    ) -> _SidecarInitOutcome:
        calls.append(selected)
        assert creation_authorized == {}
        return _outcome(tmp_path, selected)

    monkeypatch.setattr("sase.sdd._sidecar_init.initialize_sidecars", initialize)

    assert auto_connect_sdd_store(tmp_path, 1) is True
    assert calls == [(specs[0],)]
    assert "sase repo init" in capsys.readouterr().err
