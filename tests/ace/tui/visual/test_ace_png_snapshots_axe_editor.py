"""ACE TUI PNG visual snapshots for AXE add/edit modals."""

from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace
from typing import Any, cast

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.modals.axe_add_modals import (
    AxeAddChooserModal,
    AxeNewEntryIdentityModal,
    AxeScriptPickerModal,
)
from sase.ace.tui.modals.axe_entry_editor_modal import (
    AxeEntryEditorModal,
    AxeEntryEditorSeed,
    AxeEntryIdentity,
    AxeWritableScope,
)
from sase.ace.tui.modals.axe_entry_editor_rendering import _HOME
from sase.ace.tui.modals.config_transaction_preview import (
    ConfigTransactionPreview,
    TransactionDiagnostic,
    TransactionEffectivePreview,
)
from sase.ace.tui.widgets.single_line_vim_text_area import SingleLineVimTextArea
from sase.ace.tui.widgets.vim_text_area import VimTextArea
from sase.axe.chop_inventory import ChopInventory
from sase.vcs_log.models import LogRepo, RepoRemoteState, VcsLogResult
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patches,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_state,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual

# The editor abbreviates paths under ``_HOME`` (a ``$HOME`` snapshot the
# renderer takes at import time) to ``~``, so this scope path is built from that
# same value and renders as ``~/.config/sase/sase.yml`` on every host. A
# hard-coded ``/home/<user>`` literal would abbreviate only on the host that
# generated the goldens and render in full everywhere else.
_USER_SCOPE_PATH = f"{_HOME}/.config/sase/sase.yml"

_VISUAL_CHOP_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "script": {
            "type": "string",
            "minLength": 1,
            "description": "Executable command or path run by AXE.",
        },
        "description": {
            "type": "string",
            "description": "Human-facing summary shown in AXE listings.",
        },
        "enabled": {"type": "boolean", "default": True},
        "run_every": {
            "type": "string",
            "pattern": r"^\d+[smh]$",
            "description": "Optional cadence such as 5m or 1h.",
        },
        "timeout": {"type": "string", "pattern": r"^\d+[smh]$"},
        "env": {
            "type": "object",
            "description": "Environment passed to this chop.",
            "additionalProperties": True,
        },
        "inhibit_if": {"oneOf": [{"type": "array"}, {"type": "object"}]},
        "trigger": {"oneOf": [{"type": "string"}, {"type": "object"}]},
        "once_per": {"oneOf": [{"type": "string"}, {"type": "object"}]},
        "for_each": {
            "type": "array",
            "description": "Generate runtime instances from target rows.",
            "items": {"type": "object"},
        },
        "vars": {"type": "object", "additionalProperties": True},
    },
    "required": ["script"],
}

_VISUAL_LUMBERJACK_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "interval": {
            "type": "integer",
            "minimum": 1,
            "description": "Seconds between AXE polling cycles.",
        },
        "chop_timeout": {
            "type": "string",
            "description": "Default timeout applied to child chops.",
        },
        "env": {
            "type": "object",
            "description": "Environment inherited by every child chop.",
            "additionalProperties": True,
        },
    },
    "required": ["interval"],
}


def _patch_axe_editor_visual_loaders(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep modal background chrome independent of the live checkout."""
    import sase.ace.tui.widgets.artifacts.commits as commits_module

    patch_startup_loaders(monkeypatch)
    result = VcsLogResult(
        repos=(LogRepo("visual-project", "/workspace/visual", "primary"),),
        commits=(),
        warnings=(),
        remote_states=(
            RepoRemoteState(
                "visual-project",
                "origin/main",
                0,
                0,
                False,
                1.0,
            ),
        ),
    )
    monkeypatch.setattr(commits_module, "run_vcs_log", lambda **_kwargs: result)


def _visual_chop_inventory() -> ChopInventory:
    records = (
        SimpleNamespace(
            name="sase_chop_hook_checks",
            executable="/workspace/.venv/bin/sase_chop_hook_checks",
            source="python_bin",
            configured=True,
        ),
        SimpleNamespace(
            name="sase_chop_refresh_docs",
            executable="/workspace/.venv/bin/sase_chop_refresh_docs",
            source="configured_dir",
            configured=False,
        ),
        SimpleNamespace(
            name="sase_chop_error_digest",
            executable="/usr/local/bin/sase_chop_error_digest",
            source="path",
            configured=False,
        ),
    )
    return cast(
        ChopInventory,
        SimpleNamespace(
            configured_chops=(),
            available_scripts=records,
            chop_script_dirs=("/workspace/chops",),
            python_bin_dir="/workspace/.venv/bin",
            path_dirs=("/usr/local/bin",),
        ),
    )


def _visual_chop_editor_seed(
    *,
    running: bool = True,
    generated: bool = False,
    advanced: bool = False,
) -> AxeEntryEditorSeed:
    effective: dict[str, Any] = {
        "script": "sase_chop_hook_checks",
        "description": "Run blocking hook checks.",
        "enabled": True,
        "run_every": "5m",
    }
    raw: dict[str, Any] = {
        "script": "sase_chop_hook_checks",
        "description": "Run blocking hook checks.",
    }
    provenance: dict[str, str | tuple[str, ...]] = {
        "script": "user",
        "description": "overlay:project",
        "enabled": "default",
        "run_every": "user",
    }
    if advanced:
        advanced_values = {
            "env": {"SASE_AXE_MODE": "strict"},
            "for_each": [
                {"project": "sase", "query": "status:ready"},
                {"project": "docs", "query": "status:wip"},
            ],
            "vars": {"mentor": "security"},
        }
        effective.update(advanced_values)
        raw.update(advanced_values)
        provenance.update(dict.fromkeys(advanced_values, "overlay:project"))
    return AxeEntryEditorSeed(
        identity=AxeEntryIdentity(
            "chop",
            "hooks.main",
            "hook.checks",
            generated_instance="hook.checks[project=sase]" if generated else None,
        ),
        schema=_VISUAL_CHOP_SCHEMA,
        writable_scopes=(
            AxeWritableScope("user", _USER_SCOPE_PATH, "user"),
            AxeWritableScope(
                "overlay:project",
                "/workspace/sase/sase.yml",
                "overlay",
                list_strategy="concatenate",
            ),
        ),
        effective_values=effective,
        raw_values=raw,
        target_values=raw,
        inherited_values={"enabled": True, "timeout": "90s"},
        provenance=provenance,
        raw_values_by_scope={
            "user": {"script": "sase_chop_hook_checks", "run_every": "5m"},
            "overlay:project": raw,
        },
        generated_warning=(
            "Editing the base chop affects every generated instance."
            if generated
            else None
        ),
        running=running,
    )


def _visual_new_lumberjack_seed() -> AxeEntryEditorSeed:
    return AxeEntryEditorSeed(
        identity=AxeEntryIdentity("lumberjack", "nightly.docs"),
        schema=_VISUAL_LUMBERJACK_SCHEMA,
        writable_scopes=(
            AxeWritableScope(
                "project",
                "/workspace/sase/sase.yml",
                "project",
                exists=True,
                list_strategy="replace",
            ),
        ),
        effective_values={"interval": 60},
        raw_values={"interval": 60},
        new_entry=True,
        initial_touched=("interval",),
        running=False,
    )


def _visual_editor_preview() -> ConfigTransactionPreview:
    return ConfigTransactionPreview(
        target_path="/workspace/sase/sase.yml",
        effective=TransactionEffectivePreview(
            has_before=True,
            before={
                "script": "sase_chop_hook_checks",
                "description": "Run blocking hook checks.",
                "enabled": True,
            },
            has_after=True,
            after={
                "script": "sase_chop_hook_checks",
                "description": "Run blocking hook checks before PR handoff.",
                "enabled": True,
            },
            changed=True,
            label="Effective AXE entry",
        ),
        diagnostics=(
            TransactionDiagnostic(
                severity="warning",
                message="overlay keeps inherited timeout from default config",
                path="axe.lumberjacks.hooks.main.chops.hook.checks.timeout",
            ),
        ),
        warnings=("AXE is running; save & restart applies this immediately.",),
        text_diff=(
            "@@ -8,7 +8,7 @@\n"
            "       hook.checks:\n"
            "         script: sase_chop_hook_checks\n"
            "-        description: Run blocking hook checks.\n"
            "+        description: Run blocking hook checks before PR handoff.\n"
        ),
        valid=True,
    )


async def _push_visual_editor(
    page: AcePage,
    seed: AxeEntryEditorSeed,
) -> AxeEntryEditorModal:
    modal = AxeEntryEditorModal(
        seed,
        plan=lambda _request: _visual_editor_preview(),
        apply=lambda _plan: "written",
    )
    page.app.push_screen(modal)
    await page.expect_modal("AxeEntryEditorModal")
    await wait_for_state(
        page,
        lambda: bool(modal.query_one("#axe-editor-title").render().plain),
        description="AXE editor initialized through the real mount lifecycle",
    )
    await wait_for_visual_idle(page)
    return modal


async def test_axe_add_chooser_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The AXE add chooser prioritizes a contextual chop under the parent."""
    _patch_axe_editor_visual_loaders(monkeypatch)
    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        page.app.push_screen(AxeAddChooserModal("hooks.main"))
        await page.expect_modal("AxeAddChooserModal")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "axe_add_chooser_120x40",
            title="ACE axe add chooser",
        )


async def test_axe_script_picker_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Discovered installed chop scripts show source and configured metadata."""
    _patch_axe_editor_visual_loaders(monkeypatch)
    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        page.app.push_screen(AxeScriptPickerModal(_visual_chop_inventory()))
        await page.expect_modal("AxeScriptPickerModal")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "axe_script_picker_120x40",
            title="ACE axe discovered script picker",
        )


async def test_axe_new_lumberjack_identity_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The new-lumberjack identity form validates exact mapping keys."""
    _patch_axe_editor_visual_loaders(monkeypatch)
    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        page.app.push_screen(
            AxeNewEntryIdentityModal(
                kind="lumberjack",
                initial_name="nightly.docs",
                lumberjack_names=("hooks.main", "comments"),
            )
        )
        await page.expect_modal("AxeNewEntryIdentityModal")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "axe_new_lumberjack_identity_120x40",
            title="ACE axe new lumberjack identity",
        )


async def test_axe_chop_editor_basics_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Chop Basics state: scopes, provenance badges, and typed string field."""
    _patch_axe_editor_visual_loaders(monkeypatch)
    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await _push_visual_editor(page, _visual_chop_editor_seed())

        ace_png_visual.assert_page_png(
            page,
            "axe_chop_editor_basics_120x40",
            title="ACE axe chop editor basics",
        )


async def test_axe_chop_editor_advanced_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Chop Advanced state: raw-YAML compound fields remain reachable."""
    _patch_axe_editor_visual_loaders(monkeypatch)
    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        modal = await _push_visual_editor(page, _visual_chop_editor_seed(advanced=True))
        modal._active_name = "for_each"
        modal._render_all()
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "axe_chop_editor_advanced_120x40",
            title="ACE axe chop editor advanced",
        )


async def test_axe_generated_instance_warning_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Editing a generated runtime row clearly names the shared base edit."""
    _patch_axe_editor_visual_loaders(monkeypatch)
    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await _push_visual_editor(page, _visual_chop_editor_seed(generated=True))

        ace_png_visual.assert_page_png(
            page,
            "axe_generated_instance_warning_120x40",
            title="ACE axe generated instance warning",
        )


async def test_axe_editor_validation_failure_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Inline validation failures stay visible before preview."""
    _patch_axe_editor_visual_loaders(monkeypatch)
    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        modal = await _push_visual_editor(page, _visual_chop_editor_seed())
        modal._active_name = "run_every"
        modal._form = modal._form.set_text("run_every", "eventually", live=True)
        modal._render_all()
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "axe_editor_validation_failure_120x40",
            title="ACE axe editor validation failure",
        )


async def test_axe_editor_diff_preview_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Preview stage shows effective before/after, warnings, and file diff."""
    _patch_axe_editor_visual_loaders(monkeypatch)
    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        modal = await _push_visual_editor(page, _visual_chop_editor_seed())
        modal._active_name = "description"
        modal._render_all()
        modal.action_edit_field()
        await wait_for_state(
            page,
            lambda: len(modal.query(".axe-editor-cell-editor")) == 1,
            description="AXE in-row editor mounted",
        )
        editor = modal.query_one(".axe-editor-cell-editor", SingleLineVimTextArea)
        editor.text = "Run blocking hook checks before PR handoff."
        await wait_for_state(
            page,
            lambda: modal._form.field("description").touched,
            description="AXE editor draft touched",
        )
        modal.action_confirm()
        await wait_for_state(
            page,
            lambda: modal._stage == "preview" and modal._plan is not None,
            description="AXE editor preview plan",
        )
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "axe_editor_diff_preview_120x40",
            title="ACE axe editor diff preview",
        )


async def test_axe_editor_constrained_width_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The AXE editor collapses to the narrow layout on constrained terminals."""
    _patch_axe_editor_visual_loaders(monkeypatch)
    async with AcePage(query='"visual"', patches=patches(), size=(70, 36)) as page:
        await wait_for_startup(page)
        modal = await _push_visual_editor(page, _visual_new_lumberjack_seed())
        await wait_for_state(
            page,
            lambda: modal.has_class("-narrow"),
            description="AXE editor narrow layout",
        )
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "axe_editor_constrained_width_70x36",
            title="ACE axe editor constrained width",
        )


async def test_axe_editor_single_line_cell_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A scalar editor replaces only the active row's value cell."""
    _patch_axe_editor_visual_loaders(monkeypatch)
    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        modal = await _push_visual_editor(page, _visual_chop_editor_seed())
        modal._active_name = "description"
        modal._render_all()
        modal.action_edit_field()
        await wait_for_state(
            page,
            lambda: len(modal.query(".axe-editor-cell-editor")) == 1,
            description="AXE scalar cell editor",
        )
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "axe_editor_single_line_cell_120x40",
            title="ACE axe single-line property cell",
        )


async def test_axe_editor_multiline_yaml_cell_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A YAML property expands its row without moving the detail dock."""
    _patch_axe_editor_visual_loaders(monkeypatch)
    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        modal = await _push_visual_editor(
            page,
            _visual_chop_editor_seed(advanced=True),
        )
        modal._active_name = "env"
        modal._render_all()
        modal.action_edit_field()
        await wait_for_state(
            page,
            lambda: len(modal.query(".axe-editor-cell-editor")) == 1,
            description="AXE YAML cell editor",
        )
        editor = modal.query_one(".axe-editor-cell-editor", VimTextArea)
        editor.text = "SASE_AXE_MODE: strict\nSASE_AXE_TRACE: enabled\n"
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "axe_editor_multiline_yaml_cell_120x40",
            title="ACE axe multi-line YAML property cell",
        )


async def test_axe_editor_compact_lumberjack_sheet_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A three-property lumberjack sheet shrinks to its content."""
    _patch_axe_editor_visual_loaders(monkeypatch)
    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        seed = _visual_new_lumberjack_seed()
        seed = replace(seed, new_entry=False, initial_touched=())
        await _push_visual_editor(page, seed)

        ace_png_visual.assert_page_png(
            page,
            "axe_editor_compact_lumberjack_sheet_120x40",
            title="ACE axe compact lumberjack property sheet",
        )
