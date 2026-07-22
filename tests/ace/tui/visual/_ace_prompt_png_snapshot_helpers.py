"""Shared fixtures for ACE prompt PNG visual snapshots."""

from __future__ import annotations

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui import AceApp
from sase.ace.tui.widgets.file_completion import CompletionCandidate
from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar
from sase.ace.tui.widgets.prompt_text_area import PromptTextArea
from sase.ace.tui.widgets.xprompt_arg_assist import XPromptAssistEntry
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

XPROMPT_HIGHLIGHT_SOLO = (
    "#gh:sase %auto #pr:my_change %m:opus fix the bug use /sase_plan\n"
    "```text\n#literal %wait:no\n---\n```"
)
XPROMPT_HIGHLIGHT_STACK = (
    "#gh:sase %auto #pr:my_change inspect the failure\n"
    "---\n"
    "%{%m:opus | %m:sonnet} #git:home summarize the fix use /sase_plan"
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

BULLET_HIGHLIGHT_SOLO = (
    "Release checklist for the prompt polish:\n"
    "- Draft the changelog and tag the #gh:sase milestone\n"
    "- Re-run the {% if flaky %}visual{% endif %} snapshots\n"
    "    - Confirm the committed gold renders match\n"
    "    - Capture the before and after screenshots\n"
    "- Keep inline dashes - like this - plainly uncolored\n"
    "Then hand off to the release owner."
)

TODO_RESTORED_PROMPT = (
    "# Release readiness draft\n"
    "\n"
    "TODO(release): confirm the rollback owner before the handoff\n"
    + "\n".join(
        f"Review note {index:02d}: preserve this restored drafting context."
        for index in range(1, 25)
    )
    + "\n\n"
    "## Remaining work\n"
    "- [ ] TODO: verify the migration against a clean workspace\n"
    "- [ ] TODO(ops): capture the final dashboard screenshot\n"
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
    "The cursor stays at the end while the title reports all three annotations."
)

_VISUAL_SKILL_ENTRIES = [
    XPromptAssistEntry(
        name="sase_plan",
        insertion="#sase_plan",
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
