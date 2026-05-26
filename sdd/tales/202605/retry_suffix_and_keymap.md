---
create_time: 2026-05-26 18:16:08
status: done
prompt: sdd/prompts/202605/retry_suffix_and_keymap.md
---
# Retry Suffix And Keymap Plan

## Goal

Update SASE's manual agent retry flow so retry-derived agent names use the `<base>.r<N>` shape instead of `<base>.<N>`,
and make the Agents-tab retry-edit prompt open from the direct `r` key instead of the leader `,r` key.

The intended product behavior is:

- Retrying an agent named `a` proposes/launches `a.r1`, then `a.r2`, and so on, using the lowest available retry slot.
- Retrying an agent that already has a richer name still appends the retry suffix to the selected agent's current name,
  preserving the existing base semantics while changing only the suffix shape.
- On the Agents tab, pressing `r` opens the retry-edit prompt.
- The leader sequence `,r` stops being the Agents-tab retry special case and returns to the existing runners modal
  behavior.

## Current Behavior

- Retry naming is centralized in `src/sase/agent/names/_retry.py` via `allocate_retry_name(base)`. It currently scans
  active agent names and returns the first free `<base>.<N>` candidate.
- The Agents-tab retry action lives in `src/sase/ace/tui/actions/agent_workflow/_entry_points.py` as
  `_retry_edit_agent()`. It reads the selected agent's raw prompt, allocates a retry name, rewrites or prepends the
  top-level `%name` directive, then opens the prompt bar.
- The visible `,r` retry key is implemented as a leader-mode special case in
  `src/sase/ace/tui/actions/agent_workflow/_leader_mode.py`: on the Agents tab, leader `r` dispatches retry-edit before
  the generic `runners` handler.
- The direct `r` key is already the app-level `run_workflow` binding. It runs workflows on the ChangeSpecs tab,
  re-runs/runs selected work on the AXE tab, and currently no-ops on the Agents tab.
- The keymap/help/footer surfaces still advertise retry-edit as a leader-mode action: `src/sase/default_config.yml`,
  `src/sase/ace/tui/keymaps/types.py`, `src/sase/ace/tui/modals/help_modal/agents_bindings.py`,
  `src/sase/ace/tui/widgets/keybinding_footer.py`, and the command catalog.

## Design

Keep retry prompt construction exactly where it is, and change only the retry name shape plus the key path that reaches
it.

1. Change `allocate_retry_name()` to generate `<base>.r<N>`.
   - Existing exact retry names reserve their slot: `foo.r1` blocks `foo.r1`.
   - Existing descendants also reserve their slot: `foo.r1.plan` blocks `foo.r1`.
   - Older `<base>.<N>` names should not block new `.r<N>` slots unless they are descendants of a `.r<N>` candidate.
     This lets the new namespace start at `r1` without being held back by legacy retries.

2. Route direct `r` to retry-edit on the Agents tab through the existing contextual app action.
   - Update `BaseActionsMixin.action_run_workflow()` so its Agents-tab branch calls `_retry_edit_agent()` and returns.
   - Preserve the current ChangeSpecs and AXE behavior for the same key.
   - This avoids duplicate Textual bindings for `r` and keeps the existing configurable app-level `run_workflow` key as
     the source of the physical key.

3. Remove the leader-mode retry special case.
   - Drop `retry_edit` from built-in leader defaults and default config.
   - Remove the `_dispatch_leader_key()` branch that made `,r` retry on Agents.
   - Leave the existing `runners` leader action on `r`, so `,r` shows runners on Agents just as it does elsewhere.

4. Update user-facing key surfaces.
   - Agents help should list `r` under Agent Actions as retry/edit/relaunch.
   - The Agents footer should surface `r retry` when an agent row is focused.
   - The leader footer/help should no longer show `,r` as retry.
   - Docs in `docs/ace.md` should change the Agents-tab retry row from `,r` to `r` while preserving the runners
     documentation for `,r`.

5. Keep command palette behavior coherent.
   - Since the direct key is still the `run_workflow` app action, expand the command catalog/tab scope and availability
     so the action is discoverable on Agents only when an agent is focused.
   - Use labels/aliases that make the contextual retry meaning searchable without breaking existing CL/AXE behavior.

## Tests

Add or update focused tests before broader verification:

- `tests/test_agent_names.py`
  - `allocate_retry_name("foo")` returns `foo.r1`.
  - It skips `foo.r1` and descendants like `foo.r2.plan`.
  - It chains allocations through a provided reserved set using `.r<N>`.

- `tests/ace/tui/test_retry_edit_agent_name.py`
  - Retry prompt rewriting prepends/replaces `%name:foo.r1`.
  - `_retry_edit_agent()` still preserves unnamed-agent behavior.

- `tests/ace/tui/test_agent_wait_resume.py`
  - `action_run_workflow()` on Agents calls retry-edit and does not fork.

- `tests/ace/tui/test_show_agent_run_log_keymap.py` and `tests/test_keymaps.py`
  - `,r` on Agents dispatches runners, not retry.
  - `retry_edit` is no longer part of the default leader-mode map.

- `tests/test_keybinding_footer_agent.py`, help-modal tests, and command availability tests
  - Agents footer/help advertise direct `r` retry.
  - Command availability exposes the contextual direct action on Agents with a focused agent.

- `tests/test_mobile_agent_bridge_smoke.py`
  - Mobile retry expectations should use `.r<N>` if they exercise the shared allocator contract.

## Verification

Run the focused pytest targets after implementation, then follow repo policy:

```bash
just install
just check
```

If `just check` exposes visual snapshot changes in the ACE footer/help surfaces, inspect the generated artifacts before
deciding whether any snapshots need to be updated.
