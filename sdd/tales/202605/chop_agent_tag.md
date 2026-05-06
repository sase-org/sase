---
create_time: 2026-05-06 03:47:32
status: done
prompt: sdd/prompts/202605/chop_agent_tag.md
---
# Plan: Tag Agents Launched By Lumberjack Chops

## Goal

Ensure every agent spawned from a lumberjack chop context is launched with the `%tag:chop` prompt directive, including:

- direct configured agent chops such as `sase_pylimit_split`, `sase_fix_just`, and refresh-docs chops in the chezmoi
  SASE config;
- nested agents launched by those chop agents, such as the per-file `pysplit.*` agents spawned from
  `xprompts/pylimit_split.yml`;
- one-shot agent chops launched through `sase axe chop run`;
- fan-out cases such as multi-prompt, `%alt` / model fan-out, and `%repeat`.

The change should be generic rather than hard-coded to `sase_pylimit_split`, because script chops and embedded workflows
already propagate `SASE_CHOP_*` metadata through the environment.

## Current Behavior

Lumberjack agent chops are represented by `ChopConfig.agent` and launched in `src/sase/axe/lumberjack.py` via:

- `build_chop_launch_env(...)`, which injects `SASE_CHOP_LUMBERJACK`, `SASE_CHOP_NAME`, `SASE_CHOP_RUN_ID`, and
  `SASE_CHOP_PROMPT_HASH`;
- `launch_agent_from_cwd(chop.agent, extra_env=extra_env)`;
- `record_chop_agent_launch_result(...)`, which preserves durable dedup metadata.

External script chops also receive the same chop env in `_run_single_chop`, so scripts that call `sase run` or
`launch_agent_from_cwd()` can propagate chop context through inherited environment.

Nested launches already get durable chop metadata because `spawn_agent_subprocess()` merges `os.environ` with prepared
launch env and records launches when `SASE_CHOP_*` is present. This is why `pylimit_split.yml` can spawn per-file
children that are still associated with the parent chop.

The existing `%tag` directive is parsed in `sase.xprompt.directives`, written to `agent_meta.json` in
`run_agent_phases.extract_directives_and_write_meta()`, and persisted to `~/.sase/agent_tags.json` so the Agents tab can
group/filter by tag.

## Proposed Design

Add a small shared prompt-normalization helper that prepends `%tag:chop` only when the launch environment identifies a
chop-launched agent and the prompt does not already contain an explicit `%tag` / `%t` directive.

Preferred location:

- `src/sase/axe/chop_agents.py`

Reasoning:

- that module already owns the chop env contract and prompt hashing;
- both direct agent chops and nested launches can use the same logic;
- this avoids hard-coding individual chop names or modifying every chezmoi prompt manually.

Suggested helper shape:

```python
CHOP_AGENT_TAG = "chop"

def prompt_with_chop_tag(prompt: str, env: dict[str, str] | None = None) -> str:
    if not _chop_agent_env_from_process_env(env):
        return prompt
    if has_tag_directive(prompt):
        return prompt
    return "%tag:chop\n" + prompt.lstrip("\n")
```

For tag detection, use a directive-aware helper rather than a naive substring check. A lightweight `has_tag_directive()`
predicate can live beside `has_wait_directive()` and `has_model_directive()` in `src/sase/xprompt/directives.py`, using
the same directive boundary conventions and aliases. It should recognize `%tag:<arg>`, `%tag(<arg>)`, and `%t:<arg>`.

Apply the helper at the launch boundary:

1. In `spawn_agent_subprocess()`, after combining `os.environ`, prepared env, and `extra_env`, but before building the
   wire request or temp prompt file, normalize the prompt against the final subprocess environment.
2. Optionally also normalize `LaunchSpawnRequest.prompt` in `execute_launch_plan()` when `extra_env`/slot env contains
   chop metadata, so tests and callbacks that inspect launch requests see the same prompt the child will receive. Keep
   `spawn_agent_subprocess()` as the final guard so direct callers are covered.

Do not change `build_chop_launch_env()` hashing behavior. The `SASE_CHOP_PROMPT_HASH` value should remain the hash of
the configured parent chop prompt so durable dedup still treats all nested children as part of that chop invocation.

Do not update the chezmoi chop prompt strings unless a later review shows a user-facing reason to make the config
explicit. A generic launcher fix covers more cases and avoids duplicate config churn.

## Edge Cases

- If the user already supplied `%tag:<something>` on a chop-launched prompt, keep their explicit tag and do not add
  `%tag:chop`.
- Multi-prompt and alt/model fan-out should tag every spawned child, not just the first segment.
- `%repeat` should tag every repeated child.
- Script chops that launch agents via inherited `SASE_CHOP_*` env should be tagged without requiring script-specific
  changes.
- Non-chop launches must be unchanged.
- Prompt history may remain as the user-entered/configured prompt; the actual spawned agent prompt and artifact prompt
  should contain `%tag:chop`.

## Tests

Add or update focused tests:

- `tests/test_axe_chop_agents.py`
  - `spawn_agent_subprocess()` under `SASE_CHOP_*` writes a temp prompt file prefixed with `%tag:chop`.
  - an existing `%tag:custom` prompt is preserved without adding `%tag:chop`.
  - normal launches without chop env are unchanged.

- `tests/test_agent_launch_executor.py`
  - fan-out execution with chop env applies `%tag:chop` to each `LaunchSpawnRequest.prompt`.
  - explicit `%tag:custom` is not overwritten.

- `tests/test_multi_prompt_launcher_launch.py`
  - chop `extra_env` sent through multi-prompt launch results in every spawned segment carrying `%tag:chop`, including
    wait-chained segments.

- `tests/test_agent_launch_repeat.py` or the launcher repeat tests
  - repeated agents inherit the chop tag directive on each child prompt.

- `tests/test_directives_has_helpers.py` or `tests/test_directives_extract.py`
  - `has_tag_directive()` recognizes `%tag` and `%t` forms and ignores ordinary text.

Existing `tests/test_xprompt_pylimit_split.py` should not need structural changes if the tag is added generically at
launch time. If request-level injection is added before `launch_agent_from_cwd()` sees the built multi-prompt, update
that test only to assert the expected launcher boundary behavior.

## Verification

After implementation:

1. Run focused tests:

```bash
pytest tests/test_axe_chop_agents.py tests/test_agent_launch_executor.py tests/test_multi_prompt_launcher_launch.py tests/test_agent_launch_repeat.py tests/test_directives_has_helpers.py tests/test_directives_extract.py
```

2. Run the repo check sequence required by local memory:

```bash
just install
just check
```

3. If any chezmoi config files are ultimately edited, run:

```bash
cd ~/.local/share/chezmoi
just check
```

Do not run `chezmoi apply --force` unless committing/applying chezmoi changes becomes part of the implementation path.

## Open Question

The plan assumes `%tag:chop` should be the default only when no explicit `%tag` is present. If the desired behavior is
"every chop-launched agent must be grouped under `chop` even when an explicit tag exists", then the current one-tag
storage model would require choosing either overwrite semantics or a larger multi-tag design. The conservative
implementation preserves explicit user tags.
