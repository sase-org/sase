---
create_time: 2026-03-24 00:26:19
status: wip
bead_id: sase-9
prompt: sdd/prompts/202603/unified_vcs_commit.md
---

# Plan: Unified VCS Commit Prompts

## Overview

Replace all VCS-specific commit/propose/cl xprompt workflows (`#commit`, `#propose`, `#cl` in retired Mercurial plugin; `#pr` in
sase-github) with three unified, built-in xprompts (`#commit`, `#propose`, `#pr`) that work across all VCS providers.
The built-in xprompts set environment variables and provide VCS-agnostic prompt content; VCS-specific behavior is
delegated to plugin hooks and tagged xprompts.

## Current State

- **retired Mercurial plugin**: Has `#commit` (amend CL with COMMITS entry), `#propose` (create proposal), `#cl` (create CL)
  workflows. Each injects `#no_cl_ops #cldd`, checks for changes, runs VCS-specific scripts.
- **sase-github**: Has `#pr` (create branch + PR via `gh`) workflow. Creates ChangeSpec, pushes branch, runs
  `gh pr create`.
- **sase core**: Has `sase commit` (creates commits with description formatting, changespec, upload) and `sase amend` (3
  modes: amend, propose, accept). Has `sase_commit_stop_hook` that runs quality checks (lint, test, fmt) and blocks if
  uncommitted changes remain.
- **chezmoi**: Has `ccommit` script (the `/commit` skill), `chez_stop_hook` (chezmoi repo validation), and per-project
  Codex stop hook config.

## Target State

1. Three built-in xprompts (`#commit`, `#propose`, `#pr`) with VCS-agnostic prompt content
2. New xprompt `environment` field sets `$SASE_COMMIT_METHOD` (and `$SASE_BUG_ID` for `#pr`)
3. VCS-specific content appended via new tags (`append_to_pr`, `append_to_commit_and_propose`)
4. `sase commit` rewritten: accepts JSON payload, dispatches via plugin hooks using `$SASE_COMMIT_METHOD` +
   `$SASE_VCS_PROVIDER`
5. `sase_commit_stop_hook` rewritten: detects changes, instructs agent to use `/sase_<vcs>_commit` skill
6. Quality checks moved to `sase_core_stop_hook` (sase repo only)
7. `sase amend` removed
8. Old VCS-specific workflows removed from plugins

## Commit Method Semantics per VCS

| Method                | `#git` (bare)               | `#gh` (GitHub)                       | `#hg` (Google)           |
| --------------------- | --------------------------- | ------------------------------------ | ------------------------ |
| `create_commit`       | git commit + push           | git commit + push                    | hg amend (COMMITS entry) |
| `create_proposal`     | git commit + push           | git commit + push                    | create proposal on CL    |
| `create_pull_request` | branch + ChangeSpec (no PR) | branch + ChangeSpec + `gh pr create` | create new CL            |

---

## Phase 1: xprompt `environment` field

**Goal**: Add support for an `environment` field on xprompt workflows that sets environment variables for the entire
agent session.

**Scope**: sase core only.

### Files to modify

- `src/sase/xprompt/workflow_models.py` — Add `environment: dict[str, str]` field to `Workflow` dataclass
- `src/sase/xprompt/workflow_loader_parse.py` — Parse `environment` from workflow YAML
- `src/sase/xprompts/workflow.schema.json` — Add `environment` to JSON schema
- `src/sase/xprompt/workflow_executor.py` — Inject env vars into `os.environ` at workflow start (before any steps run).
  The values support jinja2 templating resolved against the workflow's input args.
- Tests: Add tests for environment field parsing, jinja2 rendering in env values, and env var injection during execution

### Design Details

- **Scope**: Workflow-level (not step-level). Env vars are set once at the start of the workflow and persist for the
  entire agent session.
- **Jinja2 support**: Environment values are rendered as jinja2 templates with the workflow's input args as context.
  Example: `SASE_BUG_ID: "{{ bug_id }}"`.
- **Overwrite policy**: If an env var is already set, the workflow's value overwrites it (workflow-specific config takes
  precedence).

### Example

```yaml
input:
  bug_id: { type: int, default: 0 }

environment:
  SASE_COMMIT_METHOD: create_pull_request
  SASE_BUG_ID: "{{ bug_id }}"

steps:
  - name: inject
    prompt_part: |
      Make the requested changes...
```

### Verification

- `just check` passes
- New unit tests pass for environment field parsing, jinja2 rendering, and env var injection

---

## Phase 2: VCS-specific append tags + built-in commit xprompts

**Goal**: Add two new xprompt tags (`append_to_pr`, `append_to_commit_and_propose`) and create the three built-in commit
xprompts that use them.

**Scope**: sase core + retired Mercurial plugin + sase-github.

### Part A: New XPromptTag values + append logic

**Files to modify in sase core:**

- `src/sase/xprompt/tags.py` — Add `append_to_pr` and `append_to_commit_and_propose` to `XPromptTag` enum
- `src/sase/xprompt/processor.py` (or wherever xprompt expansion happens) — When expanding a built-in commit xprompt
  (`#commit`, `#propose`, `#pr`), look up xprompts tagged with the appropriate append tag using VCS-aware disambiguation
  (same logic as `diff_file` tag: prefer xprompts from the same plugin as the active VCS workflow). Append their content
  to the built-in xprompt's `prompt_part`.
- Tests for tag-based content appending with VCS disambiguation

### Part B: Built-in commit xprompts

**Files to create in sase core (`src/sase/xprompts/`):**

- `commit.yml` — Sets `$SASE_COMMIT_METHOD=create_commit`. Has a `prompt_part` step with VCS-agnostic instructions for
  making changes and preparing a commit. Content should be similar to the instruction portion of the current retired Mercurial plugin
  `#commit` workflow (minus VCS-specific operations).
- `propose.yml` — Sets `$SASE_COMMIT_METHOD=create_proposal`. Same prompt_part as `#commit` but for proposals.
- `pr.yml` — Sets `$SASE_COMMIT_METHOD=create_pull_request`. Input: `name` (word), `bug_id` (int, default: 0). Sets
  `$SASE_BUG_ID` via environment field. Prompt_part instructs agent to make changes for a new CL/PR.

**Important**: These built-in xprompts must NOT conflict with the existing VCS-specific workflows during the migration
period. The old workflows will be removed in Phase 5. During the transition, the built-in xprompts will shadow the
plugin-provided ones due to loading priority (built-in xprompts load from `src/sase/xprompts/` which is checked before
plugin packages). Verify this loading priority is correct; if not, adjust.

### Part C: Plugin tagged xprompts

**Files to create/modify in retired Mercurial plugin:**

- Tag existing `#no_cl_ops` xprompt (in `default_config.yml`) with `append_to_pr`
- Create new `#no_cl_ops_and_cldd` xprompt tagged with `append_to_commit_and_propose`, content: `#no_cl_ops #cldd`

**Files to create in sase-github:**

- Create `#prdd` xprompt tagged with `append_to_commit_and_propose`. This xprompt works like `#cldd` but for GitHub:
  uses `gh` to fetch PR description and `git` to create the diff file. Content should use `#x(...)` expansion syntax
  similar to `#cldd`.

### Verification

- `just check` passes in sase core
- Tag lookup with VCS hint returns correct tagged xprompts
- Built-in xprompts expand correctly with appended VCS-specific content
- No conflicts with existing VCS-specific workflows during migration

---

## Phase 3: `sase commit` rewrite + new hookspecs + remove `sase amend`

**Goal**: Rewrite `sase commit` to be VCS-agnostic, accepting a JSON payload and dispatching via plugin hooks. Remove
`sase amend`.

**Scope**: sase core + retired Mercurial plugin + sase-github.

### Part A: New hookspecs

**Files to modify in sase core:**

- `src/sase/vcs_provider/_hookspec.py` — Add new hookspecs:
  - `vcs_create_commit(payload: dict, cwd: str) -> tuple[bool, str | None]`
  - `vcs_create_proposal(payload: dict, cwd: str) -> tuple[bool, str | None]`
  - `vcs_create_pull_request(payload: dict, cwd: str) -> tuple[bool, str | None]`
- `src/sase/vcs_provider/_base.py` — Add corresponding abstract methods to `VCSProvider`
- `src/sase/vcs_provider/_plugin_manager.py` — Add dispatch methods

### Part B: `sase commit` rewrite

**Files to modify:**

- `src/sase/main/cl_handler.py` — Rewrite `handle_commit_command` to:
  1. Parse JSON payload from argument (positional arg or stdin)
  2. Read `$SASE_COMMIT_METHOD` (or `--method` override)
  3. Read `$SASE_VCS_PROVIDER` to get the VCS provider
  4. Dispatch to the appropriate `vcs_create_*` hook based on method
  5. Handle ChangeSpec creation/update (VCS-agnostic parts)
- `src/sase/main/parser_commands.py` — Update commit parser:
  - Accept JSON payload as positional arg
  - Add `--method` option to override `$SASE_COMMIT_METHOD`
  - Remove old positional args that are now in the JSON payload
- `src/sase/workflows/commit/workflow.py` — Major rewrite or replacement. The VCS-agnostic orchestration (ChangeSpec
  management, description formatting, project file updates) stays in core. VCS-specific operations (actual commit/amend,
  upload, mail) move to plugin hooks.

### Part C: Plugin hook implementations

**retired Mercurial plugin (`src/retired_mercurial_plugin/plugin.py`):**

- `vcs_create_commit` — Amend CL with COMMITS entry (port from current `#commit` workflow's bash/python steps)
- `vcs_create_proposal` — Create proposal on CL (port from current `#propose` workflow)
- `vcs_create_pull_request` — Create new CL (port from current `#cl` workflow)

**sase-github (`src/sase_github/plugin.py`):**

- `vcs_create_commit` — `git commit` + `git push`
- `vcs_create_proposal` — Same as create_commit for GitHub
- `vcs_create_pull_request` — Create branch + ChangeSpec + `gh pr create`

**bare_git (`src/sase/vcs_provider/plugins/bare_git.py`):**

- `vcs_create_commit` — `git commit` + `git push`
- `vcs_create_proposal` — Same as create_commit
- `vcs_create_pull_request` — Create branch + ChangeSpec (no actual PR)

### Part D: Remove `sase amend`

- `src/sase/main/cl_handler.py` — Remove `handle_amend_command`
- `src/sase/main/parser_commands.py` — Remove amend subcommand parser
- `src/sase/workflows/amend.py` — Delete file
- `src/sase/workflows/accept.py` — Delete if only used by amend --accept (verify first)
- Tests — Remove amend tests, add commit rewrite tests

### JSON Payload Schemas

**create_commit:**

```json
{
  "message": "commit message",
  "files": ["file1.py", "file2.py"],
  "note": "optional COMMITS note"
}
```

**create_proposal:**

```json
{
  "message": "proposal description",
  "files": ["file1.py", "file2.py"],
  "note": "optional note"
}
```

**create_pull_request:**

```json
{
  "name": "cl_or_pr_name",
  "description": "CL/PR description",
  "files": ["file1.py", "file2.py"],
  "wip": true
}
```

(These schemas are illustrative. The exact fields should be determined by examining what the current VCS-specific
workflows pass to their scripts and what the plugin hooks need.)

### Verification

- `just check` passes in sase core, retired Mercurial plugin, sase-github
- `sase commit '{"message": "test", "files": []}' --method=create_commit` dispatches correctly
- `sase amend` no longer exists
- Plugin hooks are called correctly for each VCS provider

---

## Phase 4: Stop hooks + commit skills (chezmoi)

**Goal**: Split the current stop hook into quality checks (sase-only) and commit orchestration (universal). Create new
`/sase_<vcs>_commit` skills.

**Scope**: sase core + chezmoi repo.

### Part A: `sase_core_stop_hook` (quality checks)

**Files to create/modify in sase core:**

- `tools/sase_core_stop_hook` — New script containing the quality check logic extracted from the current
  `sase_commit_stop_hook`: auto-formatting (`just fmt-py`, `just fmt-md`), linting (`just lint`), testing (`just test`),
  pyvision, pylimit. This hook is only configured for the sase repo.

**Files to modify in chezmoi:**

- Configure `sase_core_stop_hook` as a Stop hook in the sase project's Claude settings (likely in the chezmoi-managed
  Claude project settings for sase). Also configure for Codex if needed (the user mentioned a workaround may be needed).

### Part B: `sase_commit_stop_hook` rewrite

**Files to modify in sase core:**

- `tools/sase_commit_stop_hook` — Major rewrite. New behavior:
  1. Check `$SASE_COMMIT_METHOD` — if not set, exit 0 (not a commit workflow)
  2. Check for uncommitted file changes
  3. If changes exist, instruct the agent to use its `/sase_<vcs>_commit` skill (determine VCS from
     `$SASE_VCS_PROVIDER`)
  4. Block the agent (exit 2 for Claude, JSON for Codex) but only ONCE per session (use a marker file like the current
     hook does with deduplication)
  5. If no changes, exit 0

### Part C: New `/sase_<vcs>_commit` skills

**Files to create in chezmoi (for each LLM provider: Claude, Codex, Gemini):**

- `/sase_git_commit` skill — Instructs the agent to:
  1. Determine which files to commit
  2. Construct the JSON payload for `sase commit`
  3. Run `sase commit '<json>' --method=<method>` (reading `$SASE_COMMIT_METHOD`)
  - This skill is shared between `#git` and `#gh` VCS workflows (verify this works; they may need slight differences for
    PR creation)

- `/sase_hg_commit` skill — Same pattern but for Mercurial/Google VCS

**Files to modify in chezmoi:**

- Remove or update the old `/commit` skill (`ccommit` script) — it gets replaced by `/sase_git_commit`
- Update Claude/Codex/Gemini settings to register the new skills

### Verification

- Stop hook correctly blocks once when changes are detected
- Stop hook correctly identifies VCS type and instructs agent to use right skill
- Quality checks run correctly via `sase_core_stop_hook` (sase repo only)
- Skills correctly construct JSON and call `sase commit`
- `chezmoi apply` succeeds

---

## Phase 5: Cleanup + migration

**Goal**: Remove old VCS-specific workflows, old commands, and verify end-to-end.

**Scope**: sase core + retired Mercurial plugin + sase-github + chezmoi.

### Part A: Remove old workflows from retired Mercurial plugin

- Delete `src/retired_mercurial_plugin/xprompts/commit.yml`
- Delete `src/retired_mercurial_plugin/xprompts/propose.yml`
- Delete `src/retired_mercurial_plugin/xprompts/cl.yml`
- Remove any scripts only used by these workflows (e.g., `retired_mercurial_plugin_commit_workflow`, `sase_propose_workflow`,
  `sase_cl_workflow` — verify these aren't used elsewhere)
- Update `default_config.yml` if any xprompts defined there are now obsolete

### Part B: Remove old workflows from sase-github

- Delete `src/sase_github/xprompts/pr.yml` (replaced by built-in `#pr`)
- Remove any scripts only used by the old `#pr` workflow (e.g., `pr_create_changespec.py` — but this may still be needed
  if the new `vcs_create_pull_request` hook uses it)
- Update `default_config.yml` if needed

### Part C: Remove `#gcommit` from sase core

- If a `#gcommit` built-in xprompt exists, remove it (replaced by the new `#commit`)
- Grep for any references to `gcommit` and update/remove

### Part D: Clean up old commit infrastructure

- Remove `ccommit` script from chezmoi if fully replaced by `/sase_git_commit`
- Remove old `/commit` skill definitions from chezmoi
- Update `CLAUDE.md` / `AGENTS.md` if they reference old workflows
- Update any documentation referencing `sase amend`, old `#commit`/`#cl`/`#pr` workflows

### Part E: End-to-end verification

- Test `#git:repo #commit` flow end-to-end
- Test `#gh:repo #pr(name=test)` flow end-to-end
- Test `#hg:workspace #commit` flow end-to-end (if possible in test environment)
- Verify stop hooks work correctly for all VCS types
- Verify no regressions in existing workflows (`#gh`, `#hg`, `#git`)

### Verification

- `just check` passes in all repos (sase core, retired Mercurial plugin, sase-github)
- No references to old workflows remain (grep for old workflow names)
- End-to-end flows work for all VCS providers
