---
create_time: 2026-05-09 19:12:29
status: done
prompt: sdd/prompts/202605/remove_obsolete_plugin_repos.md
bead_id: sase-2k
tier: epic
---
# Remove Obsolete Plugin Repository References

## Goal

Remove all tracked references to the exact obsolete chat and Mercurial plugin repository/package names from:

- this repository (`sase_100`)
- the non-obsolete plugin repos: `../sase-github`, `../sase-telegram`, `../sase-nvim`
- the Rust core repo: `../sase-core`

The immediate failure mode is GitHub Actions trying to validate or access obsolete external repositories introduced by
the `sase-2j` pyvision external-repository work. The end state should be stronger than fixing one failing pragma: a
literal sweep for the exact obsolete repo/package names should be clean across the in-scope repos unless an intentionally
retained historical artifact is called out and approved during implementation.

## Current Reconnaissance

`sase-2j` is closed and points at `sdd/epics/202605/pyvision_external_repos.md`. That plan added repository URI
validation for pyvision pragmas and currently leaves one live failing pragma:

- `src/sase/integrations/agent_status_groups.py`: obsolete chat-plugin pyvision pragma

This repo also has live references to the obsolete repos in config, docs, tests, memory, and comments, including:

- `sase.yml`
- `AGENTS.md`
- `README.md`
- `memory/long/external_repos.md`
- `docs/plugins.md`
- `docs/vcs.md`
- `docs/workspace.md`
- `docs/configuration.md`
- `docs/ace.md`
- `tests/test_plugin_integration.py`
- `tests/test_commit_xprompt_append.py`
- `tests/test_xprompt_tags_lookup.py`
- `tests/test_sibling_commit_stop_hook.py`
- `tests/workflows/test_new_workflows.py`
- `tests/workflows/test_utils.py`
- `src/sase/integrations/agent_status_groups.py`
- `src/sase/ace/hooks/defaults.py`
- `src/sase/xprompt/tags.py`

There are many additional historical references under `sdd/epics`, `sdd/tales`, `sdd/research`, and
`sdd/beads/issues.jsonl`. These are version-controlled and therefore in scope for "all references", but they should be
handled separately from runtime/docs cleanup because they are historical records and can be noisy.

Initial direct sweeps found no exact obsolete repo/package name matches in:

- `../sase-core`
- `../sase-github`
- `../sase-telegram`
- `../sase-nvim`

Those repos still need an explicit phase because this plan's acceptance condition spans them.

## Scope Decisions

1. Remove references to the obsolete repository/package names, not every generic occurrence of the words "google",
   "Google", "Gemini", "Mercurial", or `hg`.
2. Do not edit the obsolete repos except possibly to inspect them. They are removal
   targets, not maintained outputs.
3. Prefer replacing obsolete external API validation with retained non-obsolete consumers or in-repo documentation. For
   the known pyvision pragma in `agent_status_groups.py`, keep `sase-telegram` if it still proves the public API, and
   remove the `retired chat plugin` pragma.
4. If removing retired Mercurial plugin references exposes dead Mercurial-only test fixtures or docs, either generalize them to
   provider-neutral examples or delete them. Do not keep a fake package name just to preserve old test wording.
5. Historical SDD cleanup should preserve useful project history where possible by rewriting references to generic
   labels such as "retired chat plugin" or "retired Mercurial plugin" only when the specific repo name is not needed for
   current operation. If a phase agent believes exact historical names must remain, it should stop and ask before
   leaving exceptions.

## Phase 1: Fix the CI Blocker and Live Runtime Surface

Owner: one agent instance focused only on live code/config/test surfaces in `sase_100`.

Primary objective: make GitHub Actions stop trying to access obsolete repositories while keeping pyvision meaningful.

Work:

1. Remove the `retired chat plugin` pyvision URI pragma from `src/sase/integrations/agent_status_groups.py`.
2. Run `just pyvision` early. If pyvision reports that `AgentStatusGroup`, `agent_status_bucket_glyph`, or
   `status_bucket_header` no longer have sufficient non-obsolete consumers, decide case-by-case:
   - retain the existing `sase-telegram` pragma if it proves the API;
   - replace the obsolete pragma with a real in-repo doc/reference if that is the actual current consumer;
   - make unused symbols private or delete them only if surrounding code/tests prove they are not part of the current
     integration surface.
3. Update tests that use `retired chat plugin` merely as a dirty sibling repo fixture. Use a non-obsolete sibling name such as
   `sase-telegram` or a neutral fake repo name, depending on what the test is proving.
4. Update tests that mention `retired Mercurial plugin` / `retired_mercurial_plugin` only as a plugin-discovery fixture. Prefer neutral synthetic
   plugin module names unless the test is specifically about legacy compatibility.
5. Update live comments/docstrings in `src/` and `tests/` that reference obsolete repos.
6. Verification:
   ```bash
   rg -n "sase-(gchat|google)|sase_(gchat|google)" src tests
   just install
   just pyvision
   just test
   ```

Acceptance:

- No `retired chat plugin`, `retired Mercurial plugin`, `retired_chat_plugin`, or `retired_mercurial_plugin` matches remain under `src/` or `tests/`.
- `just pyvision` no longer attempts to fetch or inspect `retired chat plugin` or `retired Mercurial plugin`.
- The focused runtime/test suite passes.

## Phase 2: Public Docs, Root Config, and Memory Cleanup

Owner: one agent instance focused on user-facing docs and always-loaded/dynamic memory in `sase_100`.

Primary objective: remove obsolete repos from current instructions and published docs so future agents and users do not
reintroduce them.

Work:

1. Update `sase.yml` mentor profile text so `cross_repo_impact` lists only maintained sibling repos: `../sase-github`,
   `../sase-telegram`, `../sase-nvim`, and `../sase-core` when relevant.
2. Update `AGENTS.md` and `memory/long/external_repos.md` to remove `retired Mercurial plugin` and not mention `retired chat plugin`.
3. Update `README.md` plugin diagrams/lists to remove `retired Mercurial plugin`.
4. Update plugin docs:
   - `docs/plugins.md`: remove the `retired Mercurial plugin` package row and any `jetski` provider claims.
   - `docs/workspace.md`: remove obsolete Mercurial workspace plugin references.
   - `docs/vcs.md`: remove install instructions and package-specific references to `retired Mercurial plugin`; if Mercurial concepts
     remain in core docs, frame them as legacy/provider-neutral behavior only if still true.
   - `docs/configuration.md`, `docs/ace.md`, and any nearby docs found by grep.
5. Update generated-skill or commit-workflow memory/docs only if they name `retired Mercurial plugin` / `retired_mercurial_plugin`; do not remove
   generic `/sase_hg_commit` documentation unless the phase agent proves that the skill itself is obsolete.
6. Verification:
   ```bash
   rg -n "sase-(gchat|google)|sase_(gchat|google)" AGENTS.md README.md docs memory sase.yml
   just docs-check
   ```

Acceptance:

- Current docs and memory no longer direct users or agents to obsolete repos.
- Documentation still accurately describes maintained plugin extension points.

## Phase 3: Historical SDD and Bead Record Sweep

Owner: one agent instance focused on version-controlled SDD/history in `sase_100`.

Primary objective: satisfy the "all references in this repo" requirement without mixing historical cleanup into live
code changes.

Work:

1. Sweep these paths for obsolete repo/package names:
   ```bash
   rg -n "sase-(gchat|google)|sase_(gchat|google)" sdd
   ```
2. For active or recent plan files that future agents may read, rewrite references to maintained replacements or generic
   retired-plugin labels.
3. For closed historical epics/tales/research:
   - prefer minimal rewrites that remove exact obsolete repo names while keeping enough context to understand the
     record;
   - avoid broad deletion of historical files unless they are generated prompt captures or clearly disposable;
   - keep bead JSON valid when editing `sdd/beads/issues.jsonl`.
4. Re-run SDD validation and markdown formatting checks after changes.
5. Verification:
   ```bash
   rg -n "sase-(gchat|google)|sase_(gchat|google)" sdd
   just sdd-validate
   just fmt-md-check
   ```

Acceptance:

- No obsolete repo/package name matches remain under `sdd/`, or every remaining match is explicitly documented as an
  approved exception.
- SDD metadata remains valid.

## Phase 4: Non-Obsolete Plugin Repos and `sase-core`

Owner: one agent instance focused on sibling repos, not `sase_100` implementation.

Primary objective: prove and maintain the cross-repo guarantee.

Repos in scope:

- `../sase-core`
- `../sase-github`
- `../sase-telegram`
- `../sase-nvim`

Work:

1. Run literal sweeps in each repo:
   ```bash
   rg -n "sase-(gchat|google)|sase_(gchat|google)" ../sase-core ../sase-github ../sase-telegram ../sase-nvim \
     --glob '!**/.git/**' --glob '!**/.pytest_cache/**'
   ```
2. If matches appear, remove or rewrite them according to the owning repo's conventions.
3. If a sibling repo is modified, run its required checks:
   - `../sase-core`: inspect available commands; prefer `cargo test --workspace` plus any repo-specific `just check` if
     present.
   - `../sase-github`: `just check`.
   - `../sase-telegram`: `just check`.
   - `../sase-nvim`: inspect available checks; run the repo's documented check command if present.
4. Do not touch `../retired chat plugin` or `../retired Mercurial plugin`.
5. Verification:
   ```bash
   git -C ../sase-core status --short
   git -C ../sase-github status --short
   git -C ../sase-telegram status --short
   git -C ../sase-nvim status --short
   ```

Acceptance:

- All maintained sibling repos are free of obsolete repo/package references.
- Checks pass in every modified sibling repo.

## Phase 5: Final Integration and Regression Gate

Owner: one final landing agent instance.

Primary objective: integrate the prior phases, catch missed references, and run the expensive repo-level checks once the
tree is coherent.

Work:

1. Run the final literal cross-repo sweep:
   ```bash
   rg -n "sase-(gchat|google)|sase_(gchat|google)" \
     . ../sase-core ../sase-github ../sase-telegram ../sase-nvim \
     --glob '!**/.git/**' --glob '!**/.pytest_cache/**'
   ```
2. Check specifically for obsolete pyvision external repository targets:
   ```bash
   rg -n "github\\.com/sase-org/sase-(gchat|google)|# pyvision: .*sase-(gchat|google)" .
   ```
3. Run full SASE validation:
   ```bash
   just install
   just check
   ```
4. If any sibling repo was modified by prior phases and has not been checked after rebasing/integration, re-run its
   check command.
5. Record final changed repos and commands run.

Acceptance:

- No unapproved references to `retired chat plugin`, `retired Mercurial plugin`, `retired_chat_plugin`, or `retired_mercurial_plugin` remain in the in-scope repos.
- SASE `just check` passes.
- All modified maintained sibling repos are checked.
- Final status clearly states that obsolete repos themselves were intentionally not edited.

## Suggested Phase-Agent Prompts

Phase 1 prompt:

> Implement Phase 1 from `sase_plan_remove_obsolete_plugin_repos.md`. Focus only on live `src/` and `tests/` references
> in `sase_100`, especially the failing `retired chat plugin` pyvision pragma. Do not edit docs or SDD history in this phase. Run
> the Phase 1 verification commands and report any pyvision-driven API decisions.

Phase 2 prompt:

> Implement Phase 2 from `sase_plan_remove_obsolete_plugin_repos.md`. Clean public docs, root config, and memory files
> in `sase_100` so they no longer mention `retired chat plugin` or `retired Mercurial plugin`. Do not edit `src/`, `tests/`, or SDD history in
> this phase unless required by formatting. Run the Phase 2 verification commands.

Phase 3 prompt:

> Implement Phase 3 from `sase_plan_remove_obsolete_plugin_repos.md`. Sweep version-controlled SDD and bead records in
> `sase_100` for obsolete repo/package names, preserving valid historical context while removing exact references. Run
> SDD validation and markdown formatting checks.

Phase 4 prompt:

> Implement Phase 4 from `sase_plan_remove_obsolete_plugin_repos.md`. Sweep `../sase-core`, `../sase-github`,
> `../sase-telegram`, and `../sase-nvim` for obsolete repo/package references. Fix any matches in the owning repo and
> run that repo's required checks. Do not edit `../retired chat plugin` or `../retired Mercurial plugin`.

Phase 5 prompt:

> Implement Phase 5 from `sase_plan_remove_obsolete_plugin_repos.md`. Run the final cross-repo sweeps and full SASE
> validation, fix any missed references, and provide the final changed-repo/check summary. Do not edit obsolete repo
> directories.
