---
create_time: 2026-06-22 08:11:57
status: done
prompt: sdd/prompts/202606/fix_ctrl_n_vcs_mru_cycling.md
---
# Fix Ctrl+N VCS MRU Cycling

## Context

The prompt input widget currently treats `Ctrl+P` as the only VCS xprompt MRU cycle key. `Ctrl+P` advances through the
filtered launchable MRU list and includes one terminal empty/no-VCS stop. `Ctrl+N` was split into
`_handle_vcs_xprompt_delete_key()`, so it always deletes the first VCS workflow tag and never loads or consults MRU
state.

That split lost the bidirectional history behavior. `Ctrl+N` should move back toward newer MRU entries when there is a
selectable next entry, and it should only clear the VCS tag when the reverse cycle reaches the empty stop. It should
also be able to move from a prompt with no VCS tag to the end of the MRU list.

## Plan

1. Reintroduce directional VCS MRU cycling in `src/sase/ace/tui/widgets/_vcs_mru_cycling.py`.
   - Add a small `VcsMruCycleKey` type or equivalent direction parameter for `ctrl+p` and `ctrl+n`.
   - Make `_next_vcs_mru_index()` operate on the existing ring of `len(mru) + 1`, where `len(mru)` is the empty/no-VCS
     stop.
   - Keep `Ctrl+P` moving forward through MRU entries into the empty stop.
   - Make `Ctrl+N` move backward through the same ring, so it selects the previous MRU entry when possible, reaches the
     empty stop at the front boundary, and selects `mru[-1]` when the current prompt has no VCS workflow tag.

2. Route prompt key handling through the directional cycle helper.
   - Change `_handle_vcs_mru_cycle_key()` to accept the key/direction.
   - Call `_handle_vcs_mru_cycle_key("ctrl+n")` for `Ctrl+N` and `_handle_vcs_mru_cycle_key("ctrl+p")` for `Ctrl+P`.
   - Preserve the current completion precedence: active file completion still owns `Ctrl+N` and `Ctrl+P`.
   - Preserve feedback-mode behavior: both keys return before loading MRU.
   - Preserve transient-state cleanup and cursor positioning after successful edits.

3. Keep the delete edit helper as the implementation of the empty stop.
   - Do not remove `_delete_vcs_xprompt_text()`, because the ring's empty stop still needs the existing
     whitespace/directive-aware deletion behavior.
   - Stop exposing a separate prompt key path whose only behavior is deletion.

4. Update tests around the corrected semantics.
   - Replace the test that asserts `Ctrl+N` never loads MRU with tests that assert it cycles when MRU entries are
     available.
   - Cover `Ctrl+N` from a prompt with no VCS tag selecting the oldest/end MRU entry.
   - Cover `Ctrl+N` deleting only at the reverse-cycle boundary, e.g. from the most recent/current first MRU entry.
   - Cover the requested symmetry sequence: `Ctrl+P`, `Ctrl+P`, `Ctrl+N`, `Ctrl+N` returns the prompt to the starting
     VCS workflow when one exists.
   - Keep existing deletion-shape coverage at the pure helper level so whitespace, directives, frontmatter, and
     fenced-block behavior remain pinned.
   - Keep file-completion and feedback-mode precedence tests.

5. Verify with the focused prompt VCS MRU tests.
   - Run
     `pytest tests/ace/tui/widgets/test_vcs_mru_cycling_logic.py tests/ace/tui/widgets/test_prompt_vcs_mru_cycling.py`.
   - If failures reveal wider prompt keymap coupling, run the adjacent prompt completion/keymap tests that own `Ctrl+N`
     and `Ctrl+P` precedence.
