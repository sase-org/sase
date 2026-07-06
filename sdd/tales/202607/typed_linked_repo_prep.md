---
create_time: 2026-07-06 14:51:14
status: done
prompt: sdd/prompts/202607/typed_linked_repo_prep.md
---
# Thread Typed Linked-Repo Resolution into Launch-Time Workspace Prep

## Assessment of the Existing Fix

Commit `f672125c5` ("fix: prepare linked repo workspaces before agent launch") took the right approach overall:

- It reuses `prepare_workspace()` (`src/sase/axe/runner_utils.py`), the same clean → checkout-default-parent → sync
  primitive used for the primary workspace and by `sase workspace open` (`handle_open_clean` in
  `src/sase/main/workspace_handler_list.py`). No core clean/update semantics were duplicated.
- It runs in the correct lifecycle windows (regular launches after primary prep + linked env/meta refresh; deferred
  `%wait` launches after the real workspace claim + refresh) and correctly excludes home mode, retry-spawn children,
  static `workspace.strategy: none` repos, and entries whose `workspace_dir` aliases the primary checkout.
- Failures abort loudly before workflow execution.

However, the data flow between the refresh and prep steps has a real defect plus avoidable indirection:

1. **Stale-metadata hazard (correctness).** `prepare_linked_repo_workspaces_if_needed` consumes
   `agent_meta.get("linked_repos")` — the JSON-able serialization — instead of the typed `LinkedRepoResolution` that
   `refresh_linked_repos_for_workspace` computes one line earlier. `refresh_linked_repos_for_workspace` only overwrites
   `agent_meta["linked_repos"]` when the fresh resolution is **non-empty** (deliberate compat so meta readers keep prior
   data), and `extract_directives_and_write_meta` seeds that key from spawn-time env (`_linked_repos_from_env()` in
   `src/sase/axe/run_agent_directives.py`). Consequence: if a launch-time re-resolution comes back empty (linked repo
   primary path missing, config drift mid-flight), prep still acts on the _stale_ spawn-time entries — and
   `prepare_workspace` is destructive (it cleans the working tree of whatever directory it is given). Prep must only
   ever touch directories the fresh resolution vouches for.

2. **Untyped round-trip.** `_workspace_backed_linked_repos` re-parses the JSON-able list with defensive `isinstance`
   checks, silently skipping malformed entries and fabricating a `"linked-repo"` fallback name. Any drift in the
   metadata shape would silently disable the whole safety net — the same silent-staleness failure class the original fix
   exists to eliminate. The typed `LinkedRepoResolution` (with `_ResolvedLinkedRepo` entries carrying `name`,
   `primary_dir`, `workspace_dir`, `workspace_strategy`) is already in hand; none of this parsing needs to exist.

3. **Vestigial prompt pass-through.** `refresh_linked_repos_for_workspace` takes `prompt` and returns it unchanged (a
   leftover of removed prompt-note behavior, as its own test name
   `test_refresh_linked_repos_for_workspace_updates_env_meta_without_prompt_note` records). The
   `prompt = refresh_linked_repos_for_workspace(...)` assignments at both call sites imply a transformation that never
   happens.

4. **Duplicated guards.** The call sites in `src/sase/axe/run_agent_runner.py` already guard on
   `update_target`/home-mode/`retry_handoff is None`, yet the prep helper re-checks `is_home_mode` and `retry_handoff`
   internally. One eligibility window, expressed twice, added by the same commit.

## Goal

Make launch-time linked-repo preparation consume the freshly computed typed resolution directly, so prep can only act on
directories the current resolution produced, and delete the untyped re-parsing layer. Keep all metadata/env
compatibility behavior and lifecycle windows exactly as they are.

## Implementation Plan

1. Return the resolution from the refresh helper (`src/sase/axe/run_agent_runner_setup.py`).
   - Change `refresh_linked_repos_for_workspace` to return the `LinkedRepoResolution` it computed; drop the `prompt`
     parameter and the prompt return.
   - Keep env application and `agent_meta` behavior byte-identical, including preserving prior
     `linked_repos`/`sibling_repos` meta when the resolution is empty (that compat is for meta readers, not for prep).
   - Import `LinkedRepoResolution` for annotations in a way consistent with the module's local-import convention (e.g. a
     `TYPE_CHECKING` import).

2. Make the prep helper take the typed resolution (`src/sase/axe/run_agent_runner_setup.py`).
   - Change `prepare_linked_repo_workspaces_if_needed` to accept `resolution` and `cl_name` only, dropping the
     `is_home_mode`/`retry_handoff` parameters now enforced solely at the call sites.
   - Filter `resolution.repos` on typed fields: `workspace_strategy == "suffix"`, non-empty `workspace_dir`, and
     `workspace_dir != primary_dir`. Use each repo's real `name` (always populated on the typed entry); the fabricated
     `"linked-repo"` fallback disappears.
   - Delete `_workspace_backed_linked_repos` entirely. Keep the default-revision sentinel, per-repo backup suffix, and
     the loud `RuntimeError` on failure unchanged.

3. Update both call sites (`src/sase/axe/run_agent_runner.py`).
   - Regular path: inside the existing `update_target and not is_home_mode and retry_handoff is None` guard, capture
     `resolution = refresh_linked_repos_for_workspace(...)` and pass it to
     `prepare_linked_repo_workspaces_if_needed(resolution=resolution, cl_name=cl_name)`.
   - Deferred path: same shape after `claim_deferred_workspace`, preserving the existing
     `update_target and retry_handoff is None` guard around prep.
   - Remove the `prompt = ...` assignments; the prompt is untouched by refresh.

4. Update and extend tests.
   - `tests/test_run_agent_runner_setup.py`: adapt the two refresh tests to the new return value (no prompt); adapt the
     three prep tests to build typed resolutions (constructing `_ResolvedLinkedRepo` entries directly is fine — this
     test file already imports private helpers). Keep the default-revision-sentinel, static/primary-skip, and
     failure-message assertions.
   - Add a regression test for the hazard in this plan's assessment: stale `agent_meta["linked_repos"]` entries plus an
     empty fresh resolution must prepare nothing.
   - `tests/test_axe_run_agent_runner_started_at.py` and `tests/test_axe_run_agent_runner_deferred_workspace.py`: update
     the patched `refresh_linked_repos_for_workspace` fakes to return typed resolutions, and the prep fakes to read
     them; keep the lifecycle-ordering and abort-before-execution assertions intact.

5. Keep everything else stable.
   - No changes to spawn-time resolution (`src/sase/agent/launch_spawn.py`), `claim_deferred_workspace`,
     `extract_directives_and_write_meta`'s env-seeded meta, canonical/`sibling_repos` compat keys, or
     `sase workspace open`.

## Explicitly Out of Scope

- Consolidating the redundant re-resolutions (spawn-time env export, `claim_deferred_workspace`'s env apply, and the
  runner refresh all call `resolve_linked_repos_for_project`; they are idempotent, and touching the spawn path expands
  the blast radius for no behavioral gain here).
- Migrating workspace prep semantics into the Rust core. Launch lifecycle orchestration is runner-local today and the
  prep primitive is shared Python used by both the runner and the `workspace open` CLI; moving it is a separate effort.

## Verification

1. Run the targeted suites: `tests/test_run_agent_runner_setup.py`, `tests/test_axe_run_agent_runner_started_at.py`,
   `tests/test_axe_run_agent_runner_deferred_workspace.py`.
2. Because repo files change, run `just install` and then `just check` (refresh the linked `sase-core` checkout via
   `sase workspace open` first if the Rust binding version skews, as previously observed).
