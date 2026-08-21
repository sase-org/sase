"""Historical naming for commit-finalizer follow-up prompt artifacts.

Older releases wrote each LLM follow-up re-prompt to a
``commit_finalizer_pass_{N}_prompt.md`` file in the agent's artifacts dir.
Those files match the generic ``*_prompt.md`` glob the TUI uses to locate the
agent's *submitted* prompt, and (being written post-completion) are newer than
the original prompt — so they would hijack the AGENT PROMPT panel.

New runs do not write these files. This module remains the single source of
truth for the historical filename convention so display-selection readers
(``sase.agent.artifact_files_cache`` and ``sase.core.artifact_file_defaults``)
still skip archived follow-up prompts.
"""

from __future__ import annotations

import re

_FINALIZER_PASS_PROMPT_RE = re.compile(r"^commit_finalizer_pass_\d+_prompt\.md$")


def commit_finalizer_pass_prompt_filename(pass_number: int) -> str:
    """Return the artifact filename for a finalizer pass's follow-up prompt."""
    return f"commit_finalizer_pass_{pass_number}_prompt.md"


def is_commit_finalizer_followup_prompt(name: str) -> bool:
    """Return True for ``commit_finalizer_pass_{N}_prompt.md`` filenames.

    ``name`` is matched as a bare filename (no directory component). Used to
    exclude the finalizer's post-completion re-prompts from prompt-file
    selection so the panel shows the prompt actually submitted to the agent.
    """
    return _FINALIZER_PASS_PROMPT_RE.match(name) is not None
