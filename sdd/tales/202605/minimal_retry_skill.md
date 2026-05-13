---
create_time: 2026-05-13 19:35:50
status: done
prompt: sdd/prompts/202605/minimal_retry_skill.md
---
# Minimal Retry Skill Wording Plan

## Goal

Make the recently added retry guidance in `sase_agents_status` minimal while preserving the important behavioral
guardrails: ordinary retries should get a fresh retry name, non-TUI `%name:!<name>` should not be presented as the
default retry path, and forced same-name reuse should remain clearly exceptional.

## Current State

The current `## Retrying an agent` section in `src/sase/xprompts/skills/sase_agents_status.md` is 17 added lines: a
short warning, a six-step ordered list, and a forced-reuse warning. The guidance is correct, but it is heavier than
necessary for a skill whose surrounding content is a compact quick reference.

## Proposed Change

Replace only the body of `## Retrying an agent` with three concise sentences:

```markdown
For ordinary retries, locate the source with `sase agents status -a -j` or `sase agents show -n <name>`, prefer
`<artifacts_dir>/raw_xprompt.md` as the prompt source, allocate a fresh name with
`sase.agent.names.allocate_retry_name("<name>")`, then rewrite the prompt through
`sase.agent.retry_prompt.rewrite_retry_prompt_name(raw_prompt, retry_name)` before launching with
`sase run -d "$rewritten_prompt"`. Confirm the new run with `sase agents status -a -j` or
`sase agents show -n <retry-name>`. Do not use `%name:!<name>` from non-TUI surfaces for ordinary retries; reserve
forced same-name reuse for explicitly approved reruns through code paths that call `wipe_names_for_forced_reuse`.
```

This keeps the modification minimal in both line count and concept count while retaining the exact helper names an agent
needs.

## Implementation Steps

1. Edit only `src/sase/xprompts/skills/sase_agents_status.md`, replacing the retry section body and leaving the heading
   and surrounding sections intact.
2. Run the repo's skill generation/deployment path from the local checkout so generated skill copies match the source.
3. Verify the retry section in the source, chezmoi copy, and installed Codex skill.
4. Run a docs-focused formatting check, such as `prettier --check src/sase/xprompts/skills/sase_agents_status.md`.

## Non-Goals

- Do not alter retry implementation code.
- Do not change memory files.
- Do not broaden this into unrelated skill cleanup.
- Do not run full test suites unless the generation or formatting step exposes a code-related issue.
