"""Tests for shared session display identity (``sase.sessions.display``)."""

from __future__ import annotations

from sase.sessions.display import (
    DEAD_SESSION_MARK,
    NO_SESSION_MARK,
    SESSION_HANDLE_LENGTH,
    SESSION_PALETTE,
    session_chip,
    session_color,
    session_display_label,
    short_session_handle,
)
from sase.sessions.registry import SessionIdentity

SESSION_A = "20260725T120000Z-4242"
SESSION_B = "20260725T130000Z-77"


def _identity(
    session_id: str = SESSION_A,
    *,
    kind: str = "ace",
    project: str | None = "sase",
    workspace_num: int | None = 27,
) -> SessionIdentity:
    return SessionIdentity(
        session_id=session_id,
        kind=kind,
        pid=4242,
        started_at="2026-07-25T12:00:00Z",
        project=project,
        workspace_num=workspace_num,
    )


# --- short_session_handle ---


def test_short_session_handle_is_stable() -> None:
    assert short_session_handle(SESSION_A) == short_session_handle(SESSION_A)


def test_short_session_handle_shape() -> None:
    handle = short_session_handle(SESSION_A)
    assert len(handle) == SESSION_HANDLE_LENGTH
    assert handle.islower() or handle.isdigit()
    assert not set(handle) & set("ilou")


def test_short_session_handle_differs_between_sessions() -> None:
    assert short_session_handle(SESSION_A) != short_session_handle(SESSION_B)


# --- session_color ---


def test_session_color_is_stable_and_from_the_palette() -> None:
    color = session_color(SESSION_A)
    assert color == session_color(SESSION_A)
    assert color in SESSION_PALETTE


# --- session_display_label ---


def test_session_display_label_includes_project_and_workspace() -> None:
    assert session_display_label(_identity()) == "ace·sase#27"


def test_session_display_label_without_a_workspace_number() -> None:
    assert session_display_label(_identity(workspace_num=None)) == "ace·sase"


def test_session_display_label_without_a_project() -> None:
    assert session_display_label(_identity(project=None)) == "ace"


def test_session_display_label_without_a_kind() -> None:
    assert session_display_label(_identity(kind="", project=None)) == "session"


# --- session_chip ---


def test_session_chip_for_a_live_identity() -> None:
    chip = session_chip(_identity())
    assert chip.plain == f"ace·sase#27 {short_session_handle(SESSION_A)}"
    assert chip.style == session_color(SESSION_A)


def test_session_chip_for_a_live_row() -> None:
    chip = session_chip(
        {"session_id": SESSION_A, "session_label": "ace·sase#27"},
        live_session_ids={SESSION_A},
    )
    assert chip.plain == f"ace·sase#27 {short_session_handle(SESSION_A)}"
    assert chip.style == session_color(SESSION_A)


def test_session_chip_for_a_dead_session_is_dim_and_marked() -> None:
    chip = session_chip(
        {"session_id": SESSION_A, "session_label": "ace·sase#27"},
        live_session_ids=set(),
    )
    assert chip.plain.endswith(f" {DEAD_SESSION_MARK}")
    assert chip.style == "dim"


def test_session_chip_for_an_unlabeled_row_is_just_the_handle() -> None:
    chip = session_chip({"session_id": SESSION_A})
    assert chip.plain == short_session_handle(SESSION_A)


def test_session_chip_for_an_absent_session() -> None:
    assert session_chip(None).plain == NO_SESSION_MARK
    assert session_chip({}).plain == NO_SESSION_MARK
    assert session_chip({"session_id": None}).plain == NO_SESSION_MARK
    assert session_chip(None).style == "dim"
