"""Durable apply completion and create-preference coverage."""

from __future__ import annotations

from pathlib import Path
from typing import Any
import weakref

import pytest

from sase.ace.tui.actions.proc_actions import TrackedProcCompletion
from sase.ace.tui.modals._new_project_apply_flow import _intent_from_submission
from sase.ace.tui.modals._new_project_apply_shared import (
    on_project_apply_complete,
    record_successful_create_preferences,
)
from sase.ace.tui.modals.new_project_review_model import apply_submission
from sase.ace.tui.proc_observer import ObservedProc
from sase.core.time import local_now
from sase.project_onboarding.preferences import load_preferences
from tests.ace.tui.modals._new_project_create_execution_helpers import create_document


def _create_proc() -> ObservedProc:
    return ObservedProc(
        proc_id="create-1",
        proc_type="project.create",
        cl_name="",
        project_file="",
        status="running",
        message="running",
        started_at=local_now(),
    )


def _sync_persist(intent: Any) -> None:
    record_successful_create_preferences(
        str(intent.get("workflow_type") or ""),
        str(intent.get("owner") or ""),
        str(intent.get("visibility") or ""),
    )


def test_dismissed_create_success_records_visibility(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "sase-home"))
    monkeypatch.setattr(
        "sase.ace.tui.modals._new_project_apply_shared._persist_create_preferences_async",
        _sync_persist,
    )
    reloads: list[object] = []
    monkeypatch.setattr(
        "sase.ace.tui.modals._new_project_apply_shared.reload_projects_if_mounted",
        lambda app: reloads.append(app),
    )

    class _Gone:
        is_mounted = False

    app = object()
    document = create_document()
    intent = _intent_from_submission(apply_submission(document))
    on_project_apply_complete(
        app,
        weakref.ref(_Gone()),
        intent,
        TrackedProcCompletion(
            proc_info=_create_proc(),
            success=True,
            message="created",
            output="",
        ),
    )
    assert reloads == [app]
    prefs = load_preferences()
    assert prefs.last_visibility == {"sase-org": intent["visibility"]}
    assert prefs.last_owner == {"gh": "sase-org"}
    assert prefs.last_provider == "gh"


def test_failed_create_does_not_overwrite_visibility(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "sase-home"))
    monkeypatch.setattr(
        "sase.ace.tui.modals._new_project_apply_shared._persist_create_preferences_async",
        _sync_persist,
    )
    from sase.project_onboarding.preferences import record_visibility_selection

    record_visibility_selection("sase-org", "private")

    class _Gone:
        is_mounted = False

    intent = {
        "mode": "create",
        "workflow_type": "gh",
        "owner": "sase-org",
        "visibility": "public",
    }
    on_project_apply_complete(
        object(),
        weakref.ref(_Gone()),
        intent,
        TrackedProcCompletion(
            proc_info=_create_proc(),
            success=False,
            message="failed",
            output="",
        ),
    )
    assert load_preferences().last_visibility == {"sase-org": "private"}


def test_add_complete_does_not_record_visibility(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "sase-home"))
    monkeypatch.setattr(
        "sase.ace.tui.modals._new_project_apply_shared._persist_create_preferences_async",
        _sync_persist,
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals._new_project_apply_shared._persist_add_preferences_async",
        lambda _intent: None,
    )
    from sase.ace.tui.modals._new_project_apply_shared import on_project_add_complete

    class _Gone:
        is_mounted = False

    on_project_add_complete(
        object(),
        weakref.ref(_Gone()),
        {"mode": "add", "workflow_type": "gh", "owner": "sase-org"},
        TrackedProcCompletion(
            proc_info=_create_proc(),
            success=True,
            message="added",
            output="",
        ),
    )
    assert load_preferences().last_visibility == {}
