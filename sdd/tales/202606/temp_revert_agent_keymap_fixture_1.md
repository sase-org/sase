---
create_time: 2026-06-14 13:11:57
status: wip
prompt: sdd/prompts/202606/temp_revert_agent_keymap_fixture_1.md
---
# Temporary Revert-Agent Keymap Fixture

## Objective

Create one intentionally disposable, low-risk repository change so Bryan can verify the newly added `,r` Agents-tab
revert-agent keymap in the TUI. Do not manually commit the change; leave it for SASE's commit finalizer.

## Current Context

- The working tree is clean before the test fixture change.
- The requested behavior is not to implement or modify the TUI keymap itself.
- The repo instructions forbid modifying memory files without explicit approval, so no `memory/` files will be touched.
- The repo instructions require `just check` after file changes except for markdown/images under `sdd/research/`.
- There is an existing tracked research note directly related to the feature:
  `sdd/research/202606/agents_tab_revert_selected_done_agent_commits.md`.

## Planned Change

Append a short, clearly labeled temporary marker section to
`sdd/research/202606/agents_tab_revert_selected_done_agent_commits.md`.

The marker will be easy to identify in the final commit and harmless to revert:

- it is markdown only;
- it lives under `sdd/research/`, matching the documented exception to full `just check`;
- it is directly related to the `,r` revert-agent work, making it a sensible fixture for the test;
- it avoids source, generated, config, memory, and broad documentation files.

## Verification

After the marker is added:

1. Run `git diff --check` to catch whitespace or malformed patch issues.
2. Run `git status --short` to confirm the only repository change is the intended research markdown file.
3. Do not run `just check`, because the only repo change will be markdown under `sdd/research/`, which is explicitly
   exempted by `memory/short/build_and_run.md`.
4. Do not commit. Leave the dirty worktree for the SASE commit finalizer, as requested.

## Expected Result

SASE's commit finalizer should be able to create a normal agent-associated commit containing only this temporary
research-note marker. Bryan can then use the TUI's Agents tab and press `,r` on the completed agent entry to test that
the revert-agent keymap reverts that commit cleanly.
