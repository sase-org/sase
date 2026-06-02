---
create_time: 2026-06-02 16:40:35
status: done
prompt: sdd/prompts/202606/builtin_split_file.md
---
# Plan: Make `split_file` a Built-In XPrompt

## Goal

Move the repository-local `xprompts/pysplit.md` prompt into the packaged built-in prompt set as
`src/sase/xprompts/split_file.md`, so users invoke it as `#split_file:<path>` instead of the project-local
`#sase/pysplit:<path>`.

## Current Behavior

- `xprompts/pysplit.md` is loaded from the checkout-local `xprompts/` directory.
- In a detected `sase` checkout, local xprompts are namespaced, so this prompt is available as `#sase/pysplit`.
- Built-in xprompts are loaded from `src/sase/xprompts/*.md` by `load_xprompts_from_internal()`.
- `xprompts/pylimit_split.yml` currently fans out child agents using `#sase/pysplit:{path}`.
- The chezmoi source path is `/home/bryan/.local/share/chezmoi/home`; initial searches found no relevant `pysplit` or
  `#sase/pysplit` references there.

## Implementation Steps

1. Add `src/sase/xprompts/split_file.md` with the same prompt body and input contract as `xprompts/pysplit.md`, but with
   the frontmatter name changed to `split_file`.
2. Remove `xprompts/pysplit.md` so the old checkout-local `#sase/pysplit` form is no longer provided by this repo.
3. Update active prompt/workflow references:
   - Change `xprompts/pylimit_split.yml` to launch `#split_file:{path}`.
   - Rename the generated child-agent prefix from `pysplit.<stem>` to `split_file.<stem>` for consistency with the new
     built-in xprompt name.
4. Update tests that assert the generated prompt shape or use the old xprompt name:
   - `tests/test_xprompt_pylimit_split.py`
   - `tests/test_axe_lumberjack_agent_chops.py`
   - `tests/test_workflow_validator_xprompt_calls.py`
   - Add or adjust a loader-level assertion that `load_xprompts_from_internal()` exposes `split_file`.
5. Update user-facing docs:
   - Add `#split_file` to the built-in xprompt table in `docs/xprompt.md`.
   - Remove `#sase/pysplit` from the repo-local xprompt table in `docs/development.md`.
   - Update any current catalog/design reference that lists `xprompts/pysplit.md` as an active prompt source, while
     avoiding broad rewrites of historical SDD prompt/tale records.
6. Audit the chezmoi repository with a focused search for `pysplit`, `#sase/pysplit`, `sase/pysplit`, `#split_file`, and
   `xprompts/pysplit`; update any real configuration/docs references if found. Ignore false positives from vendored
   Python package internals such as `split_filename`.

## Verification

1. Run focused xprompt tests:
   - `pytest tests/test_xprompt_pylimit_split.py tests/test_xprompt_loader_config.py tests/test_workflow_validator_xprompt_calls.py tests/test_axe_lumberjack_agent_chops.py`
2. Run catalog/expansion sanity checks:
   - `sase xprompt expand '#split_file:src/sase/content.py'`
   - `sase xprompt expand '#sase/pysplit:src/sase/content.py'` should fail or report the prompt as unavailable once the
     local file is removed.
3. Re-run repository and chezmoi searches for stale active references.
4. Because this changes files in the SASE repo, run `just install` if needed and then `just check` before finalizing.

## Non-Goals

- Do not add a compatibility alias from `pysplit` to `split_file`; the request is to move to `#split_file` instead of
  `#sase/pysplit`.
- Do not edit memory files.
- Do not bulk-update historical SDD transcripts and investigation notes unless they are active reference material.
