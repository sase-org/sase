---
create_time: 2026-05-11 19:09:41
status: done
prompt: sdd/prompts/202605/resume_finds_embedded_vcs_tag.md
---
# Plan — Resume xprompt picks up VCS workflow tag embedded anywhere in agent prompt

## Bug report

When copying the resume xprompt text for an agent (from Telegram or the TUI), if the agent's original prompt embeds a
VCS xprompt workflow tag (e.g. `#gh:sase`) anywhere other than the very start of the first line, the VCS tag is **not**
prepended to the copied resume text. The user has to remember the workspace and retype `#gh:sase` manually, which
defeats the convenience of the resume button.

Concrete reproduction scenarios where the bug triggers:

- Agent launched with `Please fix the failing test\n#gh:sase` (VCS tag on line 2).
- Agent launched with `tweak something #gh:sase quickly` (VCS tag mid-line).
- Agent launched with `#fast\n#gh:sase fix it` (tag after a non-`%directive` xprompt line — outside what
  `_DIRECTIVE_PREFIX_RE` skips).

In all three cases the resume text comes out as `#resume:<name>` with no `#gh:sase ` prefix, even though the agent ran
in that workspace.

## Root cause

`extract_vcs_workflow_tag()` in `src/sase/xprompt/_parsing.py:179` strips leading `%directive` tokens via
`_DIRECTIVE_PREFIX_RE` and then calls `_get_vcs_tag_pattern().match(stripped)`. The compiled pattern (built in
`src/sase/workspace_provider/_registry.py:100-103`) is:

```
^#(?:names)(?:!!|\?\?)?(?:\([^)]*\)|\+|[_:][^\s]*|)\s
```

Both `^` and `.match()` anchor the search at index 0 (after `%directive` stripping). Anything past the first
non-whitespace, non-`%directive` token is invisible to this function. The result: a VCS tag that lives anywhere else in
the prompt is silently dropped from the resume context.

The downstream resume callers all behave correctly given a non-`None` return — the bug is purely the position
restriction of the extractor.

## Affected callers and scope

VCS tag extraction is used in two categories of caller, and we need to be careful to only loosen the position constraint
where it is actually desired:

**Resume / display callers** (want to find the VCS tag wherever the user put it):

1. `src/sase/ace/tui/actions/agents/_wait_resume.py:32` `_resolve_vcs_tag()` — used by `action_resume_agent`,
   `_wait_for_single_agent`, and the bulk-wait helper. This drives both the `R` (resume) and `w` (wait) prompt-bar
   prefills in the TUI.
2. `sase-telegram/src/sase_telegram/formatting.py:564` — the Telegram bot's resume-button keyboard. (Sibling repo;
   handled in a follow-up CL.)

**Agent-startup / live-prompt callers** (want strict leading-tag semantics; **do not** change):

- `src/sase/axe/run_agent_runner_setup.py:127` — captures the leading VCS tag for the agent record.
- `src/sase/axe/run_agent_phases.py:442,450,473` — resolves `@name` refs inside the leading VCS tag.
- `src/sase/ace/tui/widgets/prompt_text_area.py:266,441` — live syntax/state of the prompt input bar.
- `src/sase/ace/tui/actions/agent_workflow/_prompt_bar_requests.py:160` — leading-tag detection when launching from the
  prompt bar.

These callers either strip the tag from the head of the prompt before passing the rest to the agent runtime, or provide
live visual feedback tied to the _first_ token; broadening their search to "anywhere" would risk picking up an
incidental `#gh:other` mention later in the prompt and silently switching workspaces.

## Approach

Add a new sibling extractor that scans the whole prompt and returns the first VCS workflow tag preceded by a safe
boundary (start of string, whitespace, or a `%directive` block). Wire the resume/display callers to it; leave
`extract_vcs_workflow_tag()` untouched so launch/strip semantics stay strict.

This keeps the change additive and reversible, and keeps the two semantically-different needs (strict leading vs.
find-anywhere) clearly named in the codebase.

### Function design

```python
def find_vcs_workflow_tag(prompt: str) -> str | None:
    """Find the first VCS workflow tag anywhere in *prompt*.

    Unlike :func:`extract_vcs_workflow_tag`, the tag does NOT need to be at
    the start of the prompt — it may appear on a later line or after some
    text on the first line, as long as it is preceded by a token boundary
    (start of string or whitespace).

    Use this for resume/display callers that want to recover the agent's
    workspace context from the original prompt regardless of where the user
    wrote the tag. Continue using :func:`extract_vcs_workflow_tag` when the
    tag must be the strict leading token (e.g. agent launch, where the tag
    is stripped from the prompt body).
    """
```

Implementation sketch:

- Build a "find anywhere" pattern by wrapping the names regex from `get_workflow_names()` with a leading boundary
  `(?:^|(?<=\s))` instead of `^`. Either expose a sibling `get_embedded_vcs_tag_pattern()` in
  `src/sase/workspace_provider/_registry.py`, or construct it inside `_parsing.py` from the existing names. I prefer
  adding a `get_embedded_vcs_tag_pattern()` next to `get_vcs_tag_pattern()` so the test patching surface mirrors the
  existing one.
- Use `.search()` and return the first match's `group(0)`. Trim/normalize the leading whitespace from the match so the
  returned tag (`"#gh:sase "`) matches the existing function's contract, which downstream code (e.g.
  `replace_ref_in_vcs_tag`) relies on.
- Keep `extract_vcs_workflow_tag` as the preferred path: in resume callers, try `extract_vcs_workflow_tag` first and
  fall back to `find_vcs_workflow_tag` only if the strict form returned `None`. This makes the behavior change purely
  additive — strict-leading prompts behave identically, embedded-tag prompts now succeed where they used to return
  `None`.

### Edits

1. `src/sase/workspace_provider/_registry.py` — add `get_embedded_vcs_tag_pattern()` returning the same alternation list
   with the leading-boundary tweak.
2. `src/sase/xprompt/_parsing.py` — add `find_vcs_workflow_tag(prompt)`, mirror lazy initialization of the new compiled
   pattern, export from `__all__`.
3. `src/sase/xprompt/__init__.py` — re-export `find_vcs_workflow_tag` so it's importable from `sase.xprompt`.
4. `src/sase/ace/tui/actions/agents/_wait_resume.py:_resolve_vcs_tag` — try `extract_vcs_workflow_tag` first, then
   `find_vcs_workflow_tag` on the same `raw_content`. Everything downstream (`replace_ref_in_vcs_tag`,
   `is_project_agent` branch, `#pr` `@name` rewrite) stays as-is.

### Out of scope for this change

- `sase-telegram/src/sase_telegram/formatting.py` lives in a sibling repo (`../sase-telegram`). Once
  `find_vcs_workflow_tag` is shipped in `sase.xprompt`, a follow-up CL there will replace the call site at
  `formatting.py:564` analogously. I will flag this as a follow-up in the commit description rather than touching the
  sibling repo from this CL.
- `src/sase/integrations/_mobile_agent_summary.py:mobile_agent_resume_options()` currently emits `#resume:<name>\n` with
  no VCS tag context at all. This is a related gap, but separate from the bug being reported — the Telegram bot derives
  its VCS prefix from the notification payload's `prompt` field, not from this endpoint. Leaving alone unless the user
  wants it folded in.

## Test plan

Add to `tests/test_xprompt_parsing.py`:

- `find_vcs_workflow_tag` returns the leading tag exactly like `extract_vcs_workflow_tag` for prompts that already pass
  today (`#gh:sase fix the bug`, `%plan\n#gh:sase fix the bug`, `%n:a #gh_sase Fix the bug`, etc.).
- `find_vcs_workflow_tag` returns the embedded tag for:
  - `Some intro\n#gh:sase fix the bug` (tag on line 2)
  - `tweak something #gh:sase quickly` (tag mid-line)
  - `#fast\n#gh:sase fix it` (tag after a non-`%directive` xprompt line)
- `find_vcs_workflow_tag` returns `None` for prompts with no VCS tag, and for prompts where the only `#gh:...`
  occurrence is glued to a non-whitespace prefix (e.g. `foo#gh:sase`) — i.e. the boundary requirement is respected.
- First-match-wins: `#gh:sase first\n#gh:other later` returns `#gh:sase `.

Add a focused test in `tests/ace/tui/` (e.g. extend `tests/ace/tui/test_resolve_vcs_tag.py`):

- `_resolve_vcs_tag` now returns the expected tag when the agent's raw prompt has the VCS tag on line 2 or embedded
  mid-line. Cover both the project-agent branch and the branch-name-substitution branch.

Add to `tests/test_mobile_agent_resume_options.py` (or a TUI integration test) only if we decide to extend the mobile
endpoint — not required for this CL.

After the CL lands in `sase`, mirror these tests in `sase-telegram` for the `formatting.py` call site.

## Risks and mitigation

- **Picking up an incidental tag in body text.** If a user writes `do NOT use #gh:other for this`, we will now treat
  `#gh:other ` as the workspace prefix on resume. This mirrors how the launch-time strict leading detector behaves today
  (any leading `#gh:other` is taken at face value), and resume is a user-confirmed action — the proposed text shows up
  in the prompt bar before submission and can be edited. Acceptable.
- **False positives from code fences / inline code.** The xprompt processor already strips code-fenced regions
  (`_markdown_code_ranges`) for some operations. The strict extractor does not do this, and neither does the proposed
  embedded extractor. Keeping parity here is fine — the resume use case operates on the user's raw prompt, not on
  rendered markdown.
- **Sibling repo lag.** Telegram users won't see the fix until `sase-telegram` is updated to call
  `find_vcs_workflow_tag`. The TUI is fixed immediately. Document the follow-up in the commit message.

## Acceptance check

After this CL:

- TUI: launch an agent with prompt `intro line\n#gh:sase fix it`, finish it, press `R` — the prompt bar should prefill
  `#gh:sase #resume:<name> ` rather than `#resume:<name> `.
- TUI: launch with `tweak #gh:sase here` — same outcome.
- Existing `extract_vcs_workflow_tag` tests all still pass; nothing in the agent launch path changes.
