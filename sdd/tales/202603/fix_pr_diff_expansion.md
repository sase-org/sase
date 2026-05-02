---
create_time: 2026-03-29 19:20:45
status: done
prompt: sdd/prompts/202603/fix_pr_diff_expansion.md
---

# Fix `#pr_diff` xprompt not expanding in agent prompts

## Problem

When the `#gh:` workflow spawns an agent, the `#pr_diff` xprompt reference appears as literal text in the agent prompt
instead of being expanded into a diff file reference. The `#x(pr_desc.txt, ...)` reference on the adjacent line expands
correctly, producing `@.sase/xcmds/pr_desc-....txt`.

## Root Cause

The expansion pipeline has two distinct mechanisms for `#`-references:

1. **Simple xprompts** (`.md` files and config-based entries) are expanded by `process_xprompt_references()`, which
   queries `get_all_xprompts()`.
2. **Workflow xprompts** (`.yml` files with multi-step execution) are expanded by
   `_expand_embedded_workflows_in_prompt()`, which queries `get_all_workflows()`.

`#pr_diff` is defined as a `.yml` workflow (`sase-github/.../xprompts/pr_diff.yml`) with a bash pre-step and a
prompt_part step. It is therefore invisible to `process_xprompt_references()`.

The flow that fails:

1. `_expand_embedded_workflows_in_prompt()` expands `#gh:sase_fix_branch_name_race` and `#commit(who=mentor)`.
2. During gh expansion, it appends tagged workflow content from `prdd.yml` (tag: `append_to_commit_and_propose`) via
   `_resolve_tagged_workflow_content()`.
3. The `prdd.yml` prompt_part contains `#pr_diff` — a workflow reference.
4. Back in `_execute_prompt_step`, the second `process_xprompt_references()` pass runs but only knows about simple
   xprompts. `#pr_diff` is skipped as unknown, left as literal text.

Meanwhile, `#x(pr_desc.txt, ...)` on the adjacent line works because `#x` is a **config-based xprompt** (defined in
`default_config.yml`), loaded by `get_all_xprompts()`.

## Fix

Inline the `pr_diff` logic into `prdd.yml` so it uses `#x(...)` (which IS expanded) instead of `#pr_diff` (which isn't).

`pr_diff.yml` does two things:

1. A bash step to detect the base branch (`origin/master` or `origin/HEAD`)
2. A prompt_part: `#x(pr_changes.diff, git diff <base>...HEAD)`

We replicate this in `prdd.yml` by adding a `detect_base` pre-step and replacing `#pr_diff` with
`#x(pr_changes.diff, git diff {{ detect_base.base }}...HEAD)`. The Jinja2 template is rendered by
`_resolve_tagged_workflow_content()` before xprompt expansion, so `#x(...)` receives the resolved base branch and
expands correctly.

### Changes (sase-github repo)

**`src/sase_github/xprompts/prdd.yml`** -- Add a `detect_base` bash step and replace `#pr_diff` with an inline `#x(...)`
call:

```yaml
steps:
  - name: check_branch
    bash: |
      ...existing...
    output: { should_inject_prompt_part: bool }

  - name: detect_base
    bash: |
      ref=$(git symbolic-ref refs/remotes/origin/HEAD 2>/dev/null || echo "refs/remotes/origin/master")
      branch=$(echo "$ref" | sed 's|refs/remotes/||')
      echo "base=$branch"
    output: { base: word }

  - name: content
    if: "{{ check_branch.should_inject_prompt_part }}"
    prompt_part: |
      ### Context Files Related to this PR
      + #x(pr_changes.diff, git diff {{ detect_base.base }}...HEAD) : Contains a diff of the changes made by the current PR.
      + #x(pr_desc.txt, gh pr view ...) : Contains the current PR's description.
```

No changes needed to `pr_diff.yml` -- it remains available as a standalone workflow for direct use.

### Verification

- Run `just check` in the sase-github repo
- Manually test by running an agent with `#gh:<ref>` and confirming the diff file reference appears expanded (e.g.
  `@.sase/xcmds/pr_changes-....diff`) instead of literal `#pr_diff`
