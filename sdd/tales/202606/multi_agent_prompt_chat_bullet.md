---
create_time: 2026-06-27 16:00:21
status: done
prompt: sdd/prompts/202606/multi_agent_prompt_chat_bullet.md
---
# Plan: Add a "multi-agent prompt file" bullet to agent chat transcripts

## Goal

SASE agent chat transcripts begin with a metadata bullet list:

```
- **TIMESTAMP:** 2026-06-27 11:13:17 EDT
- **MODEL:** codex/gpt-5.5
- **AGENT:** 082
```

Add one more bullet whose value is a path to a markdown file containing the **entire** multi-agent prompt that launched
the agent (all `---`-separated agent prompts plus any leading frontmatter). The bullet is added **only** when the agent
was launched as part of a multi-agent prompt (a `---`-separated prompt). Single-agent prompts, alt-split
(`%alt`/`%{a|b}`), multi-model (`%{%m:..}`), and bead-batch launches do **not** get the bullet.

## Product context

Today, given a chat transcript for an agent that was one of several launched from a single multi-agent prompt, there is
no way to recover the _other_ sibling prompts or the shared frontmatter — only the agent's own (already-expanded) prompt
is visible in the transcript. Persisting the full multi-agent prompt to a stable markdown file and linking it from each
sibling's transcript header makes the originating prompt re-readable and re-runnable, and ties siblings together.

## Current behavior (where things live)

- **Header rendering:** `src/sase/history/chat.py`
  - `_format_transcript_metadata_blocks(...)` builds the bullet list.
  - `save_chat_history(...)` calls it and writes the transcript.
- **Header consumers:** `save_chat_history` is called from three places, all of which already have the agent's
  `AgentExecContext` (`ctx`):
  - `src/sase/axe/run_agent_exec_finalize.py` (final transcript)
  - `src/sase/axe/run_agent_exec_plan.py` (planner transcript)
  - `src/sase/axe/run_agent_exec_questions.py` (Q&A transcript)
- **Multi-agent launch chokepoint:** `src/sase/agent/multi_prompt_launcher.py`
  - `launch_multi_prompt_agents(...)` → `_spawn_segments_into(...)` spawns one agent per segment and assembles each
    slot's environment.
  - NOTE: this same function is also used by single-segment fan-outs (alt, multi-model, bead), so injection here must be
    **opt-in**, not automatic.
- **True `---` multi-agent callers** (the only ones that should opt in), each of which has the original submitted prompt
  text available:
  - `src/sase/agent/launch_cwd_agents.py` (the `len(expanded_segments) > 1` branch) — has `submitted_query`.
  - `src/sase/ace/tui/actions/agent_workflow/_launch_multi_prompt.py` (`_run_multi_prompt_launch`) — has
    `submitted_prompt` and the parsed `MultiPrompt`.
- **Env → subprocess path:** launch-time `extra_env` flows into `AgentLaunchRequestWire.extra_env` → Rust
  `prepare_agent_launch` → `prepared.env_delta` → subprocess env (`src/sase/agent/launch_spawn.py`). This is the
  established mechanism already used for `SASE_AGENT_PLANNED_NAME`, upstream-variable context, repeat-batch vars, etc.
  No Rust change is required (arbitrary `SASE_*` keys already pass through).
- **Runner → context:** `src/sase/axe/run_agent_runner.py` reads env vars and constructs `AgentExecContext`
  (`src/sase/axe/run_agent_exec_types.py`).

## Key design decisions (defaults chosen; flagged for review)

1. **What the file contains.** Default: the **raw submitted multi-agent prompt text** (verbatim), which already includes
   the frontmatter and all `---`-separated agent prompts exactly as written. This is the highest-fidelity representation
   of "the multi-agent prompt that initiated the agent."
   - _Edge case / decision point:_ when the multi-agent-ness comes solely from expanding a single multi-agent
     **xprompt** (e.g. the user submitted `#foo` and `foo` is a multi-agent xprompt), the raw submitted text is just
     `#foo`, not the expanded per-agent prompts. Options: (a) accept this (store raw — simplest, recommended for v1), or
     (b) when the submitted text expands into multiple agents, store the expanded segments (joined by `\n---\n`,
     prefixed with the parsed frontmatter) so the file always literally contains "all of the agent prompts." The plan
     implements (a) but isolates content generation behind one helper so switching to (b) later is a one-function
     change.

2. **One shared file per launch.** All siblings from the same multi-agent prompt reference the **same** file (the prompt
   is identical for all of them). The file is written once at launch time, before the spawn loop, and its path is
   injected into every slot's environment.

3. **Storage location.** `~/.sase/multi_prompts/YYYYMM/<filename>.md` via the existing
   `sharded_path("multi_prompts", filename)` helper (`src/sase/core/paths.py`), mirroring how chats/prompt-history shard
   by month. This is a stable location (not an ephemeral artifacts dir) so the transcript's reference stays valid.
   Filename pattern: `<cl_name>-multiprompt-<timestamp>.md` (timestamp in the standard `YYmmdd_HHMMSS` launch format for
   shard routing and uniqueness).

4. **Bullet label & value format.** Default label `PROMPT`; value is the `~`-relative path wrapped in backticks, e.g.
   `` - **PROMPT:** `~/.sase/multi_prompts/202606/main-multiprompt-260627_111317.md` ``. The label is a single named
   constant so changing it (e.g. to `MULTIPROMPT` or `MULTI-AGENT PROMPT`) is trivial. _Decision point for reviewer:_
   confirm label text and whether to keep backticks.

5. **Threading via a new env var.** `SASE_MULTI_AGENT_PROMPT_FILE` carries the `~`-relative path from launch to runner.
   Consistent with existing per-launch env vars.

## Implementation plan

### 1. Persist the multi-agent prompt file (new helper)

- Add a small module/helper (e.g. `src/sase/history/multi_agent_prompt.py`) with:
  - `render_multi_agent_prompt_file(text: str) -> str` — currently returns the raw text (the seam for decision #1b
    later).
  - `save_multi_agent_prompt_file(text: str, *, cl_name: str, timestamp: str) -> str` — writes via
    `sharded_path("multi_prompts", ...)`, returns the `~`-relative path (same `Path.home()` → `~` substitution
    `save_chat_history` uses).
- Define `MULTI_AGENT_PROMPT_FILE_ENV = "SASE_MULTI_AGENT_PROMPT_FILE"` in a shared spot (alongside the other launch
  env-var constants).

### 2. Opt-in injection at the launch chokepoint

- `multi_prompt_launcher.py`: add a new keyword-only param `multi_agent_prompt_text: str | None = None` to both
  `launch_multi_prompt_agents(...)` and `_spawn_segments_into(...)`.
- When non-`None`, before the spawn loop: write the file once (using the batch's first allocated/launch timestamp +
  `cl_name`), then add `SASE_MULTI_AGENT_PROMPT_FILE=<~path>` to **every** slot's `slot_env` (next to where
  `SASE_AGENT_VAR_UPSTREAMS_ENV` / `_PLANNED_AGENT_NAME_ENV` are set).
- When `None` (alt / multi-model / bead / any other caller): no file, no env, no bullet — preserving the "only for
  multi-agent prompts" requirement.

### 3. Wire the two true multi-agent callers

- `launch_cwd_agents.py` (the `len(expanded_segments) > 1` branch): pass `multi_agent_prompt_text=submitted_query` into
  `launch_multi_prompt_agents`.
- `_launch_multi_prompt.py` (`_run_multi_prompt_launch`): pass `multi_agent_prompt_text=submitted_prompt` (falling back
  to `"\n---\n".join(multi.segments)` when `submitted_prompt is None`, matching the existing failure-history fallback).
- Do **not** touch the alt branch in `launch_cwd_agents.py`, the multi-model caller, or `launch_cwd_bead_work.py`.

### 4. Scrub inherited env on every launch

- `launch_spawn.py`: add `_remove_inherited_multi_agent_prompt_env(env)` that pops `SASE_MULTI_AGENT_PROMPT_FILE`, and
  call it in the `env_shape` block alongside the existing `_remove_inherited_*` calls. This prevents a multi-agent child
  that itself spawns a _single_ agent from leaking a stale path into the grandchild's transcript.

### 5. Runner → AgentExecContext

- `run_agent_exec_types.py`: add field `multi_agent_prompt_file: str | None = None` to `AgentExecContext`.
- `run_agent_runner.py`: read `os.environ.get(MULTI_AGENT_PROMPT_FILE_ENV)` and pass it into the `AgentExecContext(...)`
  construction.

### 6. Render the bullet

- `chat.py`:
  - `_format_transcript_metadata_blocks(...)`: add `metadata_multi_agent_prompt: str | None` param; append
    `- **PROMPT:** `<path>`` when present (cleaned like the other fields).
  - `save_chat_history(...)`: add matching `metadata_multi_agent_prompt: str | None = None` param and forward it.

### 7. Pass it through all three transcript call sites

- `run_agent_exec_finalize.py`, `run_agent_exec_plan.py`, `run_agent_exec_questions.py`: pass
  `metadata_multi_agent_prompt=ctx.multi_agent_prompt_file` to `save_chat_history` so the planner, Q&A, and final
  transcripts of a multi-agent-launched agent all carry the bullet consistently.

### 8. Keep chat post-processing correct

- `src/sase/history/chat_links.py`: extend `_BULLET_METADATA_LIST_RE`'s alternation from `(?:MODEL|AGENT)` to include
  the new label (`(?:MODEL|AGENT|PROMPT)`) so the `## Linked Chats` section is still inserted _after_ the full metadata
  list rather than splitting it. (The legacy `_BLOCK_METADATA_RE` path is for old transcripts and need not change.)

## Edge cases & non-goals

- **Non-multi-agent launches** (single agent, alt, multi-model, bead) never set the env var, so they never get the
  bullet — satisfied by opt-in design.
- **`chat_catalog.py`** derives workflow/agent from the `# Chat History` heading and timestamp from the filename, and
  snippets from `## Prompt`/`## Response`; an extra metadata bullet does not affect it. (Verify with a catalog test.)
- **Rust core boundary:** transcript header rendering and the launch-time file write are already Python-side
  presentation/glue (`chat.py`, launcher). `---` splitting (already in Rust) is unchanged, and env passthrough uses the
  generic `extra_env`→`env_delta` path. No `sase-core` changes expected; confirm `prepare_agent_launch` does not filter
  unknown `extra_env` keys (existing per-launch vars already prove it does not).
- **Resume / wait chats:** resumed transcripts go through the same `save_chat_history`; the bullet appears whenever
  `ctx.multi_agent_prompt_file` is populated.
- **Not in scope:** backfilling the bullet onto historical transcripts; making any other frontend (web/CLI) render it.

## Testing

- `_format_transcript_metadata_blocks`: renders the bullet when the path is present; omits it when `None`; preserves
  order/format.
- `save_chat_history`: end-to-end content includes the bullet only when the arg is supplied.
- `chat_links`: `_BULLET_METADATA_LIST_RE` matches a metadata list that includes the new `PROMPT` bullet, and
  `append_links_to_chat` inserts `## Linked Chats` after (not within) the metadata list.
- File helper: writes content under a `multi_prompts` shard and returns a `~`-relative path.
- Launcher: with `multi_agent_prompt_text` set, the file is written once and the env var is present in every slot's env;
  with it `None`, neither happens.
- `launch_spawn`: `_remove_inherited_multi_agent_prompt_env` drops a stale value unless the launch supplies its own.
- Runner/context: env var populates `AgentExecContext.multi_agent_prompt_file` and reaches the transcript header.
- `chat_catalog`: parsing a transcript that contains the new bullet still yields correct
  workflow/agent/timestamp/snippets.

## Files expected to change

- `src/sase/history/chat.py`
- `src/sase/history/chat_links.py`
- `src/sase/history/multi_agent_prompt.py` (new) — or fold into an existing history module
- `src/sase/agent/multi_prompt_launcher.py`
- `src/sase/agent/launch_cwd_agents.py`
- `src/sase/agent/launch_spawn.py`
- `src/sase/ace/tui/actions/agent_workflow/_launch_multi_prompt.py`
- `src/sase/axe/run_agent_exec_types.py`
- `src/sase/axe/run_agent_runner.py`
- `src/sase/axe/run_agent_exec_finalize.py`
- `src/sase/axe/run_agent_exec_plan.py`
- `src/sase/axe/run_agent_exec_questions.py`
- Tests covering the above.
