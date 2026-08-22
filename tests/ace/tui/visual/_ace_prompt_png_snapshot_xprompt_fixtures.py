"""Xprompt assist entries and completion rows for ACE prompt PNG snapshots."""

from __future__ import annotations

import pytest

from sase.ace.tui import AceApp
from sase.ace.tui.widgets.file_completion import CompletionCandidate
from sase.ace.tui.widgets.xprompt_arg_assist import XPromptAssistEntry

_VISUAL_SKILL_ENTRIES = [
    XPromptAssistEntry(
        name="skill/sase_plan",
        skill_name="sase_plan",
        insertion="#skill/sase_plan",
        reference_prefix="#",
        kind="xprompt",
        input_signature=None,
        inputs=(),
        content_preview=None,
        description="Create an implementation plan",
        is_skill=True,
    )
]


def patch_visual_skill_catalog(monkeypatch: pytest.MonkeyPatch) -> None:
    def _entries(
        _app: AceApp,
        _project: str | None,
        *,
        schedule: bool = True,
    ) -> list[XPromptAssistEntry]:
        del schedule
        return _VISUAL_SKILL_ENTRIES

    def _exact_entries(
        _app: AceApp,
        _project: str | None,
    ) -> list[XPromptAssistEntry]:
        return _VISUAL_SKILL_ENTRIES

    monkeypatch.setattr(AceApp, "get_prompt_catalog_assist_entries", _entries)
    monkeypatch.setattr(
        AceApp,
        "get_warm_prompt_catalog_assist_entries_exact",
        _exact_entries,
    )


def _xprompt_candidate(
    name: str,
    *,
    kind: str,
    description: str,
) -> CompletionCandidate:
    return CompletionCandidate(
        display=f"#{name}",
        insertion=name,
        is_dir=False,
        name=name,
        metadata=XPromptAssistEntry(
            name=name,
            insertion=name,
            reference_prefix="#",
            kind=kind,
            input_signature=None,
            inputs=(),
            content_preview=None,
            description=description,
        ),
    )


XPROMPT_COMPLETION_ROWS = [
    _xprompt_candidate("fork", kind="part", description="Strip SASE lingo and fork"),
    _xprompt_candidate(
        "format", kind="workflow", description="Run the formatter across the diff"
    ),
    _xprompt_candidate(
        "followup", kind="part", description="Draft a follow-up review pass"
    ),
]


# Production `/sase_monitor` description: one logical row that exceeds the
# default snapshot width so the golden pins ellipsis, not wrap.
_LONG_SKILL_DESCRIPTION = (
    "Run a long command without blocking your turn. Use this INSTEAD of any "
    "built-in monitor, provider-native background-execution, or scheduled "
    "wake-up tool - those do not work in SASE, which runs agents for a single "
    "turn. Also use it to sleep/wait (for a CI job, a deploy, a rate limit) by "
    "monitoring a `sleep` command."
)


def _skill_candidate(name: str, *, description: str) -> CompletionCandidate:
    return CompletionCandidate(
        display=f"/{name}",
        insertion=f"/{name}",
        is_dir=False,
        name=name,
        metadata=XPromptAssistEntry(
            name=f"skill/{name}",
            insertion=f"#skill/{name}",
            reference_prefix="#",
            kind="xprompt",
            input_signature=None,
            inputs=(),
            content_preview=None,
            description=description,
            is_skill=True,
            skill_name=name,
        ),
    )


LONG_SKILL_COMPLETION_ROWS = [
    _skill_candidate("sase_monitor", description=_LONG_SKILL_DESCRIPTION),
    _skill_candidate("sase_plan", description="Create an implementation plan"),
    _skill_candidate("sase_questions", description="Ask the user questions"),
]
