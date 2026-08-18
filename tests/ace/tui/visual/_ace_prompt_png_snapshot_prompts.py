"""Prompt bodies used by the ACE prompt PNG visual snapshots."""

from __future__ import annotations

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
    "Compare @plan:202607/design.md @commit:sase@abcdef1 @user:handle\n"
    "Known references stay vivid while unknown-kind prose stays subdued."
)
GLOSSARY_HIGHLIGHT_PROMPT = (
    "Ask the Agent Clan to review the Patch glossary wiring\n"
    "Keep xprompt references, `Agent Clan`, and @plan:notes.md distinct."
)
GLOSSARY_WRAPPED_HIGHLIGHT_PROMPT = (
    "Ask the Agent\n"
    "  Clan to review the Patch glossary wiring\n"
    "Keep xprompt references and @plan:notes.md distinct."
)
REPO_MENTION_HIGHLIGHT_PROMPT = (
    "Ask the Agent Clan to inspect sase-core before the Patch handoff"
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
