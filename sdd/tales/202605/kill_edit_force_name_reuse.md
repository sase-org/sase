---
create_time: 2026-05-13 15:52:58
status: done
prompt: sdd/prompts/202605/kill_edit_force_name_reuse.md
---
# Plan: Force Name Reuse When Killing And Editing Agents

## Context

The `,x` Agents-tab key binding is `leader.kill_and_edit`. It routes through `EntryPointsMixin._kill_and_edit_agent`,
captures the selected agent's raw prompt, kills or dismisses the agent, and then calls `_edit_and_relaunch_agent` to
mount the prompt input bar with that raw prompt.

Agent name overwrite is already supported by the launch path: `%name:!foo` / `%n:!foo` means "force reuse this existing
name". The TUI launch flow detects this, confirms the overwrite, wipes the previous owner, and rewrites the directive
back to the normal form before starting the replacement agent. So the needed behavior is a prompt preparation step for
the `,x` path only.

## Desired Behavior

When `,x` loads the killed agent's prompt into the prompt input bar:

- If the top-level prompt contains an active `%name` or `%n` directive with an argument, rewrite that argument so it
  starts with `!`.
- Preserve the user's directive spelling and argument style where possible: `%n:foo` becomes `%n:!foo`, `%name(foo)`
  becomes `%name(!foo)`, and `%name:\`foo\``becomes`%name:\`!foo\``.
- If the argument already starts with `!`, leave it unchanged.
- Ignore `%name` / `%n` text inside fenced blocks and disabled xprompt regions.
- Leave prompts with no name directive unchanged.
- Leave bare `%name` / `%n` unchanged because there is no explicit argument value to mark for overwrite.
- Do not apply this transformation to `,r` retry-edit, mobile retry, or generic prompt history flows.

## Implementation Approach

1. Add a small shared prompt helper near the existing retry prompt rewrite logic, probably in
   `src/sase/agent/retry_prompt.py`, because that module already owns syntax-aware rewriting of top-level name
   directives while protecting fenced blocks and disabled regions.

2. Implement the helper using the existing directive parser primitives: `_DIRECTIVE_PATTERN`, `_DIRECTIVE_ALIASES`,
   `protect_fenced_blocks`, `protect_disabled_regions`, and `find_matching_paren_for_args`. The helper should find the
   first active directive whose canonical name is `name`, determine whether it has a colon/backtick argument or
   parenthesized argument, and insert `!` at the start of the argument value only when needed.

3. Wire the helper into `EntryPointsMixin._kill_and_edit_agent` after reading `raw_prompt` and before either
   dismissing/killing or mounting the prompt bar. Keeping this in `_kill_and_edit_agent` scopes the behavior to `,x`
   exactly.

4. Add focused tests:
   - unit tests for the helper covering `%name:foo`, `%n:foo`, parenthesized, backtick, already-forced, bare directive,
     no directive, fenced, and disabled regions;
   - an entry-point test proving `_kill_and_edit_agent` passes the forced prompt to `_edit_and_relaunch_agent` for a
     done/pidless agent without changing `_retry_edit_agent` behavior.

5. Verify with targeted pytest first, then run the required repo check sequence: `just install` followed by
   `just check`.

## Risk Notes

The main edge case is preserving directive syntax without accidentally rewriting examples in prompt text. Reusing the
existing directive pattern and protection helpers keeps this aligned with current directive extraction semantics.

This is TUI behavior: the backend launch parser and name registry already support the `!` overwrite semantics, so no
Rust core change should be needed.
