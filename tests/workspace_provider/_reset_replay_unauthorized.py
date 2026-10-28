"""Authorization and happy-path coverage for reset-and-replay."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.workspace_provider.ownership import (
    AccessKind,
    OperationContext,
    WorkspaceOwnershipError,
)
from sase.workspace_provider.reset_replay import (
    DEFAULT_MAX_ATTEMPTS,
    ResetReplayResult,
    reset_and_replay,
    reset_leased_checkout_to_upstream,
)
from tests.workspace_provider._reset_replay_helpers import (
    clone_repo,
    init_origin,
    operation_context,
    redirect_rescue_state,  # noqa: F401 (registers the autouse fixture)
)

__all__ = [
    "TestRefusesUnauthorizedContexts",
    "TestSuccessfulReplay",
    "redirect_rescue_state",
]


def _assert_reset_entry_points_refused(
    context: OperationContext,
    repo_root: Path,
    match: str,
) -> None:
    with pytest.raises(WorkspaceOwnershipError, match=match):
        reset_and_replay(context, repo_root, lambda: "ok")
    with pytest.raises(WorkspaceOwnershipError, match=match):
        reset_leased_checkout_to_upstream(context, repo_root)


class TestRefusesUnauthorizedContexts:
    def test_refuses_primary_workspace(self, tmp_path: Path) -> None:
        checkout = tmp_path / "primary"
        checkout.mkdir()
        context = operation_context(checkout, checkout, workspace_num=0)
        _assert_reset_entry_points_refused(context, checkout, "primary workspace #0")

    def test_refuses_read_only_canonical(self, tmp_path: Path) -> None:
        checkout = tmp_path / "primary"
        checkout.mkdir()
        context = operation_context(
            checkout, checkout, access_kind=AccessKind.READ_ONLY_CANONICAL
        )
        _assert_reset_entry_points_refused(
            context, checkout, "leased operational context"
        )

    def test_refuses_user_directed(self, tmp_path: Path) -> None:
        checkout = tmp_path / "proj"
        checkout.mkdir()
        context = operation_context(
            checkout, checkout, access_kind=AccessKind.USER_DIRECTED
        )
        _assert_reset_entry_points_refused(
            context, checkout, "leased operational context"
        )

    def test_refuses_primary_sidecar_sync(self, tmp_path: Path) -> None:
        checkout = tmp_path / "primary--beads"
        checkout.mkdir()
        primary = tmp_path / "primary"
        primary.mkdir()
        context = operation_context(
            checkout, primary, access_kind=AccessKind.PRIMARY_SIDECAR_SYNC
        )
        _assert_reset_entry_points_refused(
            context, checkout, "leased operational context"
        )

    def test_refuses_missing_live_claim(self, tmp_path: Path) -> None:
        checkout = tmp_path / "proj_10"
        checkout.mkdir()
        primary = tmp_path / "proj"
        primary.mkdir()
        context = operation_context(checkout, primary, no_claim=True)
        _assert_reset_entry_points_refused(context, checkout, "no live workspace claim")

    def test_refuses_repo_outside_checkout(self, tmp_path: Path) -> None:
        checkout = tmp_path / "proj_10"
        checkout.mkdir()
        outside = tmp_path / "elsewhere"
        outside.mkdir()
        primary = tmp_path / "proj"
        primary.mkdir()
        context = operation_context(checkout, primary)
        _assert_reset_entry_points_refused(context, outside, "outside leased checkout")

    def test_no_git_commands_run_before_authorization_fails(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        checkout = tmp_path / "primary"
        checkout.mkdir()
        context = operation_context(checkout, checkout, workspace_num=0)
        called = False

        def _boom(*_args: object, **_kwargs: object) -> None:
            nonlocal called
            called = True

        monkeypatch.setattr(
            "sase.workspace_provider.reset_replay._run_git",
            _boom,
        )
        with pytest.raises(WorkspaceOwnershipError):
            reset_and_replay(context, checkout, lambda: "ok")
        with pytest.raises(WorkspaceOwnershipError):
            reset_leased_checkout_to_upstream(context, checkout)
        assert called is False


class TestSuccessfulReplay:
    def test_first_attempt_success_does_not_reset(self, tmp_path: Path) -> None:
        origin = tmp_path / "origin"
        checkout = tmp_path / "proj_10"
        init_origin(origin)
        clone_repo(origin, checkout)
        context = operation_context(checkout, tmp_path / "proj")
        n = 0

        def _operation() -> str:
            nonlocal n
            n += 1
            return "done"

        result = reset_and_replay(context, checkout, _operation)
        assert result == ResetReplayResult(
            value="done",
            attempts=1,
            reset_performed=False,
            recovery_ref=None,
        )
        assert n == 1

    def test_max_attempts_defaults_to_three(self) -> None:
        assert DEFAULT_MAX_ATTEMPTS == 3
