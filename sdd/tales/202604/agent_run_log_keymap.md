---
create_time: 2026-04-28 13:51:14
status: done
prompt: sdd/prompts/202604/agent_run_log_keymap.md
---
# Restore "Agent Run Log" keymap on the CLs tab

## Problem

On the CLs tab, pressing `L` used to open the **Agent Run Log modal**, which lists every agent (including dismissed
ones) that ever worked on the currently selected ChangeSpec. After commit `d7b96606` ("remove FLAT grouping from the CLs
tab"), `L` was repurposed exclusively to **expand all ChangeSpec group folds**, and the `_show_agent_run_log()` fallback
was deleted from `action_expand_all_folds()` in `src/sase/ace/tui/actions/agents/_folding.py`.

The `AgentRunLogModal` widget itself still exists at `src/sase/ace/tui/modals/agent_run_log_modal.py` — only the binding
was lost. We need a new keymap to bring the feature back without re-overloading `L`.

## Investigation summary

- **Current state of `L`** (default_config.yml:49): `expand_all_folds: "L"` — on CLs tab this calls
  `_expand_all_changespec_group_folds()` only.
- **Lost behavior**: `_show_agent_run_log()` used to be invoked under `L` when grouping was inactive (FLAT mode). FLAT
  grouping was removed, so the dispatch site is gone.
- **Modal still wired**: `AgentRunLogModal` is intact and importable; we just need a callsite + key.

### Single-letter keys currently unused in `app` keymaps

Uppercase: `A`, `B`, `D`, `F`, `O`, `P`, `U`, `Z` Lowercase: `f`

(Compiled from a full audit of `src/sase/default_config.yml` lines 8–102.)

## Keymap recommendation

**Use `A` (uppercase)** for the new action `show_agent_run_log`.

Rationale:

- **Mnemonic**: "A for **A**gent log" — directly evokes the feature.
- **Free**: `A` is unbound today; `a` (`accept_proposal`) is unrelated but the lowercase/uppercase asymmetry matches
  existing precedent in the keymap (e.g. `e` edit_spec vs `E` edit_panel, `n` rename_cl vs `N` add_agent_tag).
- **Reachable**: Single-letter, no chord, no leader mode — appropriate for a frequently-used inspection action on the
  CLs tab.
- **Discoverable**: Will appear in the `?` help popup and (if conditional) the footer.

### Alternatives considered

| Key             | Verdict | Notes                                                               |
| --------------- | ------- | ------------------------------------------------------------------- |
| `O`             | Reject  | "lOg" is a stretch; not obvious.                                    |
| `F`             | Reject  | No semantic link to "agent log".                                    |
| `D`             | Reject  | Could be confused with `d` (show_diff).                             |
| `B`/`U`/`Z`/`P` | Reject  | No mnemonic value.                                                  |
| `,a` (leader)   | Reject  | Adds friction for a primary inspection action.                      |
| `f` (lowercase) | Reject  | Often expected to be available for "find/filter" by users; reserve. |

## Proposed changes (high level — implementation will follow plan approval)

1. **New keymap entry** in `src/sase/default_config.yml` under `ace.keymaps.app`:

   ```yaml
   show_agent_run_log: "A"
   ```

   Place it near the other agent/axe-related keymaps (after `edit_panel: "E"` around line 63), or in a new "Agent
   inspection" subsection — pick the location that best matches existing grouping conventions during implementation.

2. **New action handler** — likely `action_show_agent_run_log()` — that:
   - On the CLs tab, opens `AgentRunLogModal` for the currently selected ChangeSpec.
   - Is a no-op (or shows a brief notification) on other tabs, matching the pattern in `action_expand_all_folds()` at
     `src/sase/ace/tui/actions/agents/_folding.py:491`.

   The handler should live alongside the existing tab-conditional actions; the previous `_show_agent_run_log()` helper
   (now deleted) can be reconstructed from git history at commit `2be9acde^` if useful as a reference, but the
   implementation is small enough to rewrite.

3. **Bind the action** through whatever keymap-binding registry the TUI uses (mirror how `expand_all_folds` is bound
   today).

4. **Help modal update** — per `src/sase/ace/AGENTS.md` ("Help Popup Maintenance"), update `help_modal.py` to document
   the new `A` binding. Mind the 57-char box width / 32-char description rules.

5. **Footer** — per the same AGENTS.md, only include in the keybinding footer if the action is _conditionally_ available
   (e.g. only when a ChangeSpec is selected and agents exist). If always available on the CLs tab, leave it to the help
   modal alone. Decide during implementation by reading the existing pattern in `keybinding_footer.py`.

6. **Tests** — add or extend a TUI keymap test covering:
   - Pressing `A` on the CLs tab with a selected ChangeSpec opens `AgentRunLogModal`.
   - Pressing `A` on other tabs is a no-op (or matches whatever non-CLs behavior we settle on).
   - The keymap config parses with the new entry.

## Out of scope

- Any redesign of `AgentRunLogModal` itself.
- Any changes to FLAT/grouping mode behavior or to `expand_all_folds`.
- Reintroducing the `L`-overloads-two-features pattern.

## Risk / open questions

- **Convention check**: Is `A` already used in any **mode** keymap (e.g. fold/leader/checkout mode) where reusing the
  same letter at the top level could cause user confusion? The audit covered the top-level `app` keymaps only —
  implementer should grep modes (`leader_mode`, `fold_mode`, etc.) for `"A"` and adjust if there's a clash worth
  avoiding.
- **Should the action also work on the Agents tab?** ("Show all attempts of the selected agent's ChangeSpec" might be
  useful there too.) Default: CLs tab only, matching the original feature. Open to user feedback.
