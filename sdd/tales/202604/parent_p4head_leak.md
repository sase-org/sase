---
create_time: 2026-04-19 14:55:56
status: wip
prompt: sdd/prompts/202604/parent_p4head_leak.md
---

# Plan: Stop `sase commit` from writing `PARENT: p4head` into ChangeSpecs

## Problem

A `sase commit` invocation produced a ChangeSpec whose `PARENT` field is literally `p4head`. That string is an
hg-specific sentinel used by the retired Mercurial plugin plugin to mean "the main branch of the repo"; it is a **checkout target**,
not a ChangeSpec name. Writing it to a ChangeSpec `PARENT` field is semantically wrong for every VCS:

- `PARENT` is supposed to reference another ChangeSpec by NAME (or be omitted when the CL has no parent).
- `p4head` is not a ChangeSpec name. It is also not meaningful to the git/GitHub provider, where the equivalent main ref
  would be `origin/main` or `origin/master`. Neither of those should appear in `PARENT` either.

So the bug manifests as hg-specific VCS knowledge leaking through `sase commit` into a field that is supposed to be
VCS-agnostic data.

## Root Cause

The trace, with exact file:line references:

1. `retired Mercurial plugin/src/retired_mercurial_plugin/scripts/sase_split_setup:75` — when the CL being split has no parent ChangeSpec, this
   script falls back to the hg sentinel for "main":

   ```python
   default_parent = target.parent if target and target.parent else "p4head"
   ```

   The variable name `default_parent` is doing double duty here: it is the **checkout target** (for
   `retired_mercurial_plugin_update`) _and_ the intended **ChangeSpec parent name** (for `sase commit -p`). The two concepts are not
   interchangeable.

2. `retired Mercurial plugin/src/retired_mercurial_plugin/xprompts/split.yml:41, 50` — the workflow pipes `default_parent` into both
   `sase_split_prepare_execute` and the `split_executor` agent xprompt.

3. `retired Mercurial plugin/src/retired_mercurial_plugin/xprompts/split_executor.md:26, 36-38` — the executor uses `{{ default_parent }}` in two
   places:
   - As the argument to `retired_mercurial_plugin_update` (correct use — a checkout target).
   - As the value of the `-p` flag to `sase commit` (incorrect use — a ChangeSpec name is expected).

4. `sase_100/src/sase/main/cl_handler.py:92-93` — `sase commit` sees `--parent=p4head` and puts it into
   `payload["parent"]` as-is.

5. `sase_100/src/sase/workflows/commit/workflow.py:140-146` — `CommitWorkflow` prefers the explicit payload parent over
   auto-detection, so `self._parent_cl_name = "p4head"`.

6. `sase_100/src/sase/workflows/commit/changespec_operations.py:243` — writes the literal string into the ChangeSpec:

   ```python
   parent_line = f"PARENT: {parent}\n" if parent else ""
   ```

   Earlier in the same function (lines 313-346) there is a "parent ChangeSpec not found" branch, but it only affects
   _where_ the new ChangeSpec is inserted (it appends to the end with a warning). It still writes `PARENT: p4head`.

So the bug has two distinct layers: a **caller bug** in retired Mercurial plugin conflating checkout-target with
ChangeSpec-parent-name, and an **insufficiently defensive sink** in sase_100 that happily writes whatever string it gets
even when it is not a real ChangeSpec name.

## Fix (VCS-Agnostic)

Two-part fix keeps VCS-specific knowledge in retired Mercurial plugin and makes sase_100 reject bogus `PARENT` values.

### Part 1: Separate checkout target from ChangeSpec parent in retired Mercurial plugin

Make `sase_split_setup` emit two distinct values and thread them through the workflow:

- `default_parent` (ChangeSpec name, empty string when there is no parent ChangeSpec) — consumed by `sase commit -p`.
- `default_checkout_target` (VCS ref, falls back to the hg-specific `"p4head"`) — consumed by `retired_mercurial_plugin_update`.

Changes:

| File                                                             | Change                                                                                                                                                                                                                                                                                                                                  |
| ---------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `retired Mercurial plugin/src/retired_mercurial_plugin/scripts/sase_split_setup`           | Split the current `default_parent` into two variables. `default_parent = target.parent if target and target.parent else ""`. `default_checkout_target = target.parent if target and target.parent else "p4head"`. Print both. Keep `parent_submitted` logic intact (still resolved via the CS name, which is now empty when no parent). |
| `retired Mercurial plugin/src/retired_mercurial_plugin/xprompts/split.yml`                 | Add `default_checkout_target: word` to the `setup` step's output schema. Pass it to `sase_split_prepare_execute` via a new `--default-checkout-target` flag, and to the `split_executor` xprompt as a new `default_checkout_target` input.                                                                                              |
| `retired Mercurial plugin/src/retired_mercurial_plugin/scripts/sase_split_prepare_execute` | Add a `--default-checkout-target` arg. Use it (not `--default-parent`) for the `retired_mercurial_plugin_update` call on line 106.                                                                                                                                                                                                                   |
| `retired Mercurial plugin/src/retired_mercurial_plugin/xprompts/split_executor.md`         | Accept both `default_parent` and `default_checkout_target`. In step 1, navigate using `default_checkout_target`. In step 4, pass `-p <parent>` only when a parent ChangeSpec name is present; omit the flag entirely when the entry has no `parent` AND `default_parent` is empty.                                                      |
| `retired Mercurial plugin/tests/*`                                            | Extend tests for `sase_split_setup` and `sase_split_prepare_execute` to cover both the "target has parent" and "target has no parent" cases, asserting that `default_parent` is empty (not `"p4head"`) in the latter.                                                                                                                   |

Why this is VCS-agnostic: the hg-specific string `"p4head"` is kept entirely inside `retired Mercurial plugin`, never crossing the
process boundary into `sase commit` as a would-be ChangeSpec name. Conceptually, retired Mercurial plugin keeps a private
"checkout_target" lingo while exposing only real ChangeSpec-name semantics to the sase CLI.

### Part 2: Defensive guard in sase_100

Even after the caller fix, sase_100 should not quietly write bogus strings into `PARENT`. Add a lightweight validation
that is VCS-agnostic (it only knows about ChangeSpecs, not VCS refs):

| File                                                          | Change                                                                                                                                                                                                                                                                                                                                                  |
| ------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `sase_100/src/sase/workflows/commit/changespec_operations.py` | In `add_changespec_to_project_file`, when `parent` is provided but `_find_changespec_end_line(lines, parent)` returns `None` (and the archive also does not contain the name), stop writing `PARENT: {parent}`. Log a prominent warning ("Parent ChangeSpec '{parent}' does not exist — omitting PARENT field") and proceed as if `parent` were `None`. |
| `sase_100/src/sase/workflows/commit/workflow.py` (optional)   | In `run()`, after resolving `self._parent_cl_name` from the explicit payload `parent`, call a cheap lookup (similar to `detect_parent_changespec`) to verify the name resolves to a real ChangeSpec. If not, emit a warning and drop the value. This gives an earlier, clearer failure signal without hard-failing the commit.                          |
| `sase_100/tests/workflows/test_commit_workflow.py`            | Add regression tests: (a) `sase commit -p <nonexistent>` produces a ChangeSpec with no `PARENT` line and a warning; (b) `sase commit -p <real>` still produces `PARENT: <real>` pointing at the correct insertion point; (c) explicit `--parent ""` (or missing) works unchanged.                                                                       |

Why this is VCS-agnostic: the guard knows only the invariant "PARENT must be an existing ChangeSpec name." It never
mentions `p4head`, `origin/main`, or any VCS ref. It is a property of the ChangeSpec data model, not the VCS.

### Part 3: Documentation

| File                                | Change                                                                                                                                            |
| ----------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------- |
| `sase_100/docs/commit_workflows.md` | Clarify that `-p`/`--parent` expects an existing ChangeSpec name. Note that if it does not resolve, the `PARENT` field is omitted with a warning. |
| `sase_100/docs/change_spec.md`      | Add a short note that `PARENT` is a ChangeSpec name (never a VCS ref such as `origin/main` or an hg sentinel).                                    |

## Out of Scope

- Changing how ChangeSpecs model the main-branch concept. If we ever want to represent "branches off main," that is a
  bigger design discussion. For now, an absent `PARENT` field already means exactly this.
- Altering the `detect_parent_changespec()` auto-detection flow, which is a separate code path that already returns
  `None` correctly when the branch name doesn't match any ChangeSpec.
- Any changes to the git `get_default_parent_revision()` implementation — it is already correct (returns
  `origin/{default_branch}`) and is only used for checkout/update purposes, not for `PARENT`.

## Verification Plan

1. **Unit tests (both repos)** cover the new behaviors, including the regression case "caller passes hg sentinel /
   nonexistent CS — sase commit does not write `PARENT: <sentinel>`".
2. **Manual smoke test (git)**: run `sase commit -t create_pull_request -n foo -M msg.txt` on a git repo from a
   non-ChangeSpec branch; the resulting ChangeSpec must not have a `PARENT` line.
3. **Manual smoke test (hg, retired Mercurial plugin)**: run the `#split` xprompt on a CL that has no parent; each generated child
   CL's ChangeSpec must have no `PARENT` line. Run it on a CL that has a parent; each generated child CL must have
   `PARENT: <parent-name>` with the real name.
4. `just check` in both `sase_100` and `retired Mercurial plugin` passes.
