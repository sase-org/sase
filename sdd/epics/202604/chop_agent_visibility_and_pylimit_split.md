---
create_time: 2026-04-28 10:45:10
status: done
bead_id: sase-11
prompt: sdd/prompts/202604/chop_agent_visibility_and_pylimit_split.md
---
# Plan: Make chop-launched agents visible and align them with `sase run -d`

## Context and findings

The active athena chop config is managed by chezmoi at:

- `~/.local/share/chezmoi/home/dot_config/sase/sase_athena.yml`
- Applied copy: `~/.config/sase/sase_athena.yml`

The `run_every` lumberjack currently configures three agent chops:

- `sase_pylimit_split`: `#gh:sase #sase/pylimit_split %approve`, with a `gate`
- `sase_fix_just`: `#gh:sase #sase/fix_just`
- `sase_refresh_docs`: `#gh:sase #sase/refresh_docs`

The current SASE code path for configured agent chops already goes through `launch_agent_from_cwd()`, the same
high-level entry point used by `sase run -d`, but lumberjack adds chop-specific behavior:

- `Lumberjack._launch_agent_chop()` sets `SASE_AGENT_AUTO_DISMISS=1` for any chop with `run_every`, which makes the
  runner write `hidden: true` into `agent_meta.json`.
- The chop also gets `SASE_CHOP_*` env vars so it can be tracked in the durable chop-agent registry. That registry is
  useful and should remain.
- Gate support is only used by `sase_pylimit_split`.

There is also a live unmanaged script at:

- `~/.config/sase/chops/sase_pylimit_split`

That script implements the older "find pylimit files, build a multi-prompt, call `sase run -d`" design. It is not
currently referenced by the athena config because `axe.chop_script_dirs` is empty, but it should be deleted or retired
so there is only one authoritative implementation.

The current `xprompts/pylimit_split.yml` workflow discovers files and then uses a `for:` loop over an `agent:` step:

```yaml
- name: split_files
  for: { file_path: "{{ find_files.files }}" }
  agent: |
    #sase/pysplit:{{ file_path }}
```

That is not equivalent to launching independent top-level background agents via `sase run -d`. It invokes the workflow
agent step inside the parent workflow runner. For the desired behavior, the xprompt workflow should remain the owner of
the pylimit file discovery, but the file-specific split work should be launched through the same detached multi-prompt
path that `sase run -d` uses.

## Goals

1. Configured agent chops are visible by default. They should not be hidden or auto-dismissed merely because they came
   from a lumberjack or have `run_every`.
2. Configured agent chops launch agents through the same semantics as `sase run -d <prompt>`.
3. `sase_pylimit_split` uses `#sase/pylimit_split` as the workflow entry point, not the standalone
   `~/.config/sase/chops/sase_pylimit_split` script.
4. `sase_pylimit_split` launches one independent split agent per offending file. Every split agent after the first
   includes a `%wait` directive so it waits for the previous split agent.
5. Gate support is removed from SASE once no config depends on it.

## Non-goals

- Do not remove the durable chop-agent registry. It prevents duplicate relaunch after axe restarts and gives useful
  provenance in `agent_meta.json`.
- Do not introduce runtime-specific logic for Claude, Gemini, Codex, or any other provider. The agent launch behavior
  must stay provider-neutral.
- Do not revive the script-chop design for pylimit split.

## Phase 1: Normalize configured agent chop launch behavior

Owner: one SASE repo agent.

Scope:

- Update the configured `agent:` chop path so it no longer marks `run_every` agents hidden or auto-dismissed by default.
- Keep using `launch_agent_from_cwd(chop.agent, extra_env=...)`.
- Keep `SASE_CHOP_LUMBERJACK`, `SASE_CHOP_NAME`, `SASE_CHOP_RUN_ID`, and `SASE_CHOP_PROMPT_HASH` so registry/dedup still
  works.
- Make `sase axe chop run <agent-chop>` and scheduled lumberjack runs behave consistently where practical. One-shot runs
  should not miss important chop metadata if the scheduled path has it.

Likely files:

- `src/sase/axe/lumberjack.py`
- `src/sase/axe/cli.py`
- `src/sase/axe/chop_agents.py` if helper APIs need a small adjustment
- `tests/test_axe_lumberjack.py`
- `tests/test_axe_chop_agents.py`
- possibly `tests/main` or `tests/test_run_agent_runner_notifications.py`

Acceptance criteria:

- A configured agent chop no longer sets `SASE_AGENT_AUTO_DISMISS=1` just because `run_every` is present.
- Agent metadata for chop-launched agents does not contain `hidden: true` unless the prompt itself requested hiding.
- Existing durable chop-agent registry tests still pass, and new coverage proves visible scheduled agent chops are still
  deduped by live registry records.
- `just install` and focused tests pass.

Risk:

- This will increase visible DONE entries for recurring chops. That is the requested behavior, but it may expose list
  clutter. Do not paper over that with hidden/auto-dismiss behavior in this phase.

## Phase 2: Rework `#sase/pylimit_split` to launch detached split agents

Owner: one SASE repo agent.

Scope:

- Keep the `#sase/pylimit_split` xprompt workflow as the public entry point.
- Replace the current in-process `for:` agent loop with workflow logic that:
  - discovers pylimit offenders using the existing `tools/pylimit_files-260227` commands,
  - deduplicates files,
  - exits cleanly with no child launches when no files are found,
  - constructs a multi-prompt with one segment per file,
  - includes `%wait` at the start of every segment after the first,
  - launches that multi-prompt through `launch_agent_from_cwd()` or an equivalent internal helper used by `sase run -d`.

Preferred implementation shape:

- Use a Python workflow step in `xprompts/pylimit_split.yml` to build the multi-prompt and call
  `sase.agent.launcher.launch_agent_from_cwd()`.
- Avoid shelling out to a standalone chop script.
- Keep child prompts explicit, for example:

```text
#gh:sase #sase/pysplit:<file> %approve
---
%wait
#gh:sase #sase/pysplit:<next-file> %approve
```

If the workflow Python-step API cannot cleanly express this, create a small shared SASE helper and call it from the
workflow rather than embedding a large ad hoc script in YAML.

Likely files:

- `xprompts/pylimit_split.yml`
- `tests/test_workflows_runner.py` or a focused workflow/xprompt test
- possibly a small helper module under `src/sase/agent/` or `src/sase/xprompt/` if needed for testability

Acceptance criteria:

- The workflow still runs manually with `sase run -d "#gh:sase #sase/pylimit_split %approve"`.
- With a fake two-file pylimit result, it calls the detached launch path once with a two-segment multi-prompt.
- Segment 1 has no injected `%wait`; segment 2 starts with `%wait`.
- The launched child agents are top-level `ace(run)` agents, not only repeated prompt-step sections inside the parent
  workflow artifact.
- No standalone `sase_pylimit_split` chop script is needed.

Risk:

- Calling `launch_agent_from_cwd()` from inside an already-running workflow means the parent workflow is a visible
  parent run and the split workers are visible child runs. That is acceptable because it matches the manual
  `sase run -d "#gh:sase #sase/pylimit_split %approve"` shape.

## Phase 3: Clean up athena config and retire the local pylimit script

Owner: one chezmoi/config agent.

Scope:

- Remove the `gate:` block from `~/.local/share/chezmoi/home/dot_config/sase/sase_athena.yml`.
- Keep the `sase_pylimit_split` chop as an `agent:` chop pointing at `#gh:sase #sase/pylimit_split %approve`.
- Do not add `~/.config/sase/chops` to `chop_script_dirs`.
- Delete the unmanaged live script at `~/.config/sase/chops/sase_pylimit_split`.
- If a managed chezmoi copy of that script appears in another checkout, remove it there too. In the currently active
  chezmoi repo, no managed `home/dot_config/sase/chops/...` copy was found.

Likely files:

- `~/.local/share/chezmoi/home/dot_config/sase/sase_athena.yml`
- real-home cleanup: `~/.config/sase/chops/sase_pylimit_split`

Acceptance criteria:

- `sase_athena.yml` has no `gate:` key.
- The live applied config has no `gate:` key after `chezmoi apply`.
- The old `~/.config/sase/chops/sase_pylimit_split` file is gone.
- `just check` passes in `~/.local/share/chezmoi/`.
- `chezmoi apply` is run after validation.

Risk:

- If axe is running during the applied config change, it may need a restart to reload the lumberjack config.

## Phase 4: Remove gate support from SASE core

Owner: one SASE repo agent.

Prerequisite: Phase 3 is applied so the user's active config no longer contains `gate`.

Scope:

- Remove `gate` from `ChopConfig` and config parsing.
- Remove `_resolve_gate_cwd()` and `_run_gate()` from `Lumberjack`.
- Remove gate handling from `_run_single_chop()`.
- Remove schema and docs references.
- Delete or rewrite tests that only cover gate behavior.

Likely files:

- `src/sase/axe/config.py`
- `src/sase/axe/lumberjack.py`
- `config/sase.schema.json`
- `docs/axe.md`
- `docs/configuration.md` if it mentions gate after docs regeneration
- `tests/test_axe_lumberjack.py`
- `tests/test_axe_lumberjack_config.py`

Acceptance criteria:

- `rg -n "\bgate\b" src tests config docs` has no chop-gate references other than unrelated words like navigation gates.
- Loading axe config ignores no longer documented gate behavior because the field is not part of the dataclass or
  schema.
- Focused axe config and lumberjack tests pass.
- `just install` and `just check` pass in the SASE repo.

Risk:

- Historical configs with `gate:` will no longer validate. That is intentional after Phase 3.

## Phase 5: End-to-end validation and handoff

Owner: one validation agent.

Scope:

- Validate the combined behavior across SASE and chezmoi after all prior phases.
- Prefer controlled tests/mocks over launching real expensive agents unless the user explicitly approves a real run.

Checks:

1. SASE repo:
   - `just install`
   - focused tests for chop launch, pylimit workflow launch, and config parsing
   - `just check`
2. Chezmoi repo:
   - `just check`
   - confirm `chezmoi apply` already ran after config cleanup
3. Runtime inspection:
   - `sase axe chop list` shows the configured agent chops.
   - `sase axe lumberjack list` shows `sase_pylimit_split` without `gate`.
   - A dry or mocked `#sase/pylimit_split` run with two fake file offenders produces a multi-prompt where every segment
     after the first starts with `%wait`.
   - Agent metadata from a controlled chop launch is visible by default.

Deliverable:

- A concise summary of changed files, tests run, and any remaining manual step such as restarting `sase axe` to pick up
  the applied config.

## Suggested phase order

1. Phase 1 first, because it fixes the generic visibility and `sase run -d` alignment for all configured agent chops.
2. Phase 2 next, because it makes `#sase/pylimit_split` itself capable of the detached `%wait` chain.
3. Phase 3 after Phase 2, because removing the script and gate is only safe once the xprompt workflow owns the pylimit
   behavior.
4. Phase 4 after Phase 3, because core gate removal should not happen while the active athena config still uses `gate:`.
5. Phase 5 last, in a fresh agent instance, to verify cross-repo behavior.
