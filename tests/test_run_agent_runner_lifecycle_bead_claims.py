"""Held bead claim release behavior of ``finalize_runner_shutdown``."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sase.axe.run_agent_runner_lifecycle import finalize_runner_shutdown
from sase.bead.claims import (
    BEAD_CLAIM_MARKER,
    BeadClaimReleaseOutcome,
    write_bead_claim_marker,
)
from tests._run_agent_runner_lifecycle_helpers import (
    make_context,
    make_deps,
    make_state,
)


def _write_marker(artifacts_dir: Path) -> None:
    assert write_bead_claim_marker(
        artifacts_dir,
        project_name="sase",
        bead_id="sase-1.2",
        agent_name="sase-1.2",
    )


def test_finalize_releases_held_prelaunch_bead_claim(tmp_path: Path) -> None:
    context = make_context(tmp_path, is_home_mode=True)
    deps = make_deps(was_killed=MagicMock(return_value=True))

    with patch(
        "sase.bead.claims.release_bead_claim_for_agent",
        return_value=BeadClaimReleaseOutcome.RELEASED,
    ) as release:
        finalize_runner_shutdown(
            context=context,
            state=make_state(
                error_summary=None,
                suppress_completion_notification=True,
                held_bead_claim_id="sase-1.2",
                held_bead_claim_agent="sase-1.2",
                held_bead_claim_project="sase",
            ),
            deps=deps,
        )

    release.assert_called_once_with(
        project_name="sase",
        bead_id="sase-1.2",
        agent_name="sase-1.2",
    )


def test_finalize_releases_marker_only_prelaunch_bead_claim(tmp_path: Path) -> None:
    _write_marker(tmp_path)
    context = make_context(tmp_path, is_home_mode=True)
    deps = make_deps(was_killed=MagicMock(return_value=True))

    with patch(
        "sase.bead.claims.release_bead_claim_for_agent",
        return_value=BeadClaimReleaseOutcome.RELEASED,
    ) as release:
        finalize_runner_shutdown(
            context=context,
            state=make_state(
                error_summary=None,
                suppress_completion_notification=True,
            ),
            deps=deps,
        )

    release.assert_called_once_with(
        project_name="sase",
        bead_id="sase-1.2",
        agent_name="sase-1.2",
    )
    assert not (tmp_path / BEAD_CLAIM_MARKER).exists()


@pytest.mark.parametrize(
    "outcome",
    [
        BeadClaimReleaseOutcome.RELEASED,
        BeadClaimReleaseOutcome.NOTHING_TO_RELEASE,
    ],
)
def test_finalize_clears_marker_after_non_error_release_outcome(
    tmp_path: Path,
    outcome: BeadClaimReleaseOutcome,
) -> None:
    _write_marker(tmp_path)
    context = make_context(tmp_path, is_home_mode=True)
    deps = make_deps(was_killed=MagicMock(return_value=True))

    with patch(
        "sase.bead.claims.release_bead_claim_for_agent",
        return_value=outcome,
    ):
        finalize_runner_shutdown(
            context=context,
            state=make_state(
                error_summary=None,
                suppress_completion_notification=True,
            ),
            deps=deps,
        )

    assert not (tmp_path / BEAD_CLAIM_MARKER).exists()


def test_finalize_preserves_marker_after_release_error(tmp_path: Path) -> None:
    _write_marker(tmp_path)
    context = make_context(tmp_path, is_home_mode=True)
    deps = make_deps(was_killed=MagicMock(return_value=True))

    with patch(
        "sase.bead.claims.release_bead_claim_for_agent",
        return_value=BeadClaimReleaseOutcome.ERROR,
    ):
        finalize_runner_shutdown(
            context=context,
            state=make_state(
                error_summary=None,
                suppress_completion_notification=True,
            ),
            deps=deps,
        )

    assert (tmp_path / BEAD_CLAIM_MARKER).exists()


def test_finalize_does_not_release_promoted_marker_claim(tmp_path: Path) -> None:
    _write_marker(tmp_path)
    (tmp_path / "agent_meta.json").write_text(
        '{"bead_claim_promoted": true}',
        encoding="utf-8",
    )
    context = make_context(tmp_path, is_home_mode=True)
    deps = make_deps(was_killed=MagicMock(return_value=True))

    with patch("sase.bead.claims.release_bead_claim_for_agent") as release:
        finalize_runner_shutdown(
            context=context,
            state=make_state(
                error_summary=None,
                suppress_completion_notification=True,
            ),
            deps=deps,
        )

    release.assert_not_called()


@pytest.mark.parametrize(
    "marker",
    [".sase_plan_pending", ".sase_questions_pending", ".sase_pipe_pending"],
)
def test_finalize_preserves_held_bead_claim_for_pending_handoff(
    tmp_path: Path, marker: str
) -> None:
    (tmp_path / marker).touch()
    context = make_context(tmp_path, is_home_mode=True)
    deps = make_deps()

    with patch("sase.bead.claims.release_bead_claim_for_agent") as release:
        finalize_runner_shutdown(
            context=context,
            state=make_state(
                error_summary=None,
                suppress_completion_notification=True,
                held_bead_claim_id="sase-1.2",
                held_bead_claim_agent="sase-1.2",
                held_bead_claim_project="sase",
            ),
            deps=deps,
        )

    release.assert_not_called()


def test_finalize_preserves_marker_only_bead_claim_for_pending_handoff(
    tmp_path: Path,
) -> None:
    (tmp_path / ".sase_plan_pending").touch()
    _write_marker(tmp_path)
    context = make_context(tmp_path, is_home_mode=True)
    deps = make_deps()

    with patch("sase.bead.claims.release_bead_claim_for_agent") as release:
        finalize_runner_shutdown(
            context=context,
            state=make_state(
                error_summary=None,
                suppress_completion_notification=True,
            ),
            deps=deps,
        )

    release.assert_not_called()
    assert (tmp_path / BEAD_CLAIM_MARKER).exists()


def test_finalize_ignores_corrupt_bead_claim_marker_with_warning(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / BEAD_CLAIM_MARKER).write_text("{", encoding="utf-8")
    context = make_context(tmp_path, is_home_mode=True)
    deps = make_deps(was_killed=MagicMock(return_value=True))

    with patch("sase.bead.claims.release_bead_claim_for_agent") as release:
        finalize_runner_shutdown(
            context=context,
            state=make_state(
                error_summary=None,
                suppress_completion_notification=True,
            ),
            deps=deps,
        )

    release.assert_not_called()
    assert "Warning: Failed to read bead claim marker" in capsys.readouterr().err
