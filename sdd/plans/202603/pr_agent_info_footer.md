---
status: done
create_time: 2026-03-26 11:09:34
prompt: sdd/prompts/202603/pr_agent_info_footer.md
---

# Add Agent Info Footer to PR Descriptions

## Problem

The old `#pr` xprompt (in sase-github) read `$SASE_ARTIFACTS_DIR/agent_meta.json` and appended a footer with agent name
and model to PR descriptions:

```
---
**Model:** `provider/model`
**Agent:** `agent_name`
```

The new `#pr` xprompt uses `CommitWorkflow` → VCS provider, but doesn't add this footer.

## Key Constraint

The `message` payload field is used for **both** `git commit -m` (in GitCommon) and `gh pr create --body` (in
GitHubPlugin). The footer must only appear in the PR body, not the commit message. So we can't just append to `message`.

## Approach

Introduce a `_pr_body` internal payload field (following the `_plan_path` convention). CommitWorkflow reads
`agent_meta.json` and sets `payload["_pr_body"]` = message + agent info footer. The GitHub plugin uses `_pr_body` when
available, falling back to `message`.

## Changes

### 1. `src/sase/workflows/commit/workflow.py` (sase_101)

Add a `_build_pr_body` method to `CommitWorkflow`:

- Read `$SASE_ARTIFACTS_DIR/agent_meta.json` (best-effort, like other meta operations)
- Extract `name`, `model`, `llm_provider`
- Build footer string matching old format:
  - `**Model:** \`provider/model\``(only if both`llm_provider`and`model` present)
  - `**Agent:** \`name\``(only if`name` present)
  - Separated from body by `\n\n---\n`
- Set `payload["_pr_body"]` = `message + footer`

Call `_build_pr_body()` in `run()` just before the VCS provider dispatch, only when
`self._method == "create_pull_request"`.

### 2. `../sase-github/src/sase_github/plugin.py` (sase-github)

In `vcs_create_pull_request`, change the PR body from `message` to `payload.get("_pr_body", message)`:

```python
message = payload.get("message", "")
body = payload.get("_pr_body", message)
title = message.split("\n", 1)[0]
pr_out = self._run(
    ["gh", "pr", "create", "--title", title, "--body", body], cwd
)
```

Note: title still comes from `message` (first line of commit message), not `_pr_body`.

### Testing

- Verify `_build_pr_body` correctly reads agent_meta.json and formats footer
- Verify footer is absent when agent_meta.json doesn't exist or SASE_ARTIFACTS_DIR is unset
- Verify the GitHub plugin uses `_pr_body` when present, falls back to `message`

## Notes

- The Google/Mercurial plugin uses `message` for CL descriptions and doesn't have a separate "PR body" concept. No
  changes needed there — `_pr_body` is simply ignored.
- The `new_pr_desc.yml` xprompt (AI-generated PR descriptions via `gh pr edit`) will overwrite the body including the
  footer. That's acceptable — it can be updated separately to preserve or re-add the footer if desired.
