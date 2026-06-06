---
create_time: 2026-06-06 09:04:01
bead_id: sase-4d
tier: epic
status: done
prompt: sdd/prompts/202606/github_project_aliases.md
---
# GitHub Project Alias Allocation Plan

## Context

Today `sase-github` resolves `#gh:owner/repo` by deriving:

- primary workspace: `~/projects/github/<owner>/<repo>/`
- SASE project record: `~/.sase/projects/<repo>/<repo>.sase`
- SASE project name: `<repo>`

That accidentally makes `#gh:<repo>` work after first use, but it also makes two GitHub repos with the same basename
impossible because the second owner/repo points at a different workspace for the same SASE project name.

The recent `PROJECT_ALIASES` support gives us a better model: GitHub owner/repo first-use should create or reuse a
collision-free canonical SASE project record, then attach a short alias that preserves the old shorthand experience.

One wording ambiguity in the request: it says `<name>_<N>`, but the availability rule and example use `<name>-<N>`
(`foo-2`). This plan follows the example and uses hyphenated aliases, starting duplicate numbering at 2.

## Target Behavior

For a first-use prompt like `#gh:foo-org/foo`:

1. SASE creates or reuses a canonical project record for that exact GitHub repo.
2. The record gets `WORKSPACE_DIR: ~/projects/github/foo-org/foo/`.
3. If `foo` is available as a project alias, the record gets `PROJECT_ALIASES: foo`.
4. Future launch-bound refs such as `#gh:foo` canonicalize to that canonical project before launch/history/artifact
   writes.

For a later first-use prompt like `#gh:bar-org/foo`:

1. SASE creates or reuses a different canonical project record for `bar-org/foo`.
2. Alias allocation sees `foo` is already occupied by a project name or alias.
3. It selects the first available hyphenated alias, e.g. `foo-2`, then `foo-3`, etc.
4. Future `#gh:foo-2` refs canonicalize to the `bar-org/foo` project.

Existing legacy basename projects remain valid. If `~/.sase/projects/foo/foo.sase` already points at
`~/projects/github/foo-org/foo/`, resolving `#gh:foo-org/foo` should reuse `foo` instead of migrating or renaming it.

## Phase 1: Shared Alias Allocation And Mutation Primitives

Primary repo: `sase`

Goal: create reusable project-alias services that are not tied to the `sase project` CLI handler.

Work:

- Move the reusable alias mutation logic currently embedded in `src/sase/main/project_handler.py` into a small service
  module, likely `src/sase/project_aliases.py` if it stays cohesive or a new `src/sase/project_registry.py` if the file
  would become too broad.
- Keep CLI behavior unchanged by making `project_handler.py` call the shared service.
- Add a pure allocator:
  - input: desired base alias, current `ProjectRecordWire` records, optional canonical project being updated.
  - output: available alias.
  - rules:
    - try `<name>` first;
    - if occupied, try `<name>-2`, `<name>-3`, ...;
    - occupied means any non-system real project name or any non-system project alias in any lifecycle state;
    - reject invalid base names with the existing SASE project-name validation.
- Add an idempotent locked mutation helper:
  - `ensure_project_alias_locked(project, alias, *, projects_root=None)` or equivalent.
  - It should preserve existing aliases and add only the missing alias.
  - It should use the normal ProjectSpec lock and Rust-backed `apply_project_aliases_update`.
  - It should validate against active, inactive, and sibling project records.
- Keep `PROJECT_ALIASES` validation strict: aliases still cannot equal their canonical project name, collide with a real
  project name, or collide with another project's alias.

Tests:

- Unit tests for allocation: available base, real-project collision, alias collision, inactive/sibling collisions,
  `foo`, `foo-2`, `foo-3` selection, and invalid base names.
- CLI regression tests proving `sase project alias add/remove/clear/list` still behave as before.
- Service tests proving the idempotent helper preserves existing aliases and writes sorted aliases.

Validation:

- In `sase`: `just install && just check` after implementation changes.

## Phase 2: GitHub First-Use Project Identity And Alias Creation

Primary repo: `sase-github`

Goal: update `resolve_gh_ref()` owner/repo mode so GitHub repos with duplicate basenames get distinct canonical SASE
projects and automatic aliases.

Work:

- Add a GitHub project identity helper in `src/sase_github/workspace_plugin.py` or a focused sibling module.
- For new owner/repo refs, use a stable canonical project name that includes the owner and repo and is a valid SASE
  project name. Recommended format: `gh_<owner>__<repo>`, with a deterministic suffix if that canonical name is already
  occupied by a different workspace.
- Before creating a new canonical record, scan all project records and reuse an existing record whose normalized
  `WORKSPACE_DIR` matches the derived primary GitHub workspace. This preserves legacy basename projects and makes
  repeated owner/repo resolution idempotent.
- If no matching record exists:
  - derive the canonical project name;
  - create/update that project file's `WORKSPACE_DIR`;
  - allocate the short alias from the repo basename using Phase 1's allocator;
  - write the alias with Phase 1's locked mutation helper.
- If a matching existing record is found:
  - keep its project name;
  - ensure a short alias only when it is valid and useful;
  - skip adding an alias equal to the existing canonical project name, because current validation intentionally rejects
    that and the real project name already resolves.
- Keep `#gh:<project-or-branch>` shorthand/change-spec resolution behavior intact for non-owner/repo refs.
- Make direct `resolve_gh_ref("foo-2")` robust by resolving project aliases before project-shorthand lookup, even if an
  upstream caller missed prompt canonicalization.

Tests:

- Existing `resolve_gh_ref("alice/myrepo")` tests updated for canonical project naming and alias writes.
- New tests for:
  - first owner/repo creates `WORKSPACE_DIR` plus `PROJECT_ALIASES: repo`;
  - second owner/repo with same repo basename creates a distinct canonical project and `PROJECT_ALIASES: repo-2`;
  - existing legacy basename project with matching workspace is reused and not renamed;
  - existing project with different workspace no longer raises the old `WORKSPACE_DIR conflict` for a duplicate GitHub
    basename;
  - alias lookup in shorthand mode resolves to the canonical project.

Validation:

- In `sase-github`: run its normal install/check/test command set, using this workspace's opened sibling path.

## Phase 3: Launch-Time Known-Project Resolution With Duplicate Basenames

Primary repo: `sase`

Goal: remove the remaining basename-only assumptions from fallback launch paths that run before or without the GitHub
workspace plugin.

Work:

- Update known-project owner/repo resolution in `src/sase/xprompt/_parsing.py` and/or
  `src/sase/agent/launch_projects.py` so `owner/repo` does not blindly collapse to `repo` when multiple projects could
  match.
- Prefer this resolution order for `owner/repo` refs:
  - exact known project name, for backward compatibility;
  - project whose `workspace_dir` matches `~/projects/github/<owner>/<repo>/`;
  - basename fallback only when it is unambiguous and preserves existing legacy behavior.
- Ensure `canonicalize_project_aliases_in_prompt()` still runs before xprompt expansion, prompt history writes, agent
  metadata writes, multi-prompt fan-out, mobile launch, TUI launch, and runner setup.
- Add tests that prove `#gh:foo`, `#gh:foo-2`, `#gh:foo-org/foo`, and `#gh:bar-org/foo` route to distinct canonical
  projects once aliases exist.
- Add multi-prompt and inactive-project tests if the touched code paths change behavior there.

Tests:

- Extend `tests/test_xprompt_aliases.py` for generated alias canonicalization.
- Extend `tests/test_xprompt_parsing.py` or add focused tests for owner/repo duplicate resolution.
- Extend `tests/test_cd_launch_from_cwd_known_project.py` and `tests/test_cd_multi_prompt_launch_resolution.py` for
  duplicate GitHub basenames and alias canonicalization.
- Keep existing owner/repo fallback tests passing for legacy single-project setups.

Validation:

- In `sase`: `just install && just check`.

## Phase 4: Documentation And Compatibility Notes

Primary repos: `sase`, `sase-github`

Goal: document the new model so users understand canonical project names, aliases, and duplicate GitHub repos.

Work:

- Update `sase` docs:
  - `docs/project_spec.md`: explain automatic GitHub aliases and collision suffixes.
  - `docs/xprompt.md`: update the "known projects / project aliases" section with duplicate basename examples.
  - `docs/cli.md`: mention that aliases may be generated automatically by providers, not only manually.
- Update `sase-github` docs:
  - `docs/architecture.md`: describe first-use canonical project naming and alias allocation.
  - `docs/configuration.md`: update "Project Files" so it no longer claims owner/repo refs always store metadata under
    `~/.sase/projects/<project>/<project>.sase`.
- Add a compatibility note:
  - existing basename projects are reused;
  - no automatic migration or rename is required;
  - users can inspect or adjust generated aliases with `sase project alias`.

Validation:

- Run relevant markdown/doc checks if available.
- Run full repo checks in any repo with code changes; docs-only changes can use targeted test/doc validation if the repo
  conventions allow it.

## Rollout Risks And Mitigations

- Risk: canonical project-name churn for existing users.
  - Mitigation: always detect and reuse an existing project by matching `WORKSPACE_DIR` before creating a new canonical
    name.
- Risk: alias allocation races when two agents first use duplicate repos at once.
  - Mitigation: perform final allocation and alias write while holding the target ProjectSpec lock, and re-read project
    records immediately before writing. If a race is still possible across two different project files, retry on alias
    validation conflict.
- Risk: fallback owner/repo lookup keeps routing by basename and defeats duplicate support.
  - Mitigation: add explicit duplicate owner/repo tests in launch, xprompt parsing, and multi-prompt paths.
- Risk: docs and UI show surprising canonical names like `gh_owner__repo`.
  - Mitigation: project-management surfaces already show aliases; docs should teach users to launch with aliases while
    treating canonical names as stable internal project records.
