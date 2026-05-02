---
create_time: 2026-04-25 15:34:55
status: done
prompt: sdd/prompts/202604/bulk_wait_marked_agents.md
---
# Bulk-wait support for `W` on the Agents tab

## Goal

On the Agents tab of `sase ace`, pressing `W` currently prefills the prompt input bar with `%w:<name> ` for the single
agent under the cursor. When the user has marked multiple agents with `m`, `W` should instead prefill the prompt with a
single `%w:` directive that lists every marked agent — mirroring the existing bulk-mode UX of `K` (kill) and other
marked-agent operations.

## Why this is the natural shape

The `%w` directive already accepts multiple agent names via comma-separated syntax
(`src/sase/xprompt/directives.py:506-507`). Adding bulk-wait is a **pure UI change**: gather the marked agent names,
join with commas, drop the result into the prompt input bar. No changes to directive parsing, no new wire format, no new
modal.

## Background (from investigation)

- `W` is bound to `action_add_tag` in `src/sase/ace/tui/bindings.py:16`, which dispatches to `action_wait_for_agent()`
  on the Agents tab (`src/sase/ace/tui/actions/base.py:198+`).
- `action_wait_for_agent()` lives at `src/sase/ace/tui/actions/agents/_wait_resume.py:249-275`. Today it:
  1. Returns early if `self.current_tab != "agents"` or no agent / no `agent_name`.
  2. Builds `prefix = f"%w:{name} "`.
  3. Optionally prepends a VCS workflow tag from `_resolve_vcs_tag(...)`.
  4. Calls
     `self._show_prompt_input_bar_for_home(initial_text=prefix, display_name=f"wait({name})", history_sort_key=...)`.
- Marks live in `self._marked_agents: set[(AgentType, str, str | None)]` (`_marking.py:25`). The canonical way to
  enumerate them, used by `_bulk_kill_marked_agents()` (`_marking.py:83-138`), is:
  ```python
  marked = [a for a in self._agents_with_children
            if a.identity in self._marked_agents]
  ```
- The footer / help modal references for `W` appear at `src/sase/ace/tui/modals/help_modal/bindings.py:87` ("Add tag to
  CL description" — the ChangeSpecs-tab meaning) and `:299` ("New agent waiting for this one" — the Agents-tab meaning).
  `W` is NOT in `keybinding_footer.py` today (it's available whenever an agent is selected, so it isn't conditional in
  that footer's sense).

## Behavior

### Trigger

Inside `action_wait_for_agent()`, **after** the `current_tab` guard and **before** the existing single-agent path,
branch on `self._marked_agents`:

- If `_marked_agents` is non-empty → bulk path.
- Otherwise → existing single-agent path, unchanged.

This matches the dispatch shape of `action_kill_agent()` (`_kill_pin.py:64-73`), which checks `if self._marked_agents:`
first.

### Bulk path

1. Resolve the marked set against the live agent list (same idiom as `_bulk_kill_marked_agents`):
   ```python
   marked: list[Agent] = [
       a for a in self._agents_with_children
       if a.identity in self._marked_agents
   ]
   ```
   Iteration order is the panel display order, which gives a deterministic and human-meaningful directive.
2. Filter to agents that have an `agent_name` (the `%w` directive only refers to named agents). If any were skipped,
   accumulate the count and warn after dispatch.
3. If the filtered list is empty, `notify("No marked agents have a name", severity="warning")` and return.
4. If the filtered list has exactly one agent, fall through to the single-agent path using that agent (so a single mark
   behaves identically to the existing single-agent UX, including the VCS tag resolution). This avoids a confusing "bulk
   mode with one entry" state.
5. Otherwise build the prefix:
   ```python
   names = [a.agent_name for a in marked_named]
   prefix = f"%w:{','.join(names)} "
   ```
6. **VCS workflow tag.** The single-agent path prepends a tag derived from one specific agent's raw xprompt. For bulk
   mode, prefer the cursor agent if it is one of the marked agents; otherwise use the first marked agent. Reason: the
   tag controls the _new_ agent's workspace branch, which is independent of how many agents you're waiting for, but the
   cursor is the user's most-recent expression of intent. If `_resolve_vcs_tag` returns a tag, prepend it to `prefix`.
7. Dispatch:
   ```python
   self._show_prompt_input_bar_for_home(
       initial_text=prefix,
       display_name=f"wait({len(names)} agents)",
       history_sort_key=(cursor.cl_name if cursor else "wait") or "wait",
   )
   ```
8. **Do not auto-clear marks.** The user may want to issue a follow-up bulk action (e.g. delete marks via `M`); the
   prompt input bar already reflects the names so there's no risk of a confusing stale state. This matches
   `_bulk_kill_marked_agents`, which also leaves marks intact — they're naturally pruned when the underlying agents
   disappear by `_prune_stale_marked_agents()`.
9. If any agents were filtered out for missing `agent_name`, follow up with
   `notify(f"Skipped {n} marked agent(s) with no name", severity="warning")`.

### Edge cases

| Scenario                                    | Behavior                                                                         |
| ------------------------------------------- | -------------------------------------------------------------------------------- |
| No marks, agent under cursor                | Existing single-agent path.                                                      |
| No marks, no agent under cursor             | Existing `"No agent selected"` warning.                                          |
| 1 mark with `agent_name`                    | Fall through to single-agent path using that agent (cursor irrelevant).          |
| ≥ 2 marks, all named                        | Bulk path, comma-joined `%w:a,b,c `.                                             |
| ≥ 2 marks, some unnamed                     | Bulk path with named subset; warn about skipped count.                           |
| All marked agents lack `agent_name`         | Warn `"No marked agents have a name"`; do not open the prompt bar.               |
| Marks include stale identities (agent gone) | Filter via `_agents_with_children` already drops them; no extra handling needed. |

## Files to change

1. `src/sase/ace/tui/actions/agents/_wait_resume.py` — extend `action_wait_for_agent()` with the bulk branch described
   above. Keep the single-agent body unchanged; either factor it into a small helper that takes an `Agent` so the "1
   mark" case can reuse it, or just reorder to handle bulk first and fall through.

2. `src/sase/ace/tui/modals/help_modal/bindings.py:299` — update the Agents-tab `W` description to mention bulk mode,
   e.g. `"Wait for selected agent (or marked set)"`. Stay within the 32-char description limit called out in
   `src/sase/ace/AGENTS.md`.

3. `tests/ace/tui/test_agent_marking.py` — extend with cases for the bulk-wait dispatch:
   - Two marked named agents → `_show_prompt_input_bar_for_home` invoked with `initial_text` starting with `%w:a,b `
     (and any VCS tag prefix).
   - One marked named agent → behaves identically to the no-mark single-agent case.
   - Marked agents with mixed named/unnamed → only named agents in the directive; warning notification emitted.
   - All-unnamed marked set → no prompt bar; warning emitted.
   - No marks → existing single-agent path still works.

## Files NOT to change

- `src/sase/xprompt/directives.py` — `%w` already supports multi-arg via `:` and comma. No directive-side change needed.
- `src/sase/default_config.yml` — the `add_tag: "W"` keymap entry is unchanged; only its handler's behavior expands.
- `src/sase/ace/tui/widgets/keybinding_footer.py` — `W` is not in the footer today. Adding it is out of scope; if we
  wanted "Wait Marked" to appear conditionally when marks exist, that would be a separate UX decision.
- `src/sase/ace/tui/modals/wait_modal.py` — `WaitModal` is for the separate `r` (reword/wait) flow on RUNNING/WAITING
  agents, not for `W`.

## Verification

- `just check` (per project policy after any source change).
- Manual: open `sase ace` → Agents tab; mark 2-3 agents with `m`; press `W`; confirm the prompt bar opens with
  `%w:<a>,<b>,<c> ` (plus any VCS tag); confirm single-agent `W` still works when no marks; confirm the warning appears
  when marked agents lack names.

## Out of scope

- Submitting the bulk-wait prompt automatically (the user still types the rest of the prompt and submits).
- Showing the bulk count in the keybinding footer.
- Bulk variants of `r` (reword-wait) or `<enter>` (resume).
- Any change to the `%w` directive's parsing or semantics.
