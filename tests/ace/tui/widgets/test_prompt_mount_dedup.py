"""Mount-dedup coverage: each prompt hook body runs once, in order."""

from __future__ import annotations

from typing import Any
from unittest.mock import Mock

from textual.worker import WorkerState

from sase.ace.tui.widgets._line_rendering import LineRenderingMixin
from sase.ace.tui.widgets.prompt_text_area import PromptTextArea

from ._completion_helpers import CompletionTestApp

_MOUNT_HOOK = "_prompt_mount_hook"
_UNMOUNT_HOOK = "_prompt_unmount_hook"

#: Every class in the prompt text-area MRO that owns a mount-hook body, in
#: the base-first order those bodies run (deepest base first, most-derived
#: mixin last). This is the inventory the mount-dedup phase verified: adding
#: a hook body means updating this list deliberately.
_EXPECTED_MOUNT_HOOK_ORDER = [
    "LineRenderingMixin",
    "FileCompletionDirectiveInventoryWorkerMixin",
    "JinjaHighlightMixin",
    "MisspellingHighlightMixin",
    "PromptRepoMentionMixin",
    "PromptGlossaryMixin",
    "PlaceholderHighlightMixin",
    "CodeBlockHighlightMixin",
    "BulletHighlightMixin",
    "XPromptSyntaxHighlightMixin",
    "ArtifactRefHighlightMixin",
    "AltSyntaxHighlightMixin",
    "TodoHighlightMixin",
    "SearchHighlightMixin",
    "YankHighlightMixin",
]

#: Classes owning an unmount-hook body, most-derived first (invocation order).
_EXPECTED_UNMOUNT_HOOK_ORDER = [
    "ArtifactRefSyncMixin",
    "PromptSoftCompletionMixin",
    "LineRenderingMixin",
]


def _hook_definers(attr: str) -> list[type]:
    return [cls for cls in PromptTextArea.__mro__ if attr in cls.__dict__]


def test_mount_hook_inventory_matches_mro() -> None:
    """The hook inventory is exactly the MRO's hook definers, base-first."""
    definers = _hook_definers(_MOUNT_HOOK)
    assert [cls.__name__ for cls in definers] == list(
        reversed(_EXPECTED_MOUNT_HOOK_ORDER)
    )
    base_first = [cls.__name__ for cls in reversed(definers)]
    assert base_first == _EXPECTED_MOUNT_HOOK_ORDER


def test_unmount_hook_inventory() -> None:
    """Both unmount bodies plus the shared-base terminator exist."""
    definers = _hook_definers(_UNMOUNT_HOOK)
    assert [cls.__name__ for cls in definers] == _EXPECTED_UNMOUNT_HOOK_ORDER


def test_single_dispatch_surface() -> None:
    """Textual dispatches each prompt handler exactly once per MRO."""
    assert [
        cls.__name__ for cls in PromptTextArea.__mro__ if "on_mount" in cls.__dict__
    ] == ["LineRenderingMixin", "ScrollView"]
    assert [
        cls.__name__ for cls in PromptTextArea.__mro__ if "on_unmount" in cls.__dict__
    ] == ["LineRenderingMixin"]
    assert [
        cls.__name__
        for cls in PromptTextArea.__mro__
        if "on_worker_state_changed" in cls.__dict__
    ] == ["LineRenderingMixin"]


def test_panel_worker_single_dispatch_surface() -> None:
    """The agent prompt panel keeps one worker dispatcher for two hook bodies."""
    from sase.ace.tui.widgets.prompt_panel import AgentPromptPanel

    assert [
        cls.__name__
        for cls in AgentPromptPanel.__mro__
        if "on_worker_state_changed" in cls.__dict__
    ] == ["AgentDisplayWorkerMixin"]


async def test_mount_bodies_run_once_in_base_first_order() -> None:
    """Each mount body runs exactly once per mount, base-first."""
    counts: dict[str, int] = {}
    order: list[str] = []
    originals: dict[str, Any] = {}
    for cls in _hook_definers(_MOUNT_HOOK):
        if cls is LineRenderingMixin:
            continue
        originals[cls.__name__] = cls.__dict__[_MOUNT_HOOK]

        def _wrapper(self: Any, _cls: type = cls) -> None:
            counts[_cls.__name__] = counts.get(_cls.__name__, 0) + 1
            originals[_cls.__name__](self)
            # Bodies run after their super-chain returns, so completion
            # order is the base-first body order of the old first chain.
            order.append(_cls.__name__)

        setattr(cls, _MOUNT_HOOK, _wrapper)
    try:
        app = CompletionTestApp()
        async with app.run_test():
            text_area = app.query_one(PromptTextArea)
            assert text_area.is_mounted
    finally:
        for cls in _hook_definers(_MOUNT_HOOK):
            if cls is LineRenderingMixin:
                continue
            setattr(cls, _MOUNT_HOOK, originals[cls.__name__])

    assert order == [
        name for name in _EXPECTED_MOUNT_HOOK_ORDER if name != "LineRenderingMixin"
    ]
    assert set(counts) == set(order)
    assert all(count == 1 for count in counts.values())


async def test_unmount_bodies_run_once() -> None:
    """Each unmount body runs exactly once per unmount."""
    from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar

    counts: dict[str, int] = {}
    originals: dict[str, Any] = {}
    for cls in _hook_definers(_UNMOUNT_HOOK):
        if cls is LineRenderingMixin:
            continue
        originals[cls.__name__] = cls.__dict__[_UNMOUNT_HOOK]

        def _wrapper(self: Any, _cls: type = cls) -> None:
            counts[_cls.__name__] = counts.get(_cls.__name__, 0) + 1
            originals[_cls.__name__](self)

        setattr(cls, _UNMOUNT_HOOK, _wrapper)
    try:
        app = CompletionTestApp()
        async with app.run_test():
            bar = app.query_one(PromptInputBar)
            await bar.remove()
    finally:
        for cls in _hook_definers(_UNMOUNT_HOOK):
            if cls is LineRenderingMixin:
                continue
            setattr(cls, _UNMOUNT_HOOK, originals[cls.__name__])

    assert counts == {
        "ArtifactRefSyncMixin": 1,
        "PromptSoftCompletionMixin": 1,
    }


async def test_theme_parity_after_mount() -> None:
    """Mount registers the same text-area theme and syntax styles as before."""
    app = CompletionTestApp()
    async with app.run_test():
        text_area = app.query_one(PromptTextArea)
        assert text_area.theme == "sase-jinja-prompt"
        assert sorted(text_area._theme.syntax_styles) == sorted(_EXPECTED_SYNTAX_STYLES)


async def test_worker_success_applies_inventory_once() -> None:
    """One worker event through the dispatcher applies inventory once."""
    from sase.ace.tui.widgets._file_completion_workers import (
        PromptCommitInventoryWorkerResult,
    )

    app = CompletionTestApp()
    async with app.run_test():
        text_area = app.query_one(PromptTextArea)
        worker_name = "prompt-commit-inventory:sase"
        text_area._prompt_commit_worker_projects[worker_name] = "sase"
        text_area._prompt_commit_inflight.add("sase")
        from types import SimpleNamespace

        worker = SimpleNamespace(
            group="prompt-commit-inventory",
            name=worker_name,
            result=Mock(spec=PromptCommitInventoryWorkerResult),
        )
        event = SimpleNamespace(worker=worker, state=WorkerState.SUCCESS)

        applied: list[object] = []
        original = PromptTextArea._apply_prompt_commit_inventory_result
        try:
            PromptTextArea._apply_prompt_commit_inventory_result = (  # type: ignore[method-assign]
                lambda self, result: applied.append(result)
            )
            # Simulate Textual's MRO dispatch: invoke every dispatched
            # handler the framework would call for this event.
            for cls in PromptTextArea.__mro__:
                handler = cls.__dict__.get("on_worker_state_changed")
                if handler is not None:
                    handler(text_area, event)
        finally:
            PromptTextArea._apply_prompt_commit_inventory_result = original  # type: ignore[method-assign]

        assert len(applied) == 1
        assert worker_name not in text_area._prompt_commit_worker_projects


async def test_unknown_worker_group_is_ignored() -> None:
    """Worker events for foreign groups fall through without side effects."""
    app = CompletionTestApp()
    async with app.run_test():
        text_area = app.query_one(PromptTextArea)
        from types import SimpleNamespace

        worker = SimpleNamespace(
            group="some-foreign-group", name="foreign", result=None
        )
        event = SimpleNamespace(worker=worker, state=WorkerState.SUCCESS)
        text_area.on_worker_state_changed(event)


_EXPECTED_SYNTAX_STYLES = [
    "alt.branch_name",
    "alt.delimiter",
    "alt.error",
    "alt.separator",
    "artifact_ref.delimiter",
    "artifact_ref.error",
    "artifact_ref.fragment",
    "artifact_ref.kind",
    "artifact_ref.neutral",
    "artifact_ref.payload",
    "artifact_ref.separator",
    "artifact_ref.sigil",
    "artifact_ref.unknown",
    "bold",
    "boolean",
    "bullet.dash",
    "bullet.ordered",
    "class",
    "codeblock.content",
    "codeblock.delimiter",
    "codeblock.fence",
    "codeblock.inline",
    "codeblock.lang",
    "comment",
    "conditional",
    "constant.builtin",
    "constructor",
    "css.property",
    "exception",
    "float",
    "function",
    "function.call",
    "glossary.term",
    "heading",
    "heading.marker",
    "include",
    "info_string",
    "inline_code",
    "italic",
    "jinja.comment",
    "jinja.delimiter",
    "jinja.error",
    "jinja.filter",
    "jinja.keyword",
    "jinja.match",
    "jinja.operator",
    "jinja.statement",
    "jinja.unknown",
    "jinja.variable",
    "json.label",
    "json.null",
    "keyword",
    "keyword.function",
    "keyword.operator",
    "keyword.return",
    "link.label",
    "link.uri",
    "list.marker",
    "method",
    "method.call",
    "number",
    "operator",
    "placeholder.delimiter",
    "placeholder.inner",
    "project_tag.name.0",
    "project_tag.name.1",
    "project_tag.name.10",
    "project_tag.name.11",
    "project_tag.name.12",
    "project_tag.name.13",
    "project_tag.name.14",
    "project_tag.name.15",
    "project_tag.name.16",
    "project_tag.name.17",
    "project_tag.name.2",
    "project_tag.name.3",
    "project_tag.name.4",
    "project_tag.name.5",
    "project_tag.name.6",
    "project_tag.name.7",
    "project_tag.name.8",
    "project_tag.name.9",
    "project_tag.name.neutral",
    "project_tag.sigil.0",
    "project_tag.sigil.1",
    "project_tag.sigil.10",
    "project_tag.sigil.11",
    "project_tag.sigil.12",
    "project_tag.sigil.13",
    "project_tag.sigil.14",
    "project_tag.sigil.15",
    "project_tag.sigil.16",
    "project_tag.sigil.17",
    "project_tag.sigil.2",
    "project_tag.sigil.3",
    "project_tag.sigil.4",
    "project_tag.sigil.5",
    "project_tag.sigil.6",
    "project_tag.sigil.7",
    "project_tag.sigil.8",
    "project_tag.sigil.9",
    "project_tag.sigil.neutral",
    "project_tag.unknown",
    "punctuation.bracket",
    "punctuation.delimiter",
    "punctuation.special",
    "repeat",
    "repo.mention",
    "search.current",
    "search.match",
    "search.operator.destructive",
    "search.operator.transform",
    "search.operator.yank",
    "spell.misspelled",
    "strikethrough",
    "string",
    "string.documentation",
    "tag",
    "todo.body",
    "todo.header",
    "toml.datetime",
    "toml.type",
    "type",
    "type.builtin",
    "type.class",
    "xprompt.arg_assign",
    "xprompt.arg_assign.invalid",
    "xprompt.arg_delimiter",
    "xprompt.arg_delimiter.invalid",
    "xprompt.arg_key",
    "xprompt.arg_key.invalid",
    "xprompt.arg_value",
    "xprompt.arg_value.invalid",
    "xprompt.arg_value_bool",
    "xprompt.arg_value_bool.invalid",
    "xprompt.arg_value_number",
    "xprompt.arg_value_number.invalid",
    "xprompt.arg_value_string",
    "xprompt.arg_value_string.invalid",
    "xprompt.directive",
    "xprompt.directive.arg_assign",
    "xprompt.directive.arg_assign.invalid",
    "xprompt.directive.arg_delimiter",
    "xprompt.directive.arg_delimiter.invalid",
    "xprompt.directive.arg_key",
    "xprompt.directive.arg_key.invalid",
    "xprompt.directive.arg_value",
    "xprompt.directive.arg_value.invalid",
    "xprompt.directive.arg_value_bool",
    "xprompt.directive.arg_value_bool.invalid",
    "xprompt.directive.arg_value_number",
    "xprompt.directive.arg_value_number.invalid",
    "xprompt.directive.arg_value_string",
    "xprompt.directive.arg_value_string.invalid",
    "xprompt.directive_arg",
    "xprompt.invocation",
    "xprompt.invocation_arg",
    "xprompt.separator",
    "xprompt.skill",
    "yaml.field",
    "yank.flash",
]
