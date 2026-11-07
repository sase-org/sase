"""Non-interactive sidecar deferral is reported as needs attention."""

from __future__ import annotations

import argparse
from io import StringIO
from pathlib import Path
from typing import Any

import pytest

from sase.main.init_onboarding import (
    _run_init_onboarding_result,
    run_init_onboarding_all,
)
from sase.main.init_registry import InitCommandSpec
from sase.main.repo_init_handler import plan_repo_init, run_repo_init
from sase.sdd._sidecar_init import SidecarInitSpec
from tests.main._repo_init_handler_creation_helpers import (
    make_preflight,
    mark_managed_project,
)
from tests.main.init_onboarding_helpers import _args, _batch_target, _reject_prompt

_DRIFT_ROLES = ("plans", "beads", "research", "agents")


def _repo_spec() -> InitCommandSpec:
    return InitCommandSpec("repo", "Repos", plan_repo_init, run_repo_init)


def _patch_missing_sidecars(
    monkeypatch: pytest.MonkeyPatch,
    roles: tuple[str, ...],
    *,
    authorizations: list[dict[str, bool] | None] | None = None,
) -> None:
    specs = tuple(SidecarInitSpec(role=role) for role in roles)
    monkeypatch.setattr(
        "sase.main.repo_init_handler._project_provider_sdd_policy",
        lambda _root: "separate_repo",
    )
    monkeypatch.setattr(
        "sase.main.repo_init_handler._configured_sidecar_specs",
        lambda _root: specs,
    )
    monkeypatch.setattr(
        "sase.sdd._sidecar_init.preflight_sidecars",
        lambda *_args: {role: make_preflight(role) for role in roles},
    )

    def initialize(
        _root: Path,
        _workspace: int,
        _specs: tuple[SidecarInitSpec, ...],
        *,
        creation_authorized: dict[str, bool] | None = None,
        publish_sidecar_changes: bool = True,
    ) -> Any:
        del _root, _workspace, _specs, publish_sidecar_changes
        if authorizations is not None:
            authorizations.append(creation_authorized)
        if creation_authorized and any(creation_authorized.values()):
            pytest.fail("onboarding must not authorize missing remote creation")
        raise AssertionError("onboarding must defer missing remote creation")

    monkeypatch.setattr("sase.sdd._sidecar_init.initialize_sidecars", initialize)


def test_bare_yes_missing_drift_sidecars_needs_attention(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    mark_managed_project(tmp_path)
    _patch_missing_sidecars(monkeypatch, _DRIFT_ROLES)
    args = argparse.Namespace(
        all=False,
        check=False,
        diff=False,
        enable_project_memory=False,
        no_commit=True,
        path=str(tmp_path),
        yes=True,
    )

    result = _run_init_onboarding_result(args, specs=(_repo_spec(),), stdin=StringIO())

    assert result.exit_code == 0
    assert result.status == "needs_attention"
    captured = capsys.readouterr()
    assert "sidecar creation needs a terminal" in captured.out
    for role in _DRIFT_ROLES:
        assert f"acme/widget--{role}" in captured.out
        assert f"acme/widget--{role} is missing" in captured.err


def test_bare_yes_missing_attachments_private_stays_initialized(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    mark_managed_project(tmp_path)
    _patch_missing_sidecars(monkeypatch, ("attachments-private",))
    args = argparse.Namespace(
        all=False,
        check=False,
        diff=False,
        enable_project_memory=False,
        no_commit=True,
        path=str(tmp_path),
        yes=True,
    )

    result = _run_init_onboarding_result(args, specs=(_repo_spec(),), stdin=StringIO())

    assert result.exit_code == 0
    assert result.status in {"initialized", "current"}
    captured = capsys.readouterr()
    assert "sidecar creation needs a terminal" not in captured.out
    assert "attachments-private is missing" in captured.err


def test_project_yes_missing_sidecars_batch_needs_attention(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    target = _batch_target(tmp_path, "love")
    mark_managed_project(target.workspace_dir)
    authorizations: list[dict[str, bool] | None] = []
    _patch_missing_sidecars(
        monkeypatch,
        _DRIFT_ROLES,
        authorizations=authorizations,
    )
    args = _args(yes=True, project=["love"])
    args.no_commit = True
    exit_code = run_init_onboarding_all(
        args,
        specs=(_repo_spec(),),
        stdin=StringIO(),
        input_func=_reject_prompt,
        targets=(target,),
    )

    assert exit_code == 1
    assert authorizations == []
    out = capsys.readouterr().out
    assert "Initialization summary: 1 checked, 1 needs attention" in out
    assert "sase init -p love" in out
