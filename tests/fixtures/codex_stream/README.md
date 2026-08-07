# Codex stream fixtures

These fixtures document the Codex NDJSON stream shapes used by the SASE tool-call
artifact tests.

- `codex-cli-0.130.0-tools.jsonl` was captured locally from `codex-cli 0.130.0` on
  2026-05-14 with
  `codex exec --model gpt-5.6-sol --dangerously-bypass-approvals-and-sandbox --json --color never --skip-git-repo-check -`.
- `codex-cli-0.130.0-error.jsonl` was captured locally from `codex-cli 0.130.0` on
  2026-05-14 by invoking an unsupported model.
- `synthesized-unknown-item.jsonl` is synthetic and exists to pin current parser
  behavior for an unknown item shape until a real MCP or provider-specific Codex event
  is available.

The current observed tool-relevant events are `item.started` and `item.completed` items
with `type` values of `command_execution` and `file_change`. Codex did not emit separate
`function_call` items or separate result-output items in the captured successful tool
run; command output and exit status were present on completed `command_execution` items.
