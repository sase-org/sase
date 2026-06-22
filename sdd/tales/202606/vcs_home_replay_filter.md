---
create_time: 2026-06-22 09:57:36
status: done
prompt: sdd/prompts/202606/vcs_home_replay_filter.md
---
# Plan: Exclude `#git:home` From VCS Replay History

## Problem

Using the `Ctrl+Space` ACE keymap can replay a saved selection that opens the prompt input bar prefilled with
`#git:home `. That should not happen. The implicit default VCS workflow `#git:home` is normalization for bare home-mode
launches, not a user-selected VCS xprompt workflow, so it should not be persisted as a replayable VCS workflow and
should not become the target of `Ctrl+Space`.

The existing MRU file path already has protections:

- `sase.history.vcs_xprompt_mru.record_vcs_xprompt_usage()` removes/skips the default prefix.
- `sase.history.vcs_xprompt_mru.load_launchable_vcs_xprompt_mru()` prunes persisted `#git:home` entries before
  prompt-local MRU cycling or "edit last VCS xprompt" can use them.

The remaining bug appears to be the separate `last_agent_selection.json` replay path used by the ACE `Ctrl+Space`
binding:

- A bare home-mode prompt is normalized to `#git:home ...`.
- Launch resolution produces `vcs_ref == ("git", "home")`.
- `save_replayable_vcs_selection()` converts that resolved ref into a
  `SelectionItem(item_type="project", project_name="home")`.
- Later `action_start_agent_from_changespec()` replays that selection and `_start_custom_agent_from_selection()`
  pre-fills `#git:home `.

## Desired Behavior

- Bare home-mode launches may still normalize to `#git:home` internally so launch semantics stay unchanged.
- The implicit default `#git:home` must not be saved to either VCS MRU history or the `Ctrl+Space` replay selection.
- Existing stale persisted replay selections that would reproduce `#git:home ` should be ignored/cleared instead of
  reused.
- Explicit non-default VCS refs, including launchable project and CL refs, should continue to populate MRU/replay state.

## Implementation Steps

1. Centralize the default-prefix predicate.
   - Keep the existing normalization-aware default check in `sase.history.vcs_xprompt_mru`.
   - Expose it through a clearly named helper such as `is_default_vcs_xprompt_prefix(prefix: str) -> bool`, while
     preserving existing internal behavior.
   - Use that helper instead of duplicating string comparisons.

2. Stop saving the implicit default as a `Ctrl+Space` replay target.
   - Update `sase.ace.tui.actions.agent_workflow._launch_history.save_replayable_vcs_selection()` to return without
     saving when `vcs_ref` corresponds to the default prefix (`#git:home` after underscore normalization).
   - This covers both a bare prompt that was normalized and an explicit `#git:home` prompt.

3. Clear stale saved replay selections that would reopen `#git:home`.
   - Extend the `action_start_agent_from_changespec()` load path in `sase.ace.tui.actions.agent_workflow._entry_points`
     so a previously saved project selection for `home` is treated as non-replayable when the computed VCS prefix is the
     default `#git:home`.
   - Clear the persisted selection with the existing `clear_last_agent_selection()` mechanism and surface a concise
     warning rather than mounting a prompt prefilled with `#git:home`.
   - Keep `item_type="home"` behavior intact: the normal home-mode keymap should still open an empty home prompt.

4. Add regression coverage.
   - Add/adjust tests for `save_replayable_vcs_selection()` or the launch-body path proving `("git", "home")` does not
     write `last_agent_selection.json` and does not update the in-memory last selection.
   - Add an ACE entry-point test proving a stale saved project-home selection is cleared and does not mount a
     `#git:home ` prompt on `Ctrl+Space`.
   - Keep existing MRU tests for `vcs_xprompt_mru` passing; add coverage only if a public helper changes imports.

5. Review user-facing ACE help text.
   - The key binding itself should not change, and "repeat last selection" is still broadly accurate.
   - If the code change makes any help modal or command palette description misleading, update the relevant help/catalog
     text in the same patch.

6. Verify.
   - Run targeted tests around VCS MRU, ACE launch replay, and last-agent selection.
   - Because this repo requires it after implementation changes, run `just install` if needed and then `just check`
     before finalizing.

## Risks and Mitigations

- Risk: Blocking all project selections named `home` could accidentally reject a legitimate non-default provider ref.
  Mitigation: compare the computed/default-normalized VCS prefix, not only `project_name == "home"`, where the workflow
  type is available.
- Risk: Existing stale persisted state can continue to surprise users after the save-path fix. Mitigation: handle stale
  default-home replay selections on load and clear them.
- Risk: Launch semantics for bare home-mode prompts could regress if normalization is changed too early. Mitigation:
  leave prompt normalization and actual launch routing unchanged; only filter replay-history persistence.
