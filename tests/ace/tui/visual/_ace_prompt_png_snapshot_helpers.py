"""Shared fixtures for ACE prompt PNG visual snapshots."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui import AceApp
from sase.ace.tui.glossary_catalog import PromptGlossaryContext
from sase.ace.tui.widgets.file_completion import CompletionCandidate
from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar
from sase.ace.tui.widgets.prompt_text_area import PromptTextArea
from sase.ace.tui.widgets.xprompt_arg_assist import XPromptAssistEntry
from sase.core.glossary_facade import GlossaryCatalog, GlossaryEntry
from sase.xprompt.glossary_catalog import (
    EditorGlossaryCatalog,
    EditorGlossaryProject,
    GlossaryConfigSignature,
)
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    wait_for_state,
    wait_for_visual_idle,
)

TWO_PANE_PROMPT = (
    "Investigate the failing CI on the beads branch and\n"
    "summarize the smallest reproducible case for the team"
    "\n---\n"
    "Refactor the workspace loader for clarity and harden\n"
    "the missing-checkout failure path so it is easy to scan"
)

# The two upper panes carry more than the inactive-pane row limit so they are
# visibly truncated while the active bottom pane keeps its full body.
COMPACT_PROMPT = (
    "Audit the overflow tag rendering across the table\n"
    "and keep the compact suffix aligned in every lane\n"
    "so nothing shifts when a long project tag wraps\n"
    "and the preview column stays put under pressure\n"
    "with one more line to push past the compact cap\n"
    "and a final line that should be clipped away"
    "\n---\n"
    "Refactor the workspace loader for clarity\n"
    "and make the missing-checkout failure easy to scan\n"
    "during a long debugging session on a slow host\n"
    "with extra context lines for the reviewer\n"
    "and yet another line beyond the compact cap\n"
    "and a trailing line that should be clipped"
    "\n---\n"
    "Draft the release notes for the prompt stack feature\n"
    "and link the before/after screenshots"
)

JINJA_VALID_PROMPT = (
    "Summarize {{ root | tojson }} for {% if root %}the release{% endif %}.\n"
    "{# keep this prompt scoped #}"
)
JINJA_INVALID_PROMPT = "Hello {{ missing }\nPlease fix before sending."

SEARCH_PROMPT = (
    "Draft alpha release notes for the prompt search polish\n"
    "Compare the alpha match highlight against the active cursor\n"
    "Ship the final alpha search behavior with clear wrap feedback"
)
CURSOR_PROMPT = "Readable cursor colors make vim modes obvious"

CURSOR_READOUT_SOLO_PROMPT = (
    "Confirm the readout tracks cursor motion across lines\n"
    "Move the caret here to check the mid-document line and column\n"
    "Then verify the relative gutter numbers surround this row\n"
    "Finish by scanning the final line for its own position"
)
CURSOR_READOUT_STACK_PROMPT = (
    "First pane parks near the start of its opening line\n"
    "with a second line for context here"
    "\n---\n"
    "Second pane parks further into its own second line\n"
    "so the two parked rules show different values"
    "\n---\n"
    "Third pane stays active at the end of its final line\n"
    "and reports its position on the bar border"
)

XPROMPT_HIGHLIGHT_SOLO = (
    "#gh:sase %auto #pr:my_change %m:opus fix the bug use /sase_plan\n"
    "```text\n#literal %wait:no\n---\n```"
)
XPROMPT_HIGHLIGHT_STACK = (
    "#gh:sase %auto #pr:my_change inspect the failure\n"
    "---\n"
    "%{%m:opus | %m:sonnet} #git:home summarize the fix use /sase_plan"
)
ARTIFACT_REF_HIGHLIGHT = (
    "Compare @plans:202607/design.md @commit:sase@abcdef1 @user:handle\n"
    "Known references stay vivid while unknown-kind prose stays subdued."
)
GLOSSARY_HIGHLIGHT_PROMPT = (
    "Ask the Agent Clan to review the ChangeSpec glossary wiring\n"
    "Keep xprompt references, `Agent Clan`, and @plans:notes.md distinct."
)

CODEBLOCK_HIGHLIGHT_SOLO = (
    "#gh:sase %auto inspect `foo`/`bar`; keep `/sase_gate` literal\n"
    "```\n"
    "plain text without a language still forms one card\n"
    "```\n"
    "Then verify the typed transform:\n"
    "```python\n"
    "def normalize(value: str) -> str:\n"
    "    # #literal and %wait:no stay inert here\n"
    "    return value.strip().lower()\n"
    "```"
)
CODEBLOCK_HIGHLIGHT_STACK = (
    "#gh:sase %auto review the `increment`/`result` Python transform\n"
    "```python\n"
    "def increment(value: int) -> int:\n"
    "    return value + 1\n"
    "```\n"
    "---\n"
    "%{%m:opus | %m:sonnet} #git:home verify the `src/*.py` path\n"
    "```bash\n"
    "for file in src/*.py; do\n"
    "  printf '%s\\n' \"$file\"\n"
    "done\n"
    "```"
)

MISSPELLING_HIGHLIGHT_PROMPT = (
    "Please recieve the attached report and confirm reciept\nbefore the meeting starts."
)

BULLET_HIGHLIGHT_SOLO = (
    "Release checklist for the prompt polish:\n"
    "- Draft the changelog and tag the #gh:sase milestone\n"
    "- Re-run the {% if flaky %}visual{% endif %} snapshots\n"
    "    - Confirm the committed gold renders match\n"
    "    - Capture the before and after screenshots\n"
    "- Keep inline dashes - like this - plainly uncolored\n"
    "Then hand off to the release owner."
)

ORDERED_HIGHLIGHT_SOLO = (
    "Release checklist for the prompt polish:\n"
    "1. Draft the changelog and tag the #gh:sase milestone\n"
    "2. Re-run the {% if flaky %}visual{% endif %} snapshots\n"
    "   1. Confirm the committed gold renders match\n"
    "   2. Capture the before and after screenshots\n"
    "3) Ship the release notes with a fresh delimiter\n"
    "Released in 2024. Keep that inline year plainly uncolored.\n"
    "Then hand off to the release owner."
)

TODO_RESTORED_PROMPT = (
    "# Release readiness draft\n"
    "\n"
    "TODO(release): confirm the rollback owner before the handoff\n"
    + "\n".join(
        f"Review note {index:02d}: preserve this restored drafting context."
        for index in range(1, 19)
    )
    + "\n\n"
    "## Remaining work\n"
    "- TODO: verify the migration and confirm reviewers have\n"
    "made updates.\n"
    "  Record the café rollout result for the release owner.\n"
    "- Keep this ordinary sibling bullet outside the highlighted note\n"
    "Keep `TODO: inline literal` rendered as code.\n"
    "```text\n"
    "TODO(owner): fenced literal\n"
    "```\n"
    'A quoted "TODO" leaves this prose ordinary; TODO: style only this note.\n'
    "Lowercase todo stays ordinary, then write the final summary here."
)
TODO_HIGHLIGHT_STACK = (
    "# Restored deployment checklist\n"
    "TODO(owner): confirm the inactive pane still counts\n"
    "Keep `TODO: literal validation` visible in the restored draft\n"
    "---\n"
    "# Active release note\n"
    "TODO: finish the customer-facing summary\n"
    "The cursor stays at the end while the title reports both annotations."
)

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

    monkeypatch.setattr(AceApp, "get_prompt_catalog_assist_entries", _entries)


def patch_visual_artifact_ref_kinds(monkeypatch: pytest.MonkeyPatch) -> None:
    from sase.ace.tui.widgets import _artifact_ref_highlight

    def _known(
        project: str | None,
        _workspace_dir: str | None,
        _workspace_num: int,
    ) -> _artifact_ref_highlight._KnownKindsResult:
        return _artifact_ref_highlight._KnownKindsResult(
            project,
            frozenset(
                {
                    "commit",
                    "chat",
                    "bug",
                    "file",
                    "bead",
                    "agent",
                    "plans",
                    "designs",
                }
            ),
        )

    monkeypatch.setattr(
        _artifact_ref_highlight,
        "_load_known_artifact_ref_kinds",
        _known,
    )


def patch_visual_glossary_catalog(monkeypatch: pytest.MonkeyPatch) -> None:
    catalog = _visual_glossary_catalog()

    def _catalog(
        _app: AceApp,
        _context: PromptGlossaryContext,
        *,
        schedule: bool = True,
    ) -> EditorGlossaryCatalog:
        del schedule
        return catalog

    def _warm(
        _app: AceApp,
        _context: PromptGlossaryContext,
    ) -> None:
        return None

    monkeypatch.setattr(AceApp, "get_prompt_glossary_catalog", _catalog)
    monkeypatch.setattr(
        AceApp,
        "is_prompt_glossary_catalog_warm",
        lambda _app, _context: True,
    )
    monkeypatch.setattr(AceApp, "warm_prompt_glossary_catalog", _warm)


class _VisualCompiledGlossary:
    def __init__(self, entries: tuple[GlossaryEntry, ...]) -> None:
        self._entries = entries

    def scan(self, text: str) -> list[dict[str, Any]]:
        spans: list[dict[str, Any]] = []
        for entry in self._entries:
            start = 0
            while True:
                found = text.find(entry.term, start)
                if found == -1:
                    break
                spans.append(
                    _visual_glossary_span_wire(
                        text,
                        entry,
                        found,
                        found + len(entry.term),
                    )
                )
                start = found + len(entry.term)
        return spans

    def lookup(
        self,
        text: str,
        line: int,
        character: int,
    ) -> dict[str, Any] | None:
        for span in self.scan(text):
            editor_range = span["range"]
            start = editor_range["start"]
            end = editor_range["end"]
            if (
                start["line"] <= line <= end["line"]
                and (line > start["line"] or character >= start["character"])
                and (line < end["line"] or character < end["character"])
            ):
                return span
        return None


def _visual_glossary_catalog() -> EditorGlossaryCatalog:
    config_path = Path("/workspace/sase/sase.yml")
    entries = (
        _visual_glossary_entry(
            index=0,
            term="Agent Clan",
            definition="Named group of collaborating agents.",
            config_path=config_path,
            line=8,
        ),
        _visual_glossary_entry(
            index=1,
            term="ChangeSpec",
            definition="SASE record for one CL or PR.",
            config_path=config_path,
            line=16,
        ),
        _visual_glossary_entry(
            index=2,
            term="xprompt",
            definition="Prompt shortcut expanded by SASE.",
            config_path=config_path,
            line=24,
        ),
    )
    return EditorGlossaryCatalog(
        schema_version=1,
        project=EditorGlossaryProject(
            key="sase",
            name="sase",
            aliases=("sase-org",),
            workspace_dir=Path("/workspace/sase"),
        ),
        config_path=config_path,
        config_signature=GlossaryConfigSignature(
            path=str(config_path),
            mtime_ns=1,
            size=2048,
        ),
        catalog=GlossaryCatalog(schema_version=1, entries=entries),
        compiled=_VisualCompiledGlossary(entries),
    )


def _visual_glossary_entry(
    *,
    index: int,
    term: str,
    definition: str,
    config_path: Path,
    line: int,
) -> GlossaryEntry:
    return GlossaryEntry(
        index=index,
        term=term,
        normalized_term=term.casefold(),
        definition=definition,
        configured_aliases=(),
        effective_aliases=(term.casefold(),),
        source={
            "config_path": str(config_path),
            "definition_range": {
                "start": {"line": line, "character": 4},
                "end": {"line": line, "character": 40},
            },
        },
    )


def _visual_glossary_span_wire(
    text: str,
    entry: GlossaryEntry,
    start: int,
    end: int,
) -> dict[str, Any]:
    return {
        "term": entry.term,
        "entry_index": entry.index,
        "alias_index": 0,
        "alias": entry.term,
        "matched_text": text[start:end],
        "byte_start": len(text[:start].encode("utf-8")),
        "byte_end": len(text[:end].encode("utf-8")),
        "range": {
            "start": _visual_editor_position(text, start),
            "end": _visual_editor_position(text, end),
        },
    }


def _visual_editor_position(text: str, offset: int) -> dict[str, int]:
    prefix = text[:offset]
    line = prefix.count("\n")
    line_start = prefix.rfind("\n") + 1
    return {
        "line": line,
        "character": sum(
            2 if ord(char) > 0xFFFF else 1 for char in text[line_start:offset]
        ),
    }


async def mount_prompt_bar(page: AcePage, initial_value: str) -> PromptInputBar:
    """Mount a prompt bar over the running app and wait for it to settle."""
    await page.app.mount(
        PromptInputBar(initial_value=initial_value, id="prompt-input-bar")
    )
    bar = page.app.query_one("#prompt-input-bar", PromptInputBar)
    await wait_for_state(
        page,
        lambda: bar.active_text_area().has_focus and len(bar._stack) > 0,
        description="mounted prompt stack and active-pane focus",
    )
    await wait_for_visual_idle(page)
    # A background refresh can move focus after the initial mount predicate
    # succeeds. Re-request it after the initial settling, prove cursor
    # visibility, then make convergence the final await so the PNG helper can
    # verify and rasterize that exact focused frame.
    text_area = bar.active_text_area()
    text_area.focus()
    await wait_for_state(
        page,
        lambda: text_area.has_focus and text_area._draw_cursor,
        description="focused prompt caret ready for snapshot capture",
    )
    # Recompute against the final cursor position. Under CI contention the
    # mount-time debounce can otherwise leave a stale suggestion that was
    # calculated while the cursor was still at the start of the prompt.
    text_area._on_prompt_completion_context_changed()
    await wait_for_visual_idle(page)
    return bar


def compute_jinja_now(text_area: PromptTextArea) -> None:
    text_area._jinja_diagnostics_generation += 1
    generation = text_area._jinja_diagnostics_generation
    text_area._fire_jinja_diagnostics_timer(
        generation,
        text_area.text,
        text_area._absolute_offset(text_area.cursor_location),
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
