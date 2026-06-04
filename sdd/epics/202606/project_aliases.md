---
create_time: 2026-06-04 10:31:44
status: done
prompt: sdd/prompts/202606/project_aliases.md
bead_id: sase-4c
tier: epic
---
# Plan: SASE Project Aliases

## Goal

Add first-class project aliases configured in ProjectSpec files. A prompt such as `#gh:bob ...` should be canonicalized
to `#gh:bob-cli ...` when the `bob-cli` project declares `bob` as an alias. Canonicalization must happen before launch
resolution, xprompt expansion, prompt history writes, and artifact writes so aliases do not appear in normal SASE
artifacts or launch output.

The first real use case is adding alias `bob` for existing project `bob-cli`.

## Current State

- ProjectSpec lifecycle metadata is owned by `sase-core` in `crates/sase_core/src/project_spec.rs` and exposed through
  `sase_core_rs`.
- Python code consumes project records through `src/sase/core/project_lifecycle_facade.py` and
  `src/sase/core/project_lifecycle_wire.py`.
- `sase project` currently manages lifecycle state and deletion only.
- ACE Project Management already lists all non-system projects and mutates lifecycle state through locked ProjectSpec
  helpers.
- Global `xprompt_aliases` already exist, but they are config-level raw xprompt aliases such as `#p -> #propose`. They
  are not per-project, and they do not solve `#gh:<alias> -> #gh:<project>`.
- The child runner writes `submitted_xprompt.md` before xprompt alias resolution and `raw_xprompt.md` after it. To meet
  the no-leak requirement, project alias canonicalization must happen in parent launch/query boundaries before the child
  process receives the prompt.

## Metadata Contract

Use a simple ProjectSpec header field before the first `NAME:` block:

```text
PROJECT_ALIASES: bob, docs
```

Rules:

- Missing `PROJECT_ALIASES` means no aliases.
- Values are comma-separated, trimmed, deduplicated, and stored sorted for stable writes.
- Alias names use the same syntax as SASE project names.
- An alias cannot equal its canonical project name.
- An alias cannot collide with any real project name or with an alias assigned to another project, across all non-system
  project records and all lifecycle states.
- Invalid or duplicate manually edited aliases should surface as parse warnings on the project record; mutation helpers
  should reject invalid writes.

This intentionally keeps aliases project-scoped and independent from global `xprompt_aliases`.

## Phase 1: Core ProjectSpec Alias Contract

Owner: one agent working in this repo plus the matching `sase-core_11` workspace.

Implementation:

- Open the sibling core workspace with `sase workspace open -p sase-core 11` before editing core files.
- Extend `sase-core` ProjectSpec parsing in `crates/sase_core/src/project_spec.rs`:
  - Add `PROJECT_ALIASES:` parsing before the first `NAME:`.
  - Add `aliases: Vec<String>` to `ProjectRecordWire`.
  - Add an `apply_project_aliases_update(content, aliases)` helper that inserts/replaces/removes the header line using
    the same line/newline preservation helpers as lifecycle updates.
  - Preserve insertion order around existing metadata by placing `PROJECT_ALIASES` before `RUNNING:` and before the
    first `NAME:` when adding it.
  - Bump the lifecycle/project record wire schema version if the project record contract is treated as versioned.
- Expose the new Rust helper from `crates/sase_core_py/src/lib.rs`.
- Update Python wire/facade code:
  - Add `aliases: list[str]` to `ProjectRecordWire`.
  - Add `apply_project_aliases_update(content, aliases)` to `project_lifecycle_facade.py`.
  - Keep missing `aliases` backward-compatible for stale test fakes and older bindings where feasible, but fail clearly
    when a mutating alias helper is missing.

Tests:

- Rust unit tests for parsing, updating, removing, newline preservation, duplicate/invalid warnings, and record listing.
- Python facade tests for dict conversion, binding calls, stale/missing binding behavior, and real-extension behavior.
- Update existing project lifecycle tests and fakes to include `aliases`.

Validation:

```bash
just install
pytest tests/test_core_facade/test_project_lifecycle.py
just check
```

In `sase-core_11`, run the focused Rust tests plus that repo's standard check target.

## Phase 2: Early Project Alias Canonicalization

Owner: one agent in the main SASE repo after Phase 1 lands.

Implementation:

- Add a shared Python helper, for example `sase.project_aliases`, with:
  - `load_project_alias_map(projects_root=None) -> dict[str, str]`.
  - `resolve_project_alias_ref(ref) -> str`.
  - `canonicalize_project_aliases_in_prompt(prompt) -> str`.
- Build the alias map from `list_project_records(sase_projects_dir(), "all", include_home=False)`, excluding `home` and
  system-managed records.
- Rewrite only exact workspace/VCS reference args:
  - `#gh:bob` -> `#gh:bob-cli`
  - `#gh_bob` -> `#gh:bob-cli` or another canonical colon form
  - `#gh(bob)` -> `#gh(bob-cli)`
  - Preserve `!!` and `??` markers.
  - Do not rewrite owner/repo paths such as `#gh:bbugyi200/bob`, partial names such as `#gh:bob-tools`, xprompt names,
    prose, or fenced code examples.
- Apply canonicalization before existing xprompt alias resolution and before VCS matching in:
  - `sase.xprompt.processor.resolve_xprompt_aliases` or an earlier wrapper used by xprompt preprocessing.
  - `sase.llm_provider.preprocessing.preprocess_prompt_early`.
  - TUI launch body before multi-prompt parsing, history writes, VCS resolution, fan-out planning, and spawn.
  - `sase.agent.launch_cwd.launch_agents_from_cwd` before `submitted_query`, multi-prompt parsing, history writes, and
    spawn.
  - `sase.main.query_handler.run_query` and `_resolve_vcs_cwd` before history/artifact writes.
  - `sase.main.xprompt_handler` so `sase xprompt expand '#gh:bob ...'` displays canonical refs.
  - `sase.axe.run_agent_runner_setup.preprocess_prompt_xprompts` as a defensive child-side fallback, while relying on
    parent-side canonicalization to protect `submitted_xprompt.md`.
  - Multi-prompt/fan-out paths that resolve segment VCS context before child spawn.
- Avoid adding alias awareness to GitHub, bare-git, or other VCS provider plugins. Providers should receive canonical
  project names only.

Tests:

- Unit tests for prompt canonicalization, including colon, underscore, paren, `!!`/`??`, fenced code, no partial match,
  real-project-name collision rejection, duplicate alias rejection, inactive-project aliases, and multiple providers.
- Launch tests proving `#gh:bob` spawns with:
  - prompt `#gh:bob-cli ...`
  - project name `bob-cli`
  - `vcs_ref == ("gh", "bob-cli")`
  - history sort key/display name `bob-cli`
- Runner setup tests proving both `submitted_xprompt.md` and `raw_xprompt.md` contain `bob-cli`, not `bob`.
- `sase xprompt expand` and `sase run` tests proving canonical text appears before expansion/output.

Validation:

```bash
just install
pytest tests/test_xprompt_aliases.py tests/test_cd_launch_from_cwd_known_project.py tests/main/test_xprompt_handler.py
just check
```

## Phase 3: `sase project` CLI Support

Owner: one agent in the main SASE repo after Phases 1 and 2 land.

Implementation:

- Extend `sase project` with alias subcommands:

```bash
sase project alias list [PROJECT] [-j|--json]
sase project alias add PROJECT ALIAS
sase project alias remove PROJECT ALIAS
sase project alias clear PROJECT
```

- Reuse the Phase 1 locked ProjectSpec updater and the Phase 2 alias-conflict validator.
- Update `sase project show` JSON and text output to include aliases.
- Update `sase project list --json` to include aliases through the existing record wire.
- Consider a compact `ALIASES` column in non-JSON `project list` only if it stays readable; otherwise keep aliases in
  `show` and `alias list`.
- Mutation behavior:
  - Reject `home` and system-managed projects.
  - Reject unknown projects.
  - Reject alias conflicts with clear messages naming the owning project.
  - Do not require lifecycle state to be active.
  - Lock and atomically update the ProjectSpec.

Tests:

- Parser tests for every alias subcommand and `-j|--json`.
- Handler tests for add, remove, clear, JSON list, text list, conflict with existing project, conflict with another
  alias, invalid alias, missing project, and system-managed project.
- Regression tests that lifecycle commands still parse and mutate exactly as before.

Validation:

```bash
just install
pytest tests/main/test_project_parser.py tests/main/test_project_handler.py
just check
```

## Phase 4: ACE Project Management Alias UI

Owner: one agent in the main SASE repo after Phases 1 through 3 land.

Implementation:

- Add aliases to Project Management display:
  - Show alias count or compact aliases in each row if column width allows.
  - Show the full alias list in the detail pane.
  - Include aliases in the text filter haystack.
- Add a modal-local binding, preferably `A`, labeled `Aliases`.
- Add a small alias editor modal for the selected project:
  - One input with the current comma-separated aliases.
  - Submit replaces the selected project's alias set through the same locked helper used by the CLI.
  - Empty input clears aliases after a confirmation or explicit submit wording.
  - Cancel leaves the ProjectSpec untouched.
  - Alias editing targets only the highlighted project, not the marked bulk set.
- After mutation, reload project records, preserve selection, notify, and refresh app data using the existing project
  lifecycle refresh hooks.
- Keep lifecycle mark behavior unchanged.

Tests:

- Rendering tests for row/detail/footer alias affordances.
- Filter test matching by alias.
- Modal test for opening alias editor from Project Management, submitting a new alias list, reloading records, and
  preserving selection.
- Error tests for invalid alias and alias conflict surfacing as status/notification without mutating records.
- Regression tests for marks, activate/deactivate, delete, edit, and reload behavior.

Validation:

```bash
just install
pytest tests/ace/tui/modals/test_project_management_modal_filtering.py \
  tests/ace/tui/modals/test_project_management_modal_states.py \
  tests/ace/tui/modals/test_project_management_modal_edit.py
just check
```

## Phase 5: Docs, Rollout, And `bob` Alias

Owner: one final agent after Phases 1 through 4 land.

Implementation:

- Update docs:
  - `docs/project_spec.md`: document `PROJECT_ALIASES`, validation rules, CLI commands, TUI behavior, and the no-leak
    canonicalization expectation.
  - `docs/xprompt.md`: distinguish project aliases from global `xprompt_aliases`; mention that VCS refs are
    canonicalized before xprompt expansion.
  - `docs/architecture.md` or nearby launch docs if needed to record the early canonicalization point.
- Add or update any JSON schema/config docs only if a new config field is introduced. The planned design uses
  ProjectSpec metadata, so `config/sase.schema.json` should not need project alias entries.
- Use the new CLI to add the first real alias:

```bash
sase project alias add bob-cli bob
```

- Verify the live ProjectSpec has canonical metadata and no manually introduced formatting damage.
- Run a focused dry-run or mocked launch test showing `#gh:bob` canonicalizes to `#gh:bob-cli` before artifacts/history.
  Avoid launching a real agent unless explicitly approved.

Tests and validation:

```bash
just install
pytest tests/test_xprompt_aliases.py tests/main/test_project_handler.py tests/ace/tui/modals
just check
```

Manual checks:

```bash
sase project show bob-cli --json | jq '.aliases'
sase xprompt expand '#gh:bob #p' | head
```

Expected result: user-facing launch/history/artifact surfaces show `bob-cli`; only project management and
`sase project alias ...` management output should show that `bob` is configured as an alias.

## Cross-Phase Acceptance Criteria

- `PROJECT_ALIASES: bob` in `~/.sase/projects/bob-cli/bob-cli.sase` makes `#gh:bob` behave exactly like `#gh:bob-cli`.
- Aliases are never persisted in `submitted_xprompt.md`, `raw_xprompt.md`, `agent_meta.json`, embedded workflow
  metadata, prompt history, display names, history sort keys, or VCS refs.
- Alias configuration is available from both `sase project` and the ACE Project Management panel.
- Alias resolution is provider-neutral at the launch/xprompt boundary; GitHub receives canonical refs and does not need
  provider-specific alias logic.
- Existing global `xprompt_aliases` continue to work and remain independent.
- Inactive project aliases can still activate through the existing known-project launch flow.
- Alias conflicts fail loudly instead of creating ambiguous routing.
