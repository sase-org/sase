---
create_time: 2026-05-22 10:55:24
status: done
prompt: sdd/prompts/202605/just_fmt_check_prettier_pin.md
---
# Plan: Stabilize `_just_fmt_check`

## Context

The `sase/fix_just` workflow runs `just fmt-check` inside an ephemeral workspace, not necessarily the checkout where a
human just ran the command. The recent failing run launched in `/home/bryan/projects/github/sase-org/sase_15/`.

`just fmt-check` passes in `sase_13` and now also passes in `sase_15`, but the commit history shows the recurring
failure pattern:

- `sase/fix_just` creates repeated `chore: run \`just fmt\`` commits.
- Those commits repeatedly touch only Markdown table alignment in `docs/ace.md` and `docs/rust_backend.md`.
- Adjacent commits flip the same table spacing back and forth.

The repo currently invokes bare `prettier` from `PATH`:

- `Justfile` uses `prettier --write/check ...`.
- GitHub Actions installs `prettier` globally without a version pin.
- There is no repo-local `package.json` or lockfile pinning the formatter.

That makes Markdown formatting dependent on whichever `prettier` installation a SASE agent, local shell, or CI runner
happens to resolve. This explains why `just fmt-check` can pass locally while `_just_fmt_check` later reports
`success=false` in ACE.

## Approach

Make Markdown formatting repo-local and deterministic.

1. Add a repo-local Node formatter manifest.
   - Add `package.json` with an exact `prettier` dev dependency.
   - Add `package-lock.json` so CI and agent workspaces install the same formatter.
   - Add `node_modules/` to `.gitignore`.

2. Update the Justfile Markdown recipes.
   - Add a private `_setup-prettier` recipe that runs `npm ci --no-audit --no-fund` when the local Prettier binary is
     missing.
   - Change `fmt-md` and `fmt-md-check` to depend on `_setup-prettier`.
   - Replace bare `prettier` calls with the repo-local `node_modules/.bin/prettier`.

3. Update CI Markdown formatting setup.
   - Remove or replace the unpinned global `npm install -g prettier` step.
   - Let `just fmt-md-check` use the same locked local formatter as every other environment.

4. Normalize the currently tracked Markdown state with the pinned formatter.
   - Run the pinned formatter/check after the Justfile change.
   - Keep any resulting docs changes limited to deterministic formatting output.

5. Verify.
   - Run `just install` as required for this ephemeral workspace.
   - Run `just fmt-check` to prove the pinned formatter accepts the tree.
   - Run `just check` before finishing because this repo was changed.

## Expected Result

`_just_fmt_check` stops failing due to environment-specific Markdown formatting because every local shell, ACE workflow
workspace, and CI job uses the same locked Prettier version.
