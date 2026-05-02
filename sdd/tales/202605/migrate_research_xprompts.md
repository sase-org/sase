---
create_time: 2026-05-02 14:03:29
status: done
---
# Migrate Research XPrompts To Built-In Defaults

## Context

The repo currently defines three research-related xprompts in the project-local `sase.yml`:

- `research`
- `research/more`
- `research/prompt`

`src/sase/default_config.yml` already carries built-in xprompts under the same top-level `xprompts:` section, bracketed
by `# keep-sorted start/end`.

The xprompt loader treats these sources differently:

- Built-in `default_config.yml` entries are loaded with source label `default_config` and keep their literal names.
- Project-local `./sase.yml` entries are loaded with source label `local_config`; when a project is detected, their
  names are prefixed with the project name, e.g. this repo's local `research` becomes `sase/research`.
- Later config sources override earlier config sources, so leaving duplicate entries in `sase.yml` would continue to
  shadow the new built-ins in this repo.

Because `research/prompt` currently references `#sase/research`, moving it to the built-in config should also change
that embedded reference to `#research`. Otherwise the built-in prompt would depend on this repo's project-local
namespace and would not work correctly as a default for other projects.

## Goals

1. Promote the three research xprompts from project-local config to built-in defaults.
2. Preserve the user-facing prompt content and typed input behavior.
3. Remove the duplicate project-local definitions so the built-ins are the source of truth.
4. Add focused regression coverage that proves the new built-ins load as expected and that `research/prompt` points at
   the built-in `#research`.
5. Run the repo-required verification after changes.

## Non-Goals

- Do not change xprompt loader precedence or namespacing rules.
- Do not introduce new xprompt fields, tags, aliases, or schemas.
- Do not move these prompts into standalone `src/sase/xprompts/*.yml` workflow files unless a later design explicitly
  chooses that model.
- Do not modify unrelated local xprompts such as `docs`, `gact`, or `remember`.

## Implementation Plan

1. Edit `src/sase/default_config.yml`.
   - Add `research`, `research/more`, and `research/prompt` under the existing `xprompts:` block.
   - Keep the section sorted with the surrounding built-ins. The natural placement is after `prompt/review` and before
     `review`.
   - Preserve the structured `input: { prompt: text }` behavior for `research/prompt`.
   - Change the embedded reference in `research/prompt` from `#sase/research` to `#research` so the built-in prompt
     composes with the built-in companion xprompt.

2. Edit the repo-local `sase.yml`.
   - Remove only the three migrated `research*` xprompt entries.
   - Leave the surrounding `xprompts:` section, keep-sorted markers, and other entries intact.

3. Add a focused loader regression test.
   - Extend an existing xprompt/config loader test file rather than creating a broad new suite.
   - Assert `get_all_prompts(project=None)` includes:
     - `research`
     - `research/more`
     - `research/prompt`
   - Assert the prompts have `source_path == "default_config"`.
   - Assert `research/prompt` has one `prompt` input of type `TEXT`.
   - Assert the `research/prompt` body contains `#research` and does not contain `#sase/research`.

4. Verification.
   - Run `just install` first, per repo workspace guidance.
   - Run a focused test for the loader coverage added above.
   - Run `just check` before reporting completion, per repo instructions.

## Risk And Mitigation

- **Risk: namespace regression for existing `#sase/research` users.** The current namespaced form exists only because
  the prompts live in this repo's project-local config. After migration, the built-in canonical name is `#research`. Any
  existing references to `#sase/research` outside historical prompt snapshots may need a follow-up alias or
  compatibility shim, but that is outside the minimal migration unless current tests or docs prove it is an active
  contract.

- **Risk: duplicate shadowing.** If the local `sase.yml` entries remain, this repo will still use the local versions
  rather than the built-ins. Removing them is part of the migration.

- **Risk: sorted-block churn.** Both config files use keep-sorted markers. Keep edits localized and preserve ordering to
  avoid format noise.

## Acceptance Criteria

- `src/sase/default_config.yml` contains the three research xprompts.
- The repo-local `sase.yml` no longer contains `research`, `research/more`, or `research/prompt` under `xprompts:`.
- `research/prompt` composes with `#research`, not `#sase/research`.
- Focused xprompt loader tests pass.
- `just check` passes after `just install`.
