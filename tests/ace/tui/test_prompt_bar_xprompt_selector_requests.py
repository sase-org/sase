"""Tests for the ``#@`` xprompt-selector request handling from the prompt bar.

Phase 1 makes the selector act on the exact pane that opened it: the
``SnippetRequested`` message carries the originating bar / text area / pane id /
trigger range, and the handler routes insertion through
``insert_snippet_at_target`` instead of re-querying the generic
``#prompt-input-bar`` after the modal closes.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from unittest.mock import patch

import pytest

from sase import project_aliases, project_display_names
from sase.ace.tui.actions.agent_workflow._prompt_bar_requests import (
    PromptBarRequestsMixin,
)
from sase.ace.tui.actions.agent_workflow._types import PromptContext
from sase.ace.tui.modals import XPromptSelectModal
from sase.ace.tui.modals.xprompt_select_modal import XPromptSelection
from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar
from sase.ace.tui.widgets.xprompt_inline_expansion import (
    _InlineExpansionReason,
    _InlineExpansionResult,
)
from sase.xprompt import loader_sources, project_identity
from sase.xprompt.models import InputArg, InputType
from sase.xprompt.workflow_models import Workflow, WorkflowStep
from tests.main.project_handler_helpers import (
    _disk_project_records,
    _write_project,
    projects_root,
)

__all__ = ["projects_root"]


def _ctx() -> PromptContext:
    return PromptContext(
        project_name="proj",
        cl_name="cl",
        project_file="/tmp/proj.sase",
        workspace_dir="/tmp/ws",
        workspace_num=1,
        workflow_name="ace(run)-ts",
        timestamp="ts",
        history_sort_key="branch",
        display_name="proj",
        update_target="",
        is_home_mode=False,
    )


class _StubTextArea:
    """Minimal origin text area exposing only the ``text`` the handler reads."""

    def __init__(self, text: str = "") -> None:
        self.text = text


class _OriginBar(PromptInputBar):
    """Real ``PromptInputBar`` (so the handler's ``isinstance`` guard accepts it).

    Only the methods the handler calls on the origin are overridden so the test
    can record the targeted insertion and simulate a stale target.
    """

    def __init__(self, *, inserted: bool = True) -> None:
        super().__init__()
        self._inserted = inserted
        self.insert_calls: list[tuple[object, str, object, str, object]] = []

    def insert_snippet_at_target(  # type: ignore[override]
        self,
        target_text_area: object,
        pane_id: str,
        trigger_range: object,
        snippet_name: str,
        entry: object = None,
    ) -> bool:
        self.insert_calls.append(
            (target_text_area, pane_id, trigger_range, snippet_name, entry)
        )
        return self._inserted


class _SelectorHarness(PromptBarRequestsMixin):
    """App stand-in capturing pushed modals and notifications."""

    def __init__(self) -> None:
        self._prompt_context: PromptContext | None = _ctx()
        self.pushed: list[tuple[object, object]] = []
        self.notifications: list[tuple[str, str | None]] = []

    def push_screen(self, modal: object, callback: object) -> None:
        self.pushed.append((modal, callback))

    def notify(self, message: str, severity: str | None = None) -> None:
        self.notifications.append((message, severity))


def _event(
    origin_bar: PromptInputBar,
    origin_text_area: object,
    *,
    pane_id: str = "prompt-input-g0-p0",
    trigger_range: tuple[tuple[int, int], tuple[int, int]] = ((0, 0), (0, 1)),
) -> PromptInputBar.SnippetRequested:
    return PromptInputBar.SnippetRequested(
        origin_bar=origin_bar,
        origin_text_area=origin_text_area,  # type: ignore[arg-type]
        origin_pane_id=pane_id,
        trigger_range=trigger_range,
    )


def test_pushes_selector_modal_with_context_project() -> None:
    harness = _SelectorHarness()
    origin_bar = _OriginBar()
    harness.on_prompt_input_bar_snippet_requested(_event(origin_bar, _StubTextArea()))

    modal, _callback = harness.pushed[0]
    assert isinstance(modal, XPromptSelectModal)


def test_selection_inserts_into_captured_origin_pane() -> None:
    harness = _SelectorHarness()
    origin_bar = _OriginBar(inserted=True)
    origin_ta = _StubTextArea(text="before #")

    harness.on_prompt_input_bar_snippet_requested(
        _event(origin_bar, origin_ta, trigger_range=((0, 7), (0, 8)))
    )
    _modal, callback = harness.pushed[0]
    callback(XPromptSelection(suffix="review"))

    # The captured origin pane is targeted directly (not a re-queried bar), with
    # the captured pane id and trigger range threaded straight through.
    assert origin_bar.insert_calls == [
        (origin_ta, "prompt-input-g0-p0", ((0, 7), (0, 8)), "review", None)
    ]
    assert harness.notifications == []


def test_selection_forwards_entry_for_smart_args() -> None:
    harness = _SelectorHarness()
    origin_bar = _OriginBar(inserted=True)
    origin_ta = _StubTextArea()
    sentinel_entry = object()

    harness.on_prompt_input_bar_snippet_requested(_event(origin_bar, origin_ta))
    _modal, callback = harness.pushed[0]
    callback(XPromptSelection(suffix="review", entry=sentinel_entry))  # type: ignore[arg-type]

    assert origin_bar.insert_calls[0][3] == "review"
    assert origin_bar.insert_calls[0][4] is sentinel_entry


def test_plain_string_result_inserts_suffix_without_entry() -> None:
    harness = _SelectorHarness()
    origin_bar = _OriginBar(inserted=True)
    origin_ta = _StubTextArea()

    harness.on_prompt_input_bar_snippet_requested(_event(origin_bar, origin_ta))
    _modal, callback = harness.pushed[0]
    callback("review")

    assert origin_bar.insert_calls == [
        (origin_ta, "prompt-input-g0-p0", ((0, 0), (0, 1)), "review", None)
    ]


def test_stale_target_notifies_and_leaves_prompt_unchanged() -> None:
    harness = _SelectorHarness()
    origin_bar = _OriginBar(inserted=False)  # origin pane gone before selection

    harness.on_prompt_input_bar_snippet_requested(_event(origin_bar, _StubTextArea()))
    _modal, callback = harness.pushed[0]
    callback(XPromptSelection(suffix="review"))

    assert len(origin_bar.insert_calls) == 1  # attempted exactly once
    assert harness.notifications == [
        ("Prompt pane is no longer available - selection discarded", "warning")
    ]


def test_cancel_does_not_insert_or_notify() -> None:
    harness = _SelectorHarness()
    origin_bar = _OriginBar()

    harness.on_prompt_input_bar_snippet_requested(_event(origin_bar, _StubTextArea()))
    _modal, callback = harness.pushed[0]
    callback(None)

    assert origin_bar.insert_calls == []
    assert harness.notifications == []


# -- Phase 4: ``Ctrl+I`` inline expansion is applied to the captured origin --


def _simple_workflow(name: str) -> Workflow:
    return Workflow(name=name, steps=[WorkflowStep(name="prompt", prompt_part="body")])


class _ExpandOriginBar(PromptInputBar):
    """Origin bar that records ``expand_xprompt_at_target`` calls.

    Overrides ``is_mounted`` so the handler's freshness guard passes without a
    running app, and records the captured target / pane id / trigger range /
    rendered body the handler threads through on a ``Ctrl+I`` expansion.
    """

    def __init__(self, *, applied: bool = True) -> None:
        super().__init__()
        self._applied = applied
        self.expand_calls: list[tuple[object, str, object, str]] = []
        self.merge_calls: list[list[InputArg]] = []

    @property
    def is_mounted(self) -> bool:  # type: ignore[override]
        return True

    def expand_xprompt_at_target(  # type: ignore[override]
        self,
        target_text_area: object,
        pane_id: str,
        trigger_range: object,
        expanded_text: str,
    ) -> bool:
        self.expand_calls.append(
            (target_text_area, pane_id, trigger_range, expanded_text)
        )
        return self._applied

    def merge_frontmatter_inputs(self, inputs: list[InputArg]) -> None:  # type: ignore[override]
        self.merge_calls.append(inputs)


def _expand_callback(
    harness: _SelectorHarness, name: str, workflow: Workflow
) -> str | None:
    """Invoke the ``Ctrl+I`` expand callback wired into the pushed modal."""
    modal, _select_callback = harness.pushed[0]
    assert isinstance(modal, XPromptSelectModal)
    return modal._expand_callback(name, workflow)  # type: ignore[misc]


def test_ctrl_i_expand_applies_rendered_body_to_origin_pane() -> None:
    harness = _SelectorHarness()
    origin_bar = _ExpandOriginBar(applied=True)
    origin_ta = _StubTextArea(text="before #")

    harness.on_prompt_input_bar_snippet_requested(
        _event(origin_bar, origin_ta, trigger_range=((0, 7), (0, 8)))
    )

    success = _InlineExpansionResult(
        expanded_text="BODY", error=None, reason=_InlineExpansionReason.EXPANDED
    )
    with patch(
        "sase.ace.tui.widgets.xprompt_inline_expansion.expand_inline_xprompt",
        return_value=success,
    ):
        error = _expand_callback(harness, "commit", _simple_workflow("commit"))

    # Success: the rendered body is applied to the captured origin pane (with
    # the captured pane id + trigger range), and the callback reports success.
    assert error is None
    assert origin_bar.expand_calls == [
        (origin_ta, "prompt-input-g0-p0", ((0, 7), (0, 8)), "BODY")
    ]
    assert origin_bar.merge_calls == []


def test_ctrl_i_expand_stages_returned_inputs_after_body_splice() -> None:
    harness = _SelectorHarness()
    origin_bar = _ExpandOriginBar(applied=True)
    origin_ta = _StubTextArea(text="before #")
    topic = InputArg(name="topic", type=InputType.LINE)

    harness.on_prompt_input_bar_snippet_requested(
        _event(origin_bar, origin_ta, trigger_range=((0, 7), (0, 8)))
    )

    success = _InlineExpansionResult(
        expanded_text="Read about {{ topic }}.",
        error=None,
        reason=_InlineExpansionReason.EXPANDED,
        inputs=[topic],
    )
    with patch(
        "sase.ace.tui.widgets.xprompt_inline_expansion.expand_inline_xprompt",
        return_value=success,
    ):
        error = _expand_callback(harness, "reads", _simple_workflow("reads"))

    assert error is None
    assert origin_bar.expand_calls == [
        (
            origin_ta,
            "prompt-input-g0-p0",
            ((0, 7), (0, 8)),
            "Read about {{ topic }}.",
        )
    ]
    assert origin_bar.merge_calls == [[topic]]


def test_ctrl_i_expand_error_does_not_touch_origin_pane() -> None:
    harness = _SelectorHarness()
    origin_bar = _ExpandOriginBar()
    origin_ta = _StubTextArea(text="#")

    harness.on_prompt_input_bar_snippet_requested(_event(origin_bar, origin_ta))

    failure = _InlineExpansionResult(
        expanded_text=None,
        error="Cannot inline-expand #!sync because it is a workflow.",
        reason=_InlineExpansionReason.STANDALONE_WORKFLOW,
    )
    with patch(
        "sase.ace.tui.widgets.xprompt_inline_expansion.expand_inline_xprompt",
        return_value=failure,
    ):
        error = _expand_callback(harness, "sync", _simple_workflow("sync"))

    # The helper's error is surfaced verbatim and nothing is applied, so the
    # user can fall back to inserting the ``#name`` reference with Enter.
    assert error == failure.error
    assert origin_bar.expand_calls == []


def test_ctrl_i_expand_stale_target_reports_recoverable_error() -> None:
    harness = _SelectorHarness()
    origin_bar = _ExpandOriginBar(applied=False)  # target went stale
    origin_ta = _StubTextArea(text="#")

    harness.on_prompt_input_bar_snippet_requested(_event(origin_bar, origin_ta))

    success = _InlineExpansionResult(
        expanded_text="BODY", error=None, reason=_InlineExpansionReason.EXPANDED
    )
    with patch(
        "sase.ace.tui.widgets.xprompt_inline_expansion.expand_inline_xprompt",
        return_value=success,
    ):
        error = _expand_callback(harness, "commit", _simple_workflow("commit"))

    # A stale target is attempted exactly once and reported as a recoverable
    # error (the modal keeps the selector open), leaving every prompt unchanged.
    assert error == "Prompt pane is no longer available - selection discarded"
    assert len(origin_bar.expand_calls) == 1
    assert origin_bar.merge_calls == []


# -- Phase 5: local frontmatter xprompts + project-catalog parity ------------

# A prompt that declares one local helper ``_rules`` through the property panel.
_RULES_FRONTMATTER = "---\nxprompts:\n  _rules: Be concise.\n---"


def test_frontmatter_local_appears_in_selector_catalog() -> None:
    harness = _SelectorHarness()
    origin_bar = _OriginBar()
    origin_bar._stack.frontmatter = _RULES_FRONTMATTER

    harness.on_prompt_input_bar_snippet_requested(
        _event(origin_bar, _StubTextArea(text="#"))
    )

    modal, _callback = harness.pushed[0]
    assert isinstance(modal, XPromptSelectModal)
    # The live frontmatter helper is merged into the selector catalog, so ``#@``
    # surfaces it as a selectable entry alongside global/project xprompts.
    assert "_rules" in modal._extra_prompts
    assert "_rules" in modal._prompts


def test_ctrl_i_expands_frontmatter_local_content() -> None:
    harness = _SelectorHarness()
    origin_bar = _ExpandOriginBar(applied=True)
    origin_bar._stack.frontmatter = _RULES_FRONTMATTER
    origin_ta = _StubTextArea(text="#")

    harness.on_prompt_input_bar_snippet_requested(_event(origin_bar, origin_ta))

    # Expand the local helper exactly as the modal would: with the projected
    # ``Workflow`` it merged into its catalog from the frontmatter.
    modal, _callback = harness.pushed[0]
    assert isinstance(modal, XPromptSelectModal)
    error = _expand_callback(harness, "_rules", modal._prompts["_rules"])

    assert error is None
    assert origin_bar.expand_calls
    assert origin_bar.expand_calls[0][3] == "Be concise."


def test_ctrl_i_global_reference_expands_recursively_from_frontmatter() -> None:
    harness = _SelectorHarness()
    origin_bar = _ExpandOriginBar(applied=True)
    origin_bar._stack.frontmatter = _RULES_FRONTMATTER
    origin_ta = _StubTextArea(text="#")

    harness.on_prompt_input_bar_snippet_requested(_event(origin_bar, origin_ta))

    # A global-style entry whose body references the frontmatter local ``#_rules``
    # resolves recursively against the live locals, matching launch behavior.
    workflow = Workflow(
        name="team",
        steps=[WorkflowStep(name="prompt", prompt_part="Team note:\n#_rules")],
    )
    error = _expand_callback(harness, "team", workflow)

    assert error is None
    assert origin_bar.expand_calls
    assert "Be concise." in origin_bar.expand_calls[0][3]


def test_ctrl_i_passes_frontmatter_locals_as_real_xprompts() -> None:
    harness = _SelectorHarness()
    origin_bar = _ExpandOriginBar(applied=True)
    origin_bar._stack.frontmatter = _RULES_FRONTMATTER
    origin_ta = _StubTextArea(text="#")

    harness.on_prompt_input_bar_snippet_requested(_event(origin_bar, origin_ta))

    captured: dict[str, object] = {}
    success = _InlineExpansionResult(
        expanded_text="BODY", error=None, reason=_InlineExpansionReason.EXPANDED
    )

    def _fake_expand(
        name: str,
        workflow: Workflow,
        *,
        local_xprompts: object = None,
        project: object = None,
    ) -> _InlineExpansionResult:
        captured["local_xprompts"] = local_xprompts
        return success

    with patch(
        "sase.ace.tui.widgets.xprompt_inline_expansion.expand_inline_xprompt",
        _fake_expand,
    ):
        error = _expand_callback(harness, "team", _simple_workflow("team"))

    assert error is None
    # The helper receives the frontmatter locals as real ``XPrompt`` objects,
    # not display-only ``Workflow`` projections.
    locals_passed = captured["local_xprompts"]
    assert isinstance(locals_passed, dict)
    assert set(locals_passed) == {"_rules"}
    assert locals_passed["_rules"].content == "Be concise."


def test_invalid_frontmatter_locals_are_omitted_without_crashing() -> None:
    harness = _SelectorHarness()
    origin_bar = _OriginBar()
    # A non-underscore local name violates the scoping rule; parsing raises and
    # the selector must omit the invalid local rather than tear down.
    origin_bar._stack.frontmatter = "---\nxprompts:\n  rules: Be concise.\n---"

    harness.on_prompt_input_bar_snippet_requested(
        _event(origin_bar, _StubTextArea(text="#"))
    )

    modal, _callback = harness.pushed[0]
    assert isinstance(modal, XPromptSelectModal)
    assert "rules" not in modal._extra_prompts
    assert harness.notifications == []


# -- sase-ac.6.2: the VCS-tag workspace lookup is canonical-name keyed --------


@pytest.fixture
def _identity_registry_reset() -> Iterator[None]:
    project_identity._identity_registry.cache_clear()
    project_identity._canonical_xprompt_project.cache_clear()
    yield
    project_identity._identity_registry.cache_clear()
    project_identity._canonical_xprompt_project.cache_clear()


@pytest.fixture
def _gh_project(
    projects_root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    _identity_registry_reset: None,
) -> Path:
    """Register ``gh_org__proj`` / ``PROJECT_NAME: proj`` with a ``sase.yml``."""
    workspace = tmp_path / "proj-ws"
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / "sase.yml").write_text(
        "xprompts:\n  thing: 'Thing body'\n", encoding="utf-8"
    )
    _write_project(
        projects_root,
        "gh_org__proj",
        f"WORKSPACE_DIR: {workspace}\nPROJECT_STATE: enabled\nPROJECT_NAME: proj\n",
    )
    monkeypatch.setattr(project_aliases, "list_project_records", _disk_project_records)
    monkeypatch.setattr(
        project_display_names, "list_project_records", _disk_project_records
    )
    monkeypatch.setattr(loader_sources, "list_project_records", _disk_project_records)
    return workspace


def test_vcs_tag_offers_project_local_xprompts_by_canonical_name(
    _gh_project: Path,
) -> None:
    harness = _SelectorHarness()
    origin_bar = _OriginBar()

    # The tag names the project by its user-facing ``PROJECT_NAME``, while the
    # ProjectSpec directory key is ``gh_org__proj``. Keying the workspace lookup
    # by the directory key silently drops the project's ``sase.yml`` xprompts.
    harness.on_prompt_input_bar_snippet_requested(
        _event(origin_bar, _StubTextArea(text="#git:proj do the thing #"))
    )

    modal, _callback = harness.pushed[0]
    assert isinstance(modal, XPromptSelectModal)
    assert "proj/thing" in modal._extra_prompts
    assert "proj/thing" in modal._prompts


def test_vcs_tag_directory_key_spelling_also_resolves(_gh_project: Path) -> None:
    harness = _SelectorHarness()
    origin_bar = _OriginBar()

    harness.on_prompt_input_bar_snippet_requested(
        _event(origin_bar, _StubTextArea(text="#git:gh_org__proj do the thing #"))
    )

    modal, _callback = harness.pushed[0]
    assert isinstance(modal, XPromptSelectModal)
    # Canonicalization also normalizes the directory-key spelling, so the entry
    # is namespaced under the canonical name either way.
    assert "proj/thing" in modal._extra_prompts
    assert "gh_org__proj/thing" not in modal._extra_prompts
