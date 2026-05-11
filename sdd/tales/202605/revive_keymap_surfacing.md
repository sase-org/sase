---
create_time: 2026-05-11 14:44:28
status: done
prompt: sdd/prompts/202605/revive_keymap_surfacing.md
---
# Plan: Surface `R` (revive) keymap and clean up confusing `r` vs `R` wording

## Background

The TUI has two distinct, easy-to-confuse actions on the Agents tab:

- **`r` (lowercase, `run_workflow` action)** — continues a DONE agent's conversation. Semantically this is **resume**.
  Implementation lives in `src/sase/ace/tui/actions/agents/_wait_resume.py`.
- **`R` (uppercase, `start_rewind` action)** — un-dismisses a dismissed agent (restore it). Semantically this is
  **revive**. Implementation lives in `src/sase/ace/tui/actions/agents/_revive.py`. On the ChangeSpecs tab the same key
  rewinds a CL.

Today the user-facing wording is muddled in two ways:

1. **The `r` keymap is currently described as "Revive chat as agent"** in the help modal
   (`src/sase/ace/tui/modals/help_modal/bindings.py:337`). That's wrong — `r` resumes, it doesn't revive.
2. **The `R` keymap is not surfaced anywhere on the Agents tab.** The command palette catalog already has a
   `start_rewind` entry, but it's scoped to `_CL_ONLY` and labeled "Rewind CL" — the Agents-tab revive behavior is
   invisible to users. The help modal's Agent Actions section also omits it.

The goal is to make `R` discoverable on the Agents tab and to start consistently using "resume" for the `r` action and
"revive" only for the `R` action (un-dismiss). This is the first pass of a broader naming cleanup; we will not chase
every occurrence of "revive" in this CL.

## Scope

In scope:

1. **Command palette (`src/sase/ace/tui/commands/catalog.py`)** — Expand the existing `start_rewind` entry so it shows
   up on the Agents tab. Update its label so users on either tab understand what the key does.
2. **Help popup (`src/sase/ace/tui/modals/help_modal/bindings.py`)** — In the Agents-tab "Agent Actions" section:
   - Add a new line for `R` (`start_rewind`) describing it as the revive (un-dismiss) action.
   - Rewrite the existing `r` (`run_workflow`) line to say "resume" instead of "Revive chat as agent".
3. **Light cleanup on the `r` keymap's user-visible wording** — Wherever the `r` (`run_workflow`) action is described to
   the user as "revive", switch it to "resume". This is a documentation/wording change only; internal identifiers and
   filenames stay as-is.

Out of scope (deliberately deferred):

- Renaming the `_revive.py` module, the `AgentRevivalMixin` class, the `revive_agent_modal.py` file, or any internal
  identifiers. The `R` action genuinely is "revive"; only its discoverability is changing.
- Renaming `start_rewind` itself (it's a single `AppKeymaps` field used by two different tabs). A future cleanup may
  split it, but that's a separate design question.
- Touching notification strings emitted from inside the revive flow (e.g., "Revived agent for ..."). Those describe the
  `R` action and should stay "revive".

## Design

### 1. Command palette

The catalog currently has one entry per `AppKeymaps` field, and `start_rewind` is one such field even though it does two
different things depending on the active tab. There are two reasonable shapes:

- **(A)** Keep one entry, broaden its tab scope to `_CL_AGENTS`, and use a slash-joined label like
  `"Rewind CL / Revive agent"` — same pattern the catalog already uses for `run_workflow` ("Run workflow / resume /
  re-run").
- **(B)** Add a second synthetic catalog entry for the Agents-tab usage.

**Recommendation: (A).** It matches the existing pattern, requires no changes to the "one entry per AppKeymaps field"
invariant guarded by `iter_app_commands`, and gives palette searchers a single hit they can recognize from either tab.
Tab scoping limits where each half is reachable; entry-level applicability already handled by `availability.py`.

### 2. Help modal — Agent Actions section

Two changes in `help_modal/bindings.py`:

- Add a row near the existing revive/resume area: `(d(a.start_rewind), "Revive dismissed agent")` so users on the Agents
  tab can discover `R`.
- Replace `(d(a.run_workflow), "Revive chat as agent")` with `(d(a.run_workflow), "Resume chat as agent")` to remove the
  confusing "revive" label from the `r` row.

Both descriptions stay within the 32-char keybinding description limit called out in `src/sase/ace/AGENTS.md`.

### 3. "Start documenting `r` as resume"

The user-visible "revive" wording on the `r` keymap appears in a small number of places. As a first pass we will update
only what's directly tied to `r` action descriptions:

- The help modal line above.
- Any palette/catalog label for `run_workflow` already says "resume" today, so no change there.

We will **not** touch the revive-modal title ("Revive Agents"), the agent run log modal's `R: revive` footer text, or
the `_revive.py` notifications — those are tied to the `R` action (which is genuinely revive) and don't need to change.

## Risks and trade-offs

- **One-entry-per-field invariant**: The catalog's guard insists each `AppKeymaps` field has exactly one metadata entry.
  Broadening `start_rewind`'s tabs keeps this invariant; adding a second synthetic entry would not. Option (A) is the
  safe path.
- **Slash-label readability**: "Rewind CL / Revive agent" is a bit long but consistent with `run_workflow`'s existing
  pattern. Acceptable.
- **Mixed terminology during transition**: After this CL, internal identifiers still say "revive" in many places (file
  names, class names, function names) while the `R` action's user-visible surfaces continue to say "revive" (correctly).
  The only wording cleanup is on the `r` keymap descriptions. This is intentional — chasing every occurrence would
  balloon scope.

## Affected files

- `src/sase/ace/tui/commands/catalog.py` — broaden tabs and relabel `start_rewind`.
- `src/sase/ace/tui/modals/help_modal/bindings.py` — add `R` row in Agents section; rewrite `r` row label.
- Tests: any snapshot tests for the help modal Agents-tab section or palette listing will need a refresh.

## Verification

- `just check` (lint + tests).
- Manually open the TUI on the Agents tab, hit `?` and confirm `R` is listed with "Revive dismissed agent" and `r` reads
  "Resume chat as agent". Open the palette, search "revive" and confirm `R` is hit-able from the Agents tab; search
  "rewind" and confirm `R` is still hit-able from the ChangeSpecs tab.
