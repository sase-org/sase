---
name: sase_var
description: Attach named output variables to the current SASE agent run.
skill: true
---

Use this skill when you need a later SASE agent to consume a small string value produced by the current agent, or when
you want the value to appear in the Agents-tab metadata and Telegram completion message for this run.

## Workflow

1. Make sure the producing agent has a stable name with `%id:<producer>` or an agent-name template such as
   `%id:build-@`.
2. Set one or more output variables:

   ```bash
   sase var set KEY=VALUE [KEY=VALUE ...]
   ```

   Use `--value` for text containing spaces, or a heredoc through `--value-file -` for a multi-line value:

   ```bash
   sase var set summary --value "tests passed"
   sase var set details --value-file - <<'EOF'
   Tests passed.
   The release artifact is ready.
   EOF
   ```

3. In later prompts, wait for the producer before referencing its variables. Every producer's variables live under a
   single `agents` dictionary keyed by agent name. For example, `%id:build-@` can produce:

   ```bash
   sase var set result_path=dist/report.md status=ok
   ```

   A later waited agent can render `{% raw %}{{ agents["build"].result_path }}{% endraw %}` after the producer has
   written the variable.

The key is always the agent's stable name. Agent-name templates use the template base, so `%id:build-@` is
`{% raw %}{{ agents["build"].result_path }}{% endraw %}`, not `build-0`. The key is the raw agent name with no
identifier munging, so dotted, hyphenated, and digit-leading names all work via bracket access: `%id:research.@.final` →
`{% raw %}{{ agents["research.final"].report_path }}{% endraw %}`, and `%id:0n.cld` →
`{% raw %}{{ agents["0n.cld"].report_path }}{% endraw %}`. Identifier-safe keys also support attribute access such as
`{% raw %}{{ agents.build.result_path }}{% endraw %}`.

## Rules

- Run this only inside a SASE agent; the command requires `SASE_AGENT=1` and `SASE_ARTIFACTS_DIR`.
- Keys must be valid Jinja attribute identifiers: `[A-Za-z_][A-Za-z0-9_]*`.
- Values are strings and are split on the first `=`, so `sase var set token=a=b=c` stores `a=b=c`.
- Use `KEY=VALUE` for simple tokens, `--value` for values containing spaces, and a heredoc into `--value-file -` for
  multi-line bodies.
- Each value is limited to 8 KiB of UTF-8 text. Output variables are for small handoff values, not report bodies; store
  a report as an artifact file and publish its path instead.
- Multiple calls merge into the same agent's variable map; later writes for the same key replace earlier values.
- Do not store secrets. Output variables are persisted in `agent_meta.json` and shown in ACE and the Telegram
  agent-completion message.

Use `%wait:<producer>` when a later agent needs a variable from another agent.

## Stopping a `%repeat` / `%r` chain with `STOP`

`STOP` is a reserved output variable that only affects later `%repeat` / `%r` slots. Inside a repeat iteration, run:

```bash
sase var set STOP=1
```

before the iteration completes to skip every remaining repeat slot. Each later slot wakes, sees its repeat predecessor's
`STOP`, finalizes as a successful completed (skipped) slot, and exits without running its prompt. Set `STOP` when the
current iteration determines no further repeat work is needed.

`STOP` is conservative about truthiness: `""`, `0`, `false`, `no`, and `off` (case-insensitive) are treated as not-stop,
so a computed `STOP=0` is a safe no-op; any other value stops the chain. It is otherwise an ordinary output variable:
agents that simply `%wait` on this producer (outside a repeat chain) are not affected and can still read
`{% raw %}{{ agents["name"].STOP }}{% endraw %}`.
