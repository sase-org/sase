"""One typed task-bead gate must show the same frozen chip on every surface.

Creates a real typed ``TaskTriage`` through ``create_gate`` and drives that one
notification through the toast, the notification row, the gate detail pane,
the review-modal loader, and the mobile bridge row. The glyph, label, and
colour come from stored ``action_data`` on every path: none of these
consumers may resolve a task type themselves.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from rich.console import Console, Group
from rich.text import Text

from sase.ace.tui.actions.agents._notification_custom_gate import (
    _load_custom_gate_modal_data,
)
from sase.ace.tui.actions.agents._toasts import _truncate, format_batch_toasts
from sase.ace.tui.modals.notification_modal import NotificationModal
from sase.bead._task_gate_spec import build_task_triage_gate_spec
from sase.bead.task_gate import TASK_TRIAGE_PREVIEW_PATH
from sase.integrations._mobile_notification_snapshot import _bridge_row
from sase.notification_gates.presentation import (
    GATE_CHIP_COLOR_ACTION_DATA_KEY,
    GATE_CHIP_GLYPH_ACTION_DATA_KEY,
    GATE_CHIP_LABEL_ACTION_DATA_KEY,
    GateChip,
    gate_chip_from_action_data,
)
from sase.notification_gates.service import create_gate
from sase.notification_gates.summary import load_gate_summary
from sase.notifications.store import load_notifications
from sase.task_types import registry as task_type_registry
from sase.task_types._models import TaskTypeRegistry


_REPO_ROOT = Path(__file__).resolve().parents[1]
_FLAKE_GLYPH = "≈"
_FLAKE_LABEL = "flake"
_FLAKE_COLOR = "#00D7D7"
_FLAKE_CHIP = GateChip(_FLAKE_GLYPH, _FLAKE_LABEL, _FLAKE_COLOR)
_TYPED_NOTE = (
    "Flaky test · Test node ID: tests/x.py::test_y · Evidence: 3/50 under -n 8"
)
_RENDER_SURFACES = (
    "src/sase/ace/tui/actions/agents/_toasts.py",
    "src/sase/ace/tui/modals/notification_modal_options.py",
    "src/sase/ace/tui/modals/notification_modal_gate.py",
    "src/sase/ace/tui/actions/agents/_notification_custom_gate.py",
    "src/sase/ace/tui/modals/custom_gate_modal.py",
    "src/sase/integrations/_mobile_notification_snapshot.py",
)
_FORBIDDEN_MODULES = (
    "sase.task_type_presentation",
    "sase.task_type_gate_presentation",
    "sase.task_types",
)


def _render_plain(renderable: object) -> str:
    console = Console(record=True, width=110, color_system=None)
    console.print(renderable)
    return console.export_text()


def _style_for(text: Text, fragment: str) -> str | None:
    for start, end, style in text.spans:
        if text.plain[start:end] == fragment:
            return str(style)
    return None


def _imported_modules(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            imported.append(node.module)
    return imported


def test_typed_task_bead_gate_chip_is_identical_on_every_surface(
    gate_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del gate_home
    spec = build_task_triage_gate_spec(
        request_id="typed-gate-surfaces",
        bead_id="sase-cx",
        project="sase",
        title="Flaky: test_x fails only under the parallel suite",
        description="Isolate the shared renderer state.",
        notes="Discovered while landing sase-cw.",
        created_by="claude_coder",
        created_at="2026-08-01T13:00:00Z",
        size="medium",
        refs=("research:202608/flaky-renderer.md",),
        task_type="flake",
        task_type_fields={
            "node_id": "tests/x.py::test_y",
            "evidence": "3/50 under -n 8",
        },
        producer={"agent": "bead_task_triage"},
    )
    result = create_gate(spec)
    [notification] = load_notifications()

    chip = gate_chip_from_action_data(notification.action_data)
    assert chip == _FLAKE_CHIP
    assert notification.action_data[GATE_CHIP_GLYPH_ACTION_DATA_KEY] == _FLAKE_GLYPH
    assert notification.action_data[GATE_CHIP_LABEL_ACTION_DATA_KEY] == _FLAKE_LABEL
    assert notification.action_data[GATE_CHIP_COLOR_ACTION_DATA_KEY] == _FLAKE_COLOR
    assert notification.notes[1] == _TYPED_NOTE

    # Empty the live catalog after freeze. A surface that re-resolves the
    # type would degrade to the unknown ``?`` chip instead of the stored one.
    empty_registry = TaskTypeRegistry(records=(), diagnostics=())
    monkeypatch.setattr(
        task_type_registry, "get_task_type_registry", lambda: empty_registry
    )
    monkeypatch.setattr(
        "sase.task_type_presentation.get_task_type_registry",
        lambda: empty_registry,
    )

    toasts = format_batch_toasts([notification])
    assert toasts == [
        (
            f"[bold {_FLAKE_COLOR}]{_FLAKE_GLYPH} {_FLAKE_LABEL}[/]  "
            f"{notification.notes[0]}\n"
            f"[dim]{_truncate(_TYPED_NOTE)}[/]",
            "warning",
        )
    ]

    modal = NotificationModal([notification])
    row = modal._create_styled_label(notification)
    assert f"{_FLAKE_GLYPH} " in row.plain
    assert _style_for(row, f"{_FLAKE_GLYPH} ") == f"bold {_FLAKE_COLOR}"
    assert "Flaky test" not in row.plain
    assert "Test node ID" not in row.plain

    modal._gate_summary_cache[notification.id] = ((), load_gate_summary(notification))
    pane = modal._render_gate_pane(notification)
    assert pane is not None
    _title, content = pane
    assert isinstance(content, Group)
    pane_text = _render_plain(content)
    assert f"{_FLAKE_GLYPH} {_FLAKE_LABEL}" in pane_text
    assert _TYPED_NOTE in pane_text
    chip_plain = _render_plain(content.renderables[2])
    assert f"{_FLAKE_GLYPH} {_FLAKE_LABEL}" in chip_plain

    data = _load_custom_gate_modal_data(notification)
    assert data.chip == _FLAKE_CHIP
    assert data.notes[1] == _TYPED_NOTE
    assert data.preview_text is not None
    assert "**Task type:** ≈ `flake`" in data.preview_text

    mobile = _bridge_row(notification)
    assert mobile.display_action_data[GATE_CHIP_GLYPH_ACTION_DATA_KEY] == _FLAKE_GLYPH
    assert mobile.display_action_data[GATE_CHIP_LABEL_ACTION_DATA_KEY] == _FLAKE_LABEL
    assert mobile.display_action_data[GATE_CHIP_COLOR_ACTION_DATA_KEY] == _FLAKE_COLOR
    assert mobile.host_action_data[GATE_CHIP_GLYPH_ACTION_DATA_KEY] == _FLAKE_GLYPH
    assert mobile.host_action_data[GATE_CHIP_LABEL_ACTION_DATA_KEY] == _FLAKE_LABEL
    assert mobile.host_action_data[GATE_CHIP_COLOR_ACTION_DATA_KEY] == _FLAKE_COLOR
    assert mobile.notes[1] == _TYPED_NOTE

    preview = (result.bundle_path / TASK_TRIAGE_PREVIEW_PATH).read_text(
        encoding="utf-8"
    )
    assert "**Task type:** ≈ `flake`" in preview
    assert preview.index("**Task type:**") < preview.index("## Description")


def test_typed_gate_render_surfaces_do_not_import_the_task_type_registry() -> None:
    """Render paths read ``action_data``; they must not consult the catalog."""
    offenders: list[str] = []
    for relative in _RENDER_SURFACES:
        path = _REPO_ROOT / relative
        for module in _imported_modules(path):
            if any(
                module == forbidden or module.startswith(f"{forbidden}.")
                for forbidden in _FORBIDDEN_MODULES
            ):
                offenders.append(f"{relative}:{module}")
    assert offenders == []
