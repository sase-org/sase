---
create_time: 2026-06-27 08:55:20
status: done
prompt: sdd/prompts/202606/commit_tag_prefix.md
---
# Plan: Prefix SASE Commit Footer Tags

## Goal

Change commit messages produced by `sase commit` so SASE-authored footer tags are rendered as `SASE_<KEY>=<value>`. For
example, `TYPE=snippet` becomes `SASE_TYPE=snippet`.

The implementation should write only prefixed keys going forward while still reading historical unprefixed keys from
existing commits, PR bodies, and test fixtures. This avoids breaking features like agent-commit discovery while moving
new commit history to the new format.

## Current Behavior

The tag handling is spread across several Python paths:

- `src/sase/workflows/commit/runtime_tags.py`
  - Adds runtime tags such as `AGENT=` and `MACHINE=`.
  - Adds auto-commit type tags such as `TYPE=sdd`.
  - Parses trailing `KEY=VALUE` blocks for downstream readers.
- `src/sase/workflows/commit/precommit_hooks.py`
  - Appends `PLAN=<path>` directly when `SASE_PLAN` is active.
- `src/sase/workflows/commit/pr_operations.py`
  - Adds `BUG=<id>` and configured or inherited PR tags before runtime tags are applied.
- `src/sase/vcs_provider/config.py`
  - Extracts and strips trailing PR tag blocks from PR descriptions.
- `src/sase/ace/revert_agent_discovery.py`
  - Reads `AGENT=<name>` from commit messages to find commits authored by an agent.

Because multiple writers append or merge the same footer block, the change should be centralized instead of updating
each call site with ad hoc string concatenation.

## Scope

Treat footer lines managed by the `sase commit` workflow as SASE commit footer tags and render them with the `SASE_`
prefix:

- Built-in tags: `TYPE`, `AGENT`, `MACHINE`, `PLAN`, and `BUG`.
- Configured or inherited PR tag keys once they are merged into the commit-message footer block by `sase commit`.
- Existing tag-like lines already present in a footer block when the SASE tag updater rewrites that block.

The helpers should be idempotent: an input key already named `SASE_TYPE` must render as `SASE_TYPE`, not
`SASE_SASE_TYPE`.

Historical compatibility is required:

- Readers must accept both `AGENT=` and `SASE_AGENT=`.
- Parent PR tag inheritance should accept both legacy and new tag blocks.
- Stale legacy keys should be removed when the same canonical key is rewritten, so a message does not end up with both
  `TYPE=old` and `SASE_TYPE=new`.

## Implementation Plan

1. Centralize key normalization in `src/sase/workflows/commit/runtime_tags.py`.
   - Add a single prefix constant, e.g. `COMMIT_TAG_PREFIX = "SASE_"`.
   - Add helpers to canonicalize keys (`SASE_TYPE` -> `TYPE`), render keys (`TYPE` -> `SASE_TYPE`), and compute legacy
     plus prefixed aliases for removal.
   - Keep public helper inputs in canonical form so existing callers can continue passing `{"TYPE": "sdd"}`.

2. Update trailing tag parsing and rendering.
   - Make `parse_trailing_commit_tags()` return canonical unprefixed keys for both legacy and new lines.
   - Make `update_trailing_commit_tags()` normalize existing footer keys, remove both legacy and prefixed aliases for
     updated or owned keys, and render every final footer key with `SASE_`.
   - Preserve current body handling, blank-line behavior, duplicate-key semantics, and value sanitization.

3. Route all direct tag writers through the central updater.
   - Leave `_resolve_runtime_commit_tags()` returning canonical keys, but make `apply_runtime_commit_tags()` render
     `SASE_AGENT=` and `SASE_MACHINE=`.
   - Make `apply_auto_commit_type_tag()` and `apply_auto_commit_tags_with_runtime()` render `SASE_TYPE=`.
   - Replace the direct `PLAN=` append in `handle_sase_plan()` with
     `update_trailing_commit_tags(message, {"PLAN": plan_ref}, remove_keys={"PLAN"})`.
   - Keep `append_pr_tags()` building canonical maps, then rely on the updater so `BUG=` and configured/inherited tag
     keys render as `SASE_BUG=`, `SASE_AUTOSUBMIT_BEHAVIOR=`, etc.

4. Update read-side compatibility.
   - Update `filter_runtime_owned_tags()` so it filters runtime-owned tags regardless of whether callers pass `AGENT`,
     `MACHINE`, `SASE_AGENT`, or `SASE_MACHINE`.
   - Reuse or mirror the canonical parsing in `extract_pr_tags()` so parent PR inheritance accepts legacy and prefixed
     tags without double-prefixing on child PRs.
   - Keep `strip_pr_tags()` generic enough to strip both legacy and prefixed footer blocks from ChangeSpec descriptions.
   - Keep `revert_agent_discovery` looking up canonical `AGENT`, relying on the parser to normalize old and new commit
     messages.

5. Update documentation.
   - Update `docs/commit_workflows.md`, `docs/change_spec.md`, and `docs/configuration.md` references that describe
     commit footer tag names.
   - Document that new commit messages use `SASE_`-prefixed footer keys and that historical unprefixed keys remain
     readable.

6. Update tests.
   - Refresh expectations in `tests/test_commit_runtime_tags.py`, `tests/test_pr_tags.py`,
     `tests/test_commit_workflow_artifacts.py`, `tests/test_sdd_commit.py`,
     `tests/llm_provider/test_commit_finalizer_auto_sdd_status.py`, and any other tests found by `rg` for old footer
     literals.
   - Add explicit regression coverage for:
     - rendering `SASE_TYPE`, `SASE_AGENT`, `SASE_MACHINE`, `SASE_PLAN`, and `SASE_BUG`;
     - parsing legacy `AGENT=` and new `SASE_AGENT=`;
     - replacing stale legacy tags without duplicates;
     - parent PR inheritance from legacy tags into prefixed child tags;
     - agent revert discovery finding both old and new commit formats.

## Risks and Decisions

- Prefixing configured `vcs_provider.pr_tags` changes the exact footer keys visible to external PR tooling. This plan
  follows the requested "all tags created by `sase commit`" behavior, but the implementation should call this out in
  docs because users may need to update external consumers that expect unprefixed names.
- Commit history should not be migrated. The compatibility layer should make old history readable without rewriting
  commits.
- This is a focused migration of the existing Python commit workflow. No linked-repository or Rust-core change is
  planned unless implementation search finds another active commit-footer renderer outside this repo.

## Verification

Run targeted tests first:

```bash
pytest tests/test_commit_runtime_tags.py \
  tests/test_pr_tags.py \
  tests/test_commit_workflow_artifacts.py \
  tests/test_sdd_commit.py \
  tests/llm_provider/test_commit_finalizer_auto_sdd_status.py \
  tests/ace/test_revert_agent_discovery.py \
  tests/test_strip_pr_tags.py
```

Then, because this repo requires it after file changes, run:

```bash
just install
just check
```
