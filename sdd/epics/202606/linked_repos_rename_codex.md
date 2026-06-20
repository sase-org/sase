---
create_time: 2026-06-20 13:49:11
status: done
prompt: sdd/prompts/202606/linked_repos_rename_codex.md
bead_id: sase-51
tier: epic
---
# Rename Configured Sibling Repos To `linked_repos`

## Objective

Rename SASE's configured sibling-repository feature to the public config key `linked_repos` while preserving the
behavior that makes the feature useful:

- workspace-number matched related checkouts for agent workspaces;
- static singleton repos through `workspace.strategy: none`;
- launch-time environment variables and `agent_meta.json` metadata;
- deferred-workspace re-resolution after `%wait` agents claim a real workspace;
- `sase workspace open -p ...` intent tracking;
- finalizer enforcement for opened numbered related repos and advisory handling for static repos.

This is a compatibility migration, not a feature removal. Existing `sibling_repos` configs must continue to work during
the migration window.

## Scope Decisions

- The canonical public key is `linked_repos`, not `linked_repositories`.
- Keep `workspace.strategy` values `suffix` and `none` in this migration. Renaming those to `matched`/`static` is a
  separate breaking-compatibility project.
- Keep unrelated uses of "sibling" intact, including agent siblings, ChangeSpec siblings, path layout wording, and TUI
  sibling navigation.
- Keep serialized hidden ProjectSpec state `PROJECT_STATE: sibling` for now. It can be documented as legacy backing
  state for linked-repo bookkeeping. Renaming lifecycle states should be a separate plan if it touches Rust/core
  boundaries or persisted state migration.
- Do not modify protected `memory/*.md` files without explicit user approval. Implementation phases may update memory
  generation code and tests; checked-in generated memory should be approval-gated.
- Existing behavior is currently Python-owned. If an implementation phase finds this should move into `sase-core`, split
  that into a focused Rust-core boundary phase instead of widening the phase in place.

## Phase 1: Compatibility Foundation In SASE

Target repo: SASE checkout assigned to the agent.

Purpose: introduce canonical linked-repo primitives while preserving every current caller.

Work:

- Add a neutral module/API, preferably `src/sase/linked_repos.py`.
- Move or mirror current resolver behavior from `src/sase/sibling_repos.py` into linked terminology:
  `LinkedRepoResolution`, resolved linked repo records, env constants, and opened-linked marker helpers.
- Keep `src/sase/sibling_repos.py` as a compatibility wrapper that delegates to the linked implementation and re-exports
  old names.
- Parse `linked_repos` as canonical and `sibling_repos` as a deprecated alias.
- Define merge/conflict behavior:
  - legacy-only entries continue to work;
  - canonical entries win for duplicate names;
  - exact duplicates are deduped;
  - same-name divergent definitions produce a non-fatal warning instead of silently creating `_2` env aliases.
- Emit new env vars and legacy aliases together:
  - `SASE_LINKED_REPOS_JSON`;
  - `SASE_LINKED_REPO_<ENV_NAME>_DIR`;
  - `SASE_LINKED_REPO_<ENV_NAME>_PRIMARY_DIR`;
  - existing `SASE_SIBLING_*` aliases.
- Scrub both linked and sibling env prefixes before applying a fresh resolution.
- Add `opened_linked_workspaces.json`; read both it and legacy `opened_siblings.json`. During the migration, write both
  markers so mixed-version tooling and rollback remain safe.

Verification:

- Focused resolver tests covering `linked_repos`, legacy `sibling_repos`, both keys together, duplicate/conflict
  behavior, env emission, env scrubbing, marker compatibility, workspace matching, and static `none` behavior.
- Existing `tests/test_sibling_repos.py` remains green through the compatibility wrapper.
- Run targeted tests first, then `just check` for the phase.

## Phase 2: Runtime Call-Site Migration In SASE

Target repo: SASE checkout assigned to the agent.

Purpose: make runtime behavior canonical on linked terminology without breaking old agents, old env, or old config.

Work:

- Update launch and deferred-workspace paths to use `sase.linked_repos`:
  - `src/sase/agent/launch_spawn.py`;
  - `src/sase/axe/run_agent_phases.py`;
  - `src/sase/axe/run_agent_runner_setup.py`;
  - `src/sase/axe/run_agent_directives.py`.
- Store canonical `linked_repos` in `agent_meta.json`; keep `sibling_repos` as a compatibility metadata alias if needed
  for existing readers.
- Update the commit finalizer to prefer linked env/metadata and fall back to sibling env/metadata:
  - target discovery;
  - opened marker discovery;
  - dirty repo details;
  - follow-up prompt wording.
- Preserve finalizer semantics exactly:
  - unopened numbered linked repos are ignored;
  - opened numbered linked repos block until clean or committed;
  - static `workspace.strategy: none` repos are advisory;
  - config fallback still works when env is absent.
- Update `sase workspace open -p <name> <workspace_num>` internals to record linked openings while preserving current
  project resolution behavior.

Verification:

- Update and run targeted tests:
  - `tests/test_cd_spawn_env.py`;
  - `tests/test_run_agent_runner_setup.py`;
  - `tests/test_axe_run_agent_runner_deferred_workspace.py`;
  - `tests/llm_provider/test_commit_finalizer_siblings.py`;
  - `tests/main/test_workspace_handler_list_path.py`;
  - `tests/main/test_workspace_handler_project_resolution.py`.
- Add compatibility tests proving old env and old marker files still drive finalizer behavior.
- Run `just check`.

## Phase 3: Public Config, Schema, Docs, And SASE Repo Config

Target repo: SASE checkout assigned to the agent.

Purpose: make `linked_repos` the documented and configured public surface in SASE.

Work:

- Change `src/sase/default_config.yml` from `sibling_repos: []` to `linked_repos: []`.
- Update `config/sase.schema.json`:
  - add canonical `linked_repos`;
  - keep deprecated `sibling_repos`;
  - share the same item schema;
  - update descriptions to reference linked repos and linked env vars.
- Rename the configured block in SASE's own `sase.yml` to `linked_repos`.
- Update the SASE `Justfile` to prefer `SASE_LINKED_REPO_SASE_CORE_DIR`, while preserving fallbacks through
  `SASE_CORE_DIR` and legacy `SASE_SIBLING_REPO_*` variables.
- Update generated-memory code and tests to render "Linked Repositories" and `linked_repo` placeholder wording.
- Update current user docs that describe the configured-repo feature:
  - `README.md`;
  - `docs/configuration.md`;
  - `docs/commit_workflows.md`;
  - `docs/init.md`;
  - `docs/llms.md`;
  - other current docs found by targeted `rg`.
- Do not rewrite historical SDD records unless they are active handoff docs for this migration.
- Do not edit checked-in `memory/*.md` without explicit approval; if they become stale, document the approval need in
  the phase result.

Verification:

- `npx prettier --check` for changed Markdown/JSON/YAML files.
- Targeted schema, memory, and Justfile tests:
  - `tests/test_config_schema.py`;
  - `tests/main/test_init_memory_*.py`;
  - any existing Justfile env tests or a new focused one if needed.
- Run `just check`.

## Phase 4: Compatibility Audit And Deprecation Guardrails

Target repo: SASE checkout assigned to the agent.

Purpose: remove accidental stale public vocabulary after the functional migration is green, while leaving deliberate
compatibility aliases in place.

Work:

- Add clear deprecation wording for `sibling_repos` in docs and schema.
- Decide whether runtime should surface a non-fatal warning for legacy `sibling_repos`; if added, avoid noisy repeated
  warnings in launched agents.
- Audit public and generated surfaces for feature-specific stale strings:
  - env docs;
  - prompt/finalizer text;
  - `agent_meta.json` docs or tests;
  - generated skill docs only if the skill generation pipeline actually references this configured-repo feature.
- If any phase changes generated skills or CLI-skill contract files, first read the relevant long memory with
  `/sase_memory_read`, especially `memory/generated_skills.md`.
- Keep old Python import paths and old env vars available unless a later breaking release explicitly removes them.

Verification:

- `rg` audit for:
  - `sibling_repos`;
  - `SASE_SIBLING_REPOS_JSON`;
  - `SASE_SIBLING_REPO_`;
  - `opened_siblings.json`;
  - `sibling repo`.
- Confirm remaining hits are deliberate compatibility aliases, unrelated meanings, or historical records.
- Run affected targeted tests plus `just check`.

## Phase 5: Maintained Local Configuration Sweep

Target: maintained local configuration sources outside numbered SASE workspaces.

Purpose: update real user config sources after SASE can read `linked_repos`, without mass-editing stale worktrees.

Work:

- Search maintained config roots, not every numbered workspace clone:
  - `/home/bryan/.config/sase/sase.yml`;
  - `/home/bryan/.local/share/chezmoi/home/dot_config/sase/sase.yml`;
  - non-numbered maintained project checkouts found by targeted search.
- Update source-of-truth config files from `sibling_repos` to `linked_repos` once the installed/runnable SASE version
  accepts the new key.
- If a config is chezmoi-managed, update the chezmoi source and apply it rather than editing generated output only.
- Do not modify protected memory files without explicit approval.
- Record a handoff note listing any legacy configs intentionally left for later.

Verification:

- `rg -n "^sibling_repos:|sibling_repos:"` over maintained config roots.
- Confirm any remaining hits are intentionally deferred, historical, or compatibility tests/docs.
- Run the relevant lightweight SASE config command, such as `sase config show`, if available in the active environment.

## Phase 6: bob-cli Config Migration And Commit

Target repo: `/home/bryan/projects/github/bobs-org/bob-cli`.

Purpose: update bob-cli's SASE configuration after the SASE migration can parse `linked_repos`, and commit that repo's
change with the required commit workflow.

Prerequisite:

- The installed/runnable SASE used by agents must accept `linked_repos`. If not, stop instead of converting bob-cli
  early.

Work:

- Read bob-cli's repo-local `AGENTS.md`.
- Keep protected `memory/*.md` files unchanged unless explicit user approval is given.
- Change bob-cli `sase.yml` from:

  ```yaml
  sibling_repos:
  ```

  to:

  ```yaml
  linked_repos:
  ```

- Preserve the existing `bob-plugins` entry exactly aside from the key rename.
- Search bob-cli for live docs/config references to `sibling_repos`; update only current documentation if it describes
  the active config. Do not rewrite historical SDD records unless they are active handoff material.
- Verify with bob-cli's normal checks. Prefer `just check`; if unavailable or excessive, run the strongest targeted
  fallback and document the gap.
- Commit using `/sase_git_commit`, not raw `git commit`:
  - run `git status` and `git diff`;
  - write a commit message file;
  - run `sase_git_commit -M <message-file> -f sase.yml` plus any other intentionally changed bob-cli files;
  - verify `git status --short --branch` is clean and not ahead afterward.

Verification:

- `rg -n "^sibling_repos:|sibling_repos:" /home/bryan/projects/github/bobs-org/bob-cli`.
- bob-cli checks as above.
- Successful `sase_git_commit` result and clean final bob-cli status.

## Cross-Phase Acceptance Criteria

- `linked_repos` is the documented and configured name.
- Existing `sibling_repos` configs still resolve during the compatibility window.
- New and old env vars are both handled safely; stale inherited env cannot leak into child agents.
- Finalizer behavior is unchanged for dirty opened numbered repos and static advisory repos.
- Deferred-workspace agents still recompute related repo paths after claiming a workspace.
- SASE's own `sase-core` build path resolution prefers the new env var and remains backward compatible.
- Maintained local configs are either migrated or explicitly documented as deferred.
- bob-cli's `sase.yml` is migrated and committed with `/sase_git_commit`.
- Remaining "sibling" strings are either unrelated concepts, explicit compatibility aliases, or historical records.
