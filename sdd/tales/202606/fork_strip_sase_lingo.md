---
create_time: 2026-06-03 02:41:46
status: done
prompt: sdd/prompts/202606/fork_strip_sase_lingo.md
---
# Plan: Strip sase-specific lingo from `#fork` previous-conversation history

## Problem

The `#fork` / `#fork_by_chat` xprompt workflows inject a `# Previous Conversation` block into a new agent's prompt so it
can resume a prior conversation. Today that block reproduces the prior **user prompts verbatim**, including a lot of
sase-internal control syntax that a fresh agent has no way to understand.

From the `~/tmp/sase_snapshot.txt` example, a single forked turn's `**User:**` block contains:

```
%name:research_swarm.final-@ %wait:research_swarm.cdx-32 %wait:research_swarm.cld-32 %g:research

#git:home The two independent research agents have finished. ...

{{ wait_chats }}

Read both chat transcripts first. ...
```

The noise falls into three categories of sase-specific lingo:

1. **`%`-directives** — `%name`, `%wait`, `%group`/`%g`, `%model`, `%approve`, `%plan`, `%epic`, `%hide`, `%time`,
   `%repeat`, `%edit`, plus the `%xprompts_enabled:false/true` region markers.
2. **`#` / `#!` xprompt & workspace references** (left _unexpanded_ inside the disabled region) — `#git:home`,
   `#research`, `#epic`, `#plan`, `#fork:...`, etc.
3. **Unrendered Jinja2 markers** — e.g. `{{ wait_chats }}` (literal because the source xprompt wrapped it in
   `{% raw %}`), plus stray `{% ... %}` / `{# ... #}`.

We cannot assume sase agents know anything about this syntax. The forked agent should see a clean, natural-language
transcript of what the user asked and what the assistant answered.

## Root cause

Chat transcripts store the **raw, pre-expansion user prompt** (`state.current_prompt` → `save_chat_history`). `#fork`
resolves the transcript and calls `sase.history.chat.load_chat_for_resume()`, which parses the stored `## Prompt` /
`## Response` turns and reformats them as flat `**User:**` / `**Assistant:**` text. The user side is emitted exactly as
stored — directives, refs, and Jinja markers included.

These tokens are _not_ re-interpreted by the new agent (the `fork.yml` `inject` step wraps the block in
`%xprompts_enabled:false ... %xprompts_enabled:true`, and `extract_prompt_directives` protects disabled regions, so no
name-hijack/expansion happens). The problem is therefore purely **presentational**: the forked agent is shown confusing
sase jargon, not that the jargon does anything. The fix is to sanitize the user-prompt text the resume path emits.

## Design

Sanitize the **user-prompt portion of each turn** at the single chokepoint where resume history is built:
`load_chat_for_resume()` in `src/sase/history/chat.py`. Assistant responses are left untouched (they are already
natural-language model output).

Cleaning at _load time_ (not save time) is deliberate:

- Raw transcripts stay intact for human inspection via `sase chats show` and for debugging.
- Forked agents — and the `## Previous Conversation` that a fork agent later persists in its own transcript (since
  `save_chat_history(previous_history=...)` is fed from this function) — get the clean text automatically.
- Recursive forks (fork-of-a-fork) converge: nested turns come back already sanitized, and the sanitizer is idempotent,
  so re-running it on clean text is a no-op.

### What gets stripped (fence-protected, in order)

Add a private helper, e.g. `_sanitize_resume_prompt(prompt: str) -> str`, composed from existing primitives so we do not
reinvent parsing:

1. **Protect fenced code blocks** (`protect_fenced_blocks` / `unprotect_fenced_blocks`) up front so that `%`, `#`, or
   `{{ }}` appearing inside example code in the prior conversation is preserved.
2. **Strip `%`-directives**: remove all known-directive spans (`_KNOWN_DIRECTIVES` + `_DIRECTIVE_ALIASES` from
   `xprompt._directive_types`, matched via `_DIRECTIVE_PATTERN`, handling colon/backtick/paren/plus arg forms) and the
   `%xprompts_enabled:false/true` markers (`strip_disabled_region_markers`).
   - Use a dedicated, **side-effect-free** stripper rather than `extract_prompt_directives`, because the latter
     allocates auto-names (`get_next_auto_name`) and raises `DirectiveError` on duplicate directives — neither is
     appropriate when cleaning historical text. Plan to add a small pure `strip_known_directives(prompt)` helper in
     `src/sase/xprompt/directives.py` (it owns the directive regex/known-set) and reuse it here.
3. **Strip `#` / `#!` references**: use `iter_xprompt_references()` (from `xprompt._parsing_references`) to find every
   reference span and delete it. This covers workspace refs (`#git:home`), inline xprompts (`#research`, `#epic`,
   `#plan`), and `#fork:...`. Markdown headings (`# Heading`, space after `#`) are not matched by the reference pattern,
   so real prose headings survive. This also subsumes the function's current ad-hoc fork/resume-ref removal.
4. **Strip unrendered Jinja markers**: remove `{{ ... }}`, `{% ... %}`, and `{# ... #}` spans.
5. **Tidy whitespace**: collapse the 3+ blank lines / dangling spaces left behind into a clean single
   blank-line-separated body; trim leading/trailing whitespace.

### Integration points in `load_chat_for_resume`

- Keep `_find_resume_refs(prompt)` driving the recursive expansion of nested fork/resume references (that logic must
  stay — it controls which transcripts get inlined).
- Apply `_sanitize_resume_prompt` to the `prompt` side when formatting the final `**User:** ... **Assistant:** ...`
  parts (the single output chokepoint). Nested turns already sanitized in the recursive call pass through idempotently.
- The manual `prompt = prompt.replace(full_match, "")` ref-stripping becomes redundant once reference stripping lives in
  the sanitizer; remove or retain harmlessly (sanitizer is idempotent).

### Import hygiene

`sase.history.chat` does not currently import `sase.xprompt`. To avoid any import-cycle risk, pull the xprompt
primitives via **lazy imports inside the helper** (matching the existing lazy import of `resolve_resume_agent_name`).

## Files to change

- `src/sase/history/chat.py` — add `_sanitize_resume_prompt`; call it in `load_chat_for_resume`.
- `src/sase/xprompt/directives.py` (+ possibly `_directive_types.py`) — add a pure `strip_known_directives()` helper
  exposing side-effect-free directive removal.
- `docs/xprompt.md` — short note under the `#fork` / `#fork_by_chat` entries that the injected previous conversation is
  sanitized of sase directives, references, and unrendered template markers.

## Testing

Add focused unit tests (alongside `tests/history/test_chat_resume.py` / `test_chat_resume_refs.py`):

- A stored prompt containing `%name/%wait/%group`, `#git:home`, `#research`, and `{{ wait_chats }}` resolves through
  `load_chat_for_resume` to a `**User:**` block with all of those removed and only the natural-language instructions
  remaining.
- A fenced code block containing `%`, `#`, and `{{ }}` is **preserved** verbatim.
- A real markdown heading (`# Title`) inside the prompt is preserved.
- Assistant response text is untouched.
- Idempotency: sanitizing already-clean text changes nothing.
- Fork-of-a-fork: nested previous-conversation turns are fully clean (no leaked lingo).
- For `strip_known_directives`: duplicate directives and bare `%name` do **not** raise or allocate names.

Update any existing `#fork` workflow assertions (`tests/test_fork_workflow.py`, `test_chat_resume*.py`) that expect the
raw lingo to appear.

## Validation

This touches Python in the sase repo, so run `just install` then `just check` before finishing. (Per the boundary note:
this is presentation/history glue in the Python repo — no `sase-core` wire/API change is required.)

## Out of scope / non-goals

- Not changing what is stored in transcripts (raw prompts stay raw for `sase chats show`).
- Not _expanding_ references into their full instruction bodies (that would inject sase boilerplate instead of removing
  it); references are removed, not rendered.
- No memory-file changes (those require explicit user approval).
