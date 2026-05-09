---
create_time: 2026-05-08 20:04:47
bead_id: sase-2e
tier: epic
status: done
prompt: sdd/prompts/202605/permanent_agent_names.md
---
# Permanent Agent Names

## Goal

Make agent names permanent IDs:

- Never rename an existing agent during dismissal, explicit-name claim, revive, retry, repeat, de-duplication, or loader
  reconciliation.
- Never allow a name that has ever belonged to an agent to be reused while the previous agent still exists anywhere in
  SASE state.
- Allow deliberate reuse only through `%name:!<name>`, after a y/n confirmation, by killing the previous agent if needed
  and completely wiping all of its persisted system state.
- Reset the auto-generated namespace by migrating every existing auto-generated name to `YYmmdd.<old-name>` and updating
  every persisted reference to it, including the currently running planner agent (`aoa` in `SASE_AGENT_NAME`).
- Extend auto-generated names from `[a-z]+` to `[a-z][a-z0-9]*`, with no generated name starting with a digit.
- Keep name lookup, membership checks, and next-auto-name allocation fast.

## Current State

The old behavior is intentionally mutable:

- `src/sase/agent/names/_claim.py` rewrites existing agents on explicit `%name:<name>` collision to `<name>_2`,
  `<name>_3`, etc.
- `../sase-core/crates/sase_core/src/agent_cleanup/planner.rs` emits dismissal rename intents that prefix names with
  `YYmmdd.`; Python applies them in `src/sase/ace/tui/actions/agents/_dismiss_cleanup.py` and rewrites wait/resume
  references through `src/sase/agent/dismissed_name_rewrites.py`.
- `src/sase/agent/names/_auto.py` treats only visible/non-dismissed names as reserved and uses an alphabetic sequence.
- The launch choke point is `src/sase/axe/run_agent_phases.py::extract_directives_and_write_meta`, which writes
  `agent_meta.json` and calls `claim_agent_name`.
- TUI launch history is written before the runner validates names, so cancel-on-name-collision needs an earlier
  validation path in TUI/CLI launchers.

## Design

Introduce a durable agent-name registry/index as the single source of truth for name reservation. It should be
append-only for normal lifecycle operations and should support O(1) membership checks after one cheap load:

- Store a compact JSON or SQLite index under `~/.sase`, keyed by `agent_name`.
- Each entry records at least `name`, canonical owning artifact identity (`project_name`, `workflow_dir`, `raw_suffix`,
  `artifacts_dir`), current lifecycle state, `created_at`, and enough fields to wipe the owner for `%name:!`.
- Rebuild/self-heal the index from artifacts, dismissed bundles, `done.json`, `agent_meta.json`, and workflow markers
  when missing or stale.
- Do not exclude dismissed agents from the reservation set. Dismissal hides agents; deletion/wipe is what releases
  names.
- Preserve existing `find_named_agent()` semantics for resolution, but use the registry for fast membership and
  next-name allocation.
- Keep the existing `agent_name_allocation_lock()` around scan/allocate/claim to serialize writers.

Cancellation semantics:

- `%name:<name>` where `<name>` was ever used by an existing agent cancels the entire prompt before any agent process is
  spawned.
- The prompt is written to prompt history with `cancelled=True`.
- The user sees a toast like: `Agent name 'foo' is taken. Try 'foo1'.`
- Suggested name is the lowest positive integer suffix `<name><N>` absent from the registry.
- For multi-prompt, fan-out, repeat, and multi-model expansions, validate every explicit or injected name in the
  complete launch plan before launching the first subprocess; fail atomically.

Forced reuse semantics:

- `%name:!<name>` means "wipe the previous owner of `<name>` and then claim `<name>`".
- TUI launch must show a y/n confirmation before dispatch. CLI/mobile launch should fail with a clear
  confirmation-required error unless a suitable explicit confirmation flag is added to that surface.
- If confirmed, kill the existing owner if it is live, remove its dismissed index entries, bundles, artifact
  markers/directory state, notifications, workspace claims, and name-registry entry, then claim the name for the new
  agent.
- The wipe operation must be narrower than "dismiss": after wipe, normal name lookup and history/resume references to
  the old agent should not resolve.

## Phase 1: Registry and Fast Name Allocation

Owner: core naming layer, mostly Python with tests.

Implement the name registry module, fast membership helpers, and the new auto-name sequence.

Work:

- Add a module such as `src/sase/agent/names/_registry.py` with load/save, rebuild, lookup, claim, delete, and
  lowest-suggestion APIs.
- Represent "used by an existing agent" across active artifacts, done artifacts, dismissed artifacts, dismissed bundles,
  workflow children, retry children, and historical aliases.
- Keep best-effort self-healing: if the index is absent/stale, rebuild once from disk; subsequent membership checks
  should avoid repeated full tree walks.
- Update `_AUTO_NAME_PREFIX_RE` and auto sequence to use `[a-z][a-z0-9]*`.
- Generate names in this order: `a..z`, then two-character names with first char `a..z` and later chars `a..z0..9`, then
  longer names with the same first-character rule.
- Change `get_next_auto_name()` and `allocate_auto_names()` to use the registry reservation set, not only active visible
  agents.
- Keep explicit "1" and "2b" invalid for auto-generation by construction.

Tests:

- Update `tests/test_agent_names_auto_name.py` for the new sequence, including transition from `z` to `aa`, and coverage
  for numeric suffixes after letters.
- Add registry tests for active, done, dismissed, bundle-only, stale/missing-index rebuild, and lowest suggestion
  (`foo1`, `foo2`, ...).
- Add a performance regression test or benchmark assertion around next-name allocation against a large synthetic
  reservation set.

## Phase 2: Stop All Lifecycle Renames

Owner: cleanup/dismiss/revive/name-claim lifecycle.

Remove all normal-path code that changes previous agent names.

Work:

- Replace `_claim.py` explicit collision behavior with "reject/collision" behavior. It must never rewrite an existing
  agent.
- Keep auto/retry/resume/repeat allocation as allocators for new names only; they may choose a different new name, but
  must not mutate old agents.
- Remove dismissal rename planning from Rust cleanup side effects:
  - Delete or deprecate `dismissal_rename_allocations` and `wait_reference_rewrite_map` emissions in
    `agent_cleanup/planner.rs`.
  - Mirror the change in `src/sase/core/agent_cleanup_facade.py` fallback and `src/sase/core/agent_cleanup_wire.py`.
  - Make `apply_dismissal_rename_intents()` a no-op or remove the call sites once all tests are updated.
- Change dismissal persistence so it hides/saves/deletes marker files without changing `agent_meta.name`, `done.name`,
  `workflow_name`, child names, or references.
- Change revive so it restores visibility/artifacts without stripping `YYmmdd.` from names or deduping to `<name>_2`.
- Audit retry, resume, repeat, multi-model, and plan-chain naming for any previous-agent mutation. They may allocate new
  descendant names, but they cannot rewrite old metadata.

Tests:

- Replace `tests/test_agent_dismiss_names.py`, `tests/test_dismissed_agent_lifecycle.py`, `tests/test_agent_revive.py`
  assertions that expect dismissal/revive renames.
- Update Rust tests in `../sase-core/crates/sase_core/src/agent_cleanup/planner.rs`.
- Add regression tests proving dismissal and revive do not change `agent.agent_name`, `agent_meta.json`, `done.json`,
  bundle names, or wait/resume references.

## Phase 3: Launch-Time Validation, Cancellation, and Forced Reuse

Owner: TUI/CLI/mobile launch paths and directive parsing.

Validate `%name` before launch, cancel atomically, and implement `%name:!<name>`.

Work:

- Extend directive parsing to preserve forced-reuse intent separately from the actual name, e.g.
  `PromptDirectives.name_force_reuse`.
- Add a launch-planning validator that extracts explicit names after xprompt expansion/fanout naming and checks the
  registry under `agent_name_allocation_lock()`.
- Insert this validator before prompt history writes and before subprocess spawn in:
  - TUI single launch in `_agent_launch.py`.
  - TUI multi-prompt, multi-model, repeat, and bulk launch entry points.
  - CLI/mobile `launch_agents_from_cwd()`.
  - Any embedded workflow path that can spawn `ace-run` agents with explicit `%name`.
- On collision without `!`, write the original prompt to history with `cancelled=True`, skip all subprocesses, and
  notify the user with the lowest `<name><N>` suggestion.
- For `%name:!<name>`, block and ask y/n confirmation in the TUI before dispatch. After confirmation, run a new wipe
  helper for the previous owner, then continue launch with `%name:<name>` semantics.
- Ensure a multi-prompt with any bad explicit name cancels the whole prompt and launches zero agents.
- Ensure `claim_agent_name()` registers the newly written owner atomically and fails if the registry says the name is
  taken by another existing owner.
- Replace manual TUI "name agent" rename in `src/sase/ace/tui/actions/rename.py` with the same policy. Existing named
  agents cannot be renamed to a taken historical name; if renaming an unnamed agent, the new name is a first claim.

Tests:

- TUI submit tests for collision toast, cancelled history entry, and no launch.
- CLI/mobile launch tests for collision failure and cancelled prompt-history entry where applicable.
- Multi-prompt/fanout/repeat tests proving atomic cancellation.
- `%name:!foo` tests for confirmation false/true, live-owner kill path, completed-owner wipe path, and no-confirmation
  behavior on non-TUI surfaces.

## Phase 4: Historical Auto-Name Migration and Namespace Reset

Owner: one-shot migration/tooling plus compatibility.

Prefix every existing auto-generated name with `YYmmdd.` and rewrite all references, so `a` becomes available again.

Work:

- Add an idempotent migration function/CLI invoked at startup before name allocation.
- Detect auto-generated names under the old policy: bare `[a-z]+` roots and their generated descendants (`a`, `a.codex`,
  `a.claude`, `a.plan`, `a.1`, `a.r1`, etc.) that are tied to an auto root. Do not prefix user names like `sase-z`.
- Use the owning agent completion/start/artifact date for the `YYmmdd.` prefix, matching the current historical prefix
  convention.
- Rewrite every persisted reference for migrated names:
  - `agent_meta.json`: `name`, `workflow_name`, `wait_for`.
  - `done.json`: `name`, `workflow_name`.
  - `waiting.json`, `ready.json`.
  - `raw_xprompt.md` wait/resume directives.
  - dismissed bundles and dismissed indexes.
  - notifications action data containing `agent_name`.
  - prompt history entries that contain `%wait`, `%w`, or `#resume` references to migrated names.
  - chat metadata or link sections only where structured agent names are stored; avoid rewriting arbitrary chat prose
    unless there is already a structured helper.
- Include the current running agent. In this session the environment shows `SASE_AGENT_NAME=aoa` and
  `SASE_ARTIFACTS_DIR=/home/bryan/.sase/projects/sase/artifacts/ace-run/20260508200053`, so the migration should update
  `aoa` and references to its prefixed form.
- After migration, rebuild the registry so `get_next_auto_name()` returns `a`.
- Make migration idempotent by recording a schema/version marker and by skipping names already carrying `YYmmdd.`.

Tests:

- Golden fixture migration test covering active, done, dismissed bundle-only, workflow children, wait/resume refs,
  notifications, and prompt history.
- Test current-process artifact migration with env-like fixture data.
- Test idempotency.
- Test that after migration `get_next_auto_name()` returns `a` even when old auto roots existed.

## Phase 5: Wipe/Delete Semantics for Forced Reuse

Owner: cleanup execution and owner lookup.

Implement the "previous agent is deleted" contract used by `%name:!`.

Work:

- Add a single high-level wipe helper taking a registry owner or name.
- If live, terminate using the existing kill path and release workspace claims.
- Delete or neutralize artifact state so loaders, name lookup, revive, notification jump, and prompt history do not
  rediscover the old owner as an existing agent.
- Remove dismissed bundle/index entries for the owner and its workflow children/follow-up/retry descendants.
- Dismiss or remove related notifications.
- Remove registry entries for all wiped names.
- Return a structured result for toast/logging and tests.

Tests:

- Wipe live agent, done agent, dismissed bundle-only agent, workflow parent with children, retry chain, and follow-up
  descendants.
- Verify `find_named_agent(old_name)` returns `None` and registry membership is clear after wipe.
- Verify unrelated agents and prompt history are not damaged.

## Phase 6: Performance, Integration, and Cleanup

Owner: final integration agent.

Finish cross-surface integration, remove legacy rename helpers, and run broad validation.

Work:

- Audit all imports/call sites of `dedup_name`, `allocate_revived_name`, `allocate_dismissed_name`,
  `rewrite_dismissed_references`, `dismissal_rename_allocations`, and `wait_reference_rewrite_map`; delete or narrow
  them to migration-only use.
- Ensure all launch paths use the same validation result type and toast/error wording.
- Add docs/help text for `%name:!<name>` and the new permanent-name behavior.
- Update directive completion text if needed.
- Run `just install` before checks in this workspace, then `just check`.
- Run focused Rust tests in `../sase-core` for agent cleanup and any new core naming code.
- Run focused Python tests for naming, launch, dismissal, revive, prompt history, notification toasts, and mobile
  launch.

Acceptance criteria:

- No normal lifecycle path changes an existing agent's name.
- A name used by any existing agent blocks reuse until wipe/delete.
- `%name:<taken>` cancels before spawn, records cancelled history, and displays the suggested `<name><N>`.
- `%name:!<taken>` requires confirmation and wipes the old owner before reuse.
- Auto names include digits after the first character and reset to `a` after migration.
- Existing auto-generated names, including the current `aoa`, are migrated to `YYmmdd.<name>` with references updated.
- Name membership and next-auto-name allocation do not introduce repeated full artifact scans on hot paths.
