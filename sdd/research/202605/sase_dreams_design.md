# Designing Dreams for SASE

Research date: 2026-05-09

## Question

Design "dreams" for SASE: a background agent periodically reviews interesting agent chat transcripts created since the
last dream run and distills useful knowledge for future agents.

The key design question is not "how do we read old chats?" SASE can already read chats. The design question is how to
turn a high-volume, noisy episodic log into durable memory without poisoning future prompts, rereading the same data, or
making the background system fragile.

## Local Findings

### Chat transcripts are high-volume and already sharded

`src/sase/history/chat.py` stores chat transcripts under `~/.sase/chats/YYYYMM/*.md`. Filenames encode workspace,
workflow, optional agent name, and a `YYmmdd_HHMMSS` timestamp. `src/sase/core/paths.py` provides the sharding helpers
used by chat writes and scans.

`src/sase/history/chat_catalog.py` already provides a reusable scan API:

- `list_chat_transcripts(limit=None, query=None)` walks sharded and legacy chat files.
- It reads only the first 64 KiB of each chat for snippets and query matching.
- It returns `ChatTranscriptInfo` rows with path, basename, mtime, size, workflow, agent, filename timestamp, prompt
  snippet, and response snippet.
- `resolve_chat_ref()` resolves by explicit path, basename, or named agent.

On this machine, `~/.sase/chats` currently has about 26k markdown transcripts. That makes full transcript rereads on
every cycle the wrong default. Dreams need an incremental index and a cheap candidate phase.

### Completed agent artifacts are a better primary index than raw chat files

`src/sase/axe/run_agent_exec.py` saves the final chat and writes `done.json` for completed outcomes. Completed
`done.json` records carry `response_path`, `step_output`, `diff_path`, `plan_path`, model/provider, project, workspace,
and agent name when available. The local sample had about 1.8k `done.json` files, with 1.1k completed records carrying
`response_path`.

This is a much smaller and richer input than the raw `~/.sase/chats` tree. It also avoids treating every workflow,
check, or legacy chat as an equal candidate.

Important caveat: plan and question handoff steps can write their own chat files before the final response. In
`src/sase/axe/run_agent_exec_plan.py`, planner and question flows save chat files and update `agent_meta.json["chat_path"]`
plus prompt-step `response_path`. A dream collector that only reads root `done.json.response_path` will miss some
planner/question evidence unless it also looks at prompt step markers or linked chat sections.

### Background periodic work already exists: axe lumberjacks and agent chops

The axe system is already the right scheduling substrate:

- `src/sase/default_config.yml` defines lumberjacks with intervals and chops.
- `src/sase/axe/lumberjack.py` supports script chops and agent chops.
- Agent chops are deduped by lumberjack name, chop name, and prompt hash via `src/sase/axe/chop_agents.py`.
- Agent chops can set metadata on `agent_meta.json` (`chop_lumberjack`, `chop_name`, `chop_run_id`,
  `chop_prompt_hash`).
- `SASE_AGENT_AUTO_DISMISS` is already used to keep recurring infrastructure agents from accumulating as visible done
  rows.

That means a first dreams implementation should not invent a separate daemon. It should be a configured agent chop,
probably in the `housekeeping` lumberjack or a new `memory` lumberjack.

### Dynamic memory is already a projection layer

`src/sase/memory/dynamic.py` matches keyword-tagged memory xprompts against the current prompt, writes matched memory
files into `.sase/memory/`, and injects a `### DYNAMIC MEMORY` section. `memory/long/*.md` files with `keywords`
frontmatter are auto-discovered.

Prior research in `sdd/research/202605/zettel_sase_shared_memory.md` makes the most important distinction:

- Raw chats are episodic evidence.
- Durable memory should be curated or distilled.
- Dynamic memory is a projection system, not the canonical memory store.

Dreams fit naturally as a producer for this memory pipeline: review recent episodes, write candidate durable notes, then
let existing dynamic memory select relevant notes for future prompts.

### Prior memory research already points to sleep-time reflection

`sdd/research/202604/git_versioned_agent_memory.md` recommends a dedicated or hybrid memory repository and explicitly
calls out periodic reflection as a "sleep-time" operation that reviews recent conversation history and persists
important information. It also cites the Letta pattern of initialization, reflection, and defragmentation.

`sdd/research/202605/zettel_sase_shared_memory.md` adds the strongest guardrail: agent transcripts should not become
canonical memory directly. They should feed a distillation layer that produces atomic, linked, reviewable memory.

## Recommended Shape

Implement dreams as an incremental, idempotent "reflection agent" launched by axe.

The pipeline should have four stages:

1. **Discover** recently completed agent runs since the last successful dream.
2. **Select** interesting transcript candidates using cheap deterministic signals.
3. **Distill** selected chats with a hidden background agent.
4. **Persist** dream outputs as reviewable memory candidates plus a durable checkpoint.

## Storage Model

Use a small dream state directory under `~/.sase/dreams/`:

```text
~/.sase/dreams/
  state.json
  runs/
    202605/
      20260509013000.json
      20260509013000.md
  inbox/
    202605/
      20260509013000_sase_memory_candidates.md
```

Recommended `state.json` shape:

```json
{
  "schema_version": 1,
  "last_successful_dream_id": "20260509013000",
  "last_successful_completed_at": "2026-05-09T01:30:00-04:00",
  "last_artifact_timestamp": "20260509012955",
  "processed_chat_ids": [
    "sha256:..."
  ]
}
```

The high-water mark should advance only after the dream output is successfully written. If a dream run fails, the next
cycle should reread the same candidates.

Use `last_artifact_timestamp` or `done.json` mtime as the main cursor, but keep `processed_chat_ids` as a safety net.
The chat ID should be stable across sync and mtime changes. A good ID is a hash of normalized absolute chat path plus
file size and filename timestamp; a stronger but slower fallback is a content hash for selected candidates.

Do not store dream state inside the transcripts. It would make immutable evidence files mutable and would interact badly
with sync.

## Discovery

Prefer an artifact-first collector:

1. Walk `~/.sase/projects/*/artifacts/ace-run/*/done.json`.
2. Keep records with `outcome == "completed"` and a readable `response_path`.
3. Join optional `agent_meta.json`, `workflow_state.json`, and `prompt_step_*.json` from the same artifact directory.
4. Include extra planner/question chats from prompt-step `response_path` or `agent_meta.chat_path` when they differ from
   the final `done.json.response_path`.
5. Fall back to `list_chat_transcripts()` only for legacy chats with no artifact record.

This gives the dream agent metadata it can use to decide importance: project, agent name, provider/model, diff path,
plan path, outcome, hidden flag, prompt snippet, response snippet, and related chat paths.

## Interestingness Filter

The first pass should be deterministic and conservative. The dream agent is expensive; the collector should send it a
bounded candidate set rather than the entire post-checkpoint transcript corpus.

Useful positive signals:

- Agent produced a `diff_path`, `plan_path`, PR URL, commit message, or generated artifact.
- Agent name or prompt suggests design, research, plan, review, bug fix, architecture, memory, xprompt, hooks, tests,
  release, migration, or failure analysis.
- Transcript is linked to planner/question/follow-up chats.
- Transcript includes a nontrivial response and is not just `noop`.
- Agent was manually launched, not an auto-dismissed chop.
- Agent failed after producing useful error context.

Useful negative signals:

- `outcome == "noop"` with no response path.
- Hidden recurring maintenance agents unless they failed.
- Very small transcripts with no diff, plan, or artifact.
- Pure status checks, pollers, stale cleanup, or notification plumbing.
- Retries that are superseded by a successful retry child, unless the failure teaches a durable lesson.

The collector should record why each candidate was selected. That makes dream outputs auditable and lets future tuning
work from evidence instead of vibes.

## Distillation Contract

The dream prompt should ask for structured outputs, not freeform summaries. Recommended output sections:

```markdown
# Dream: 2026-05-09 01:30

## Inputs Reviewed

- <chat id> <agent/project> <path> <selection reasons>

## Durable Memories Proposed

### <short title>

Type: gotcha | convention | architecture | workflow | user preference | open question
Scope: global | project:<name>
Keywords: [...]
Evidence: <chat id/path references>

<distilled memory>

## Non-Memory Findings

- Things worth noting but not promoting to memory.

## Follow-Up Suggestions

- Optional SDD tales, bugs, or cleanup tasks.
```

The agent should be explicitly told:

- Do not copy long transcript passages.
- Do not promote one-off implementation details unless they explain a recurring pattern.
- Keep evidence links to chat paths and artifact directories.
- Prefer small atomic memories over broad summaries.
- Flag contradictions with existing memory instead of overwriting silently.

## Persistence

Dream outputs should land in an inbox first, not directly in `memory/short`.

Best first target:

```text
~/.sase/dreams/inbox/YYYYMM/<dream_id>_<project>_memory_candidates.md
```

Then add a separate promotion path:

- Human or agent reviews inbox notes.
- Approved notes become `memory/long/*.md` with `keywords` frontmatter, or project-local `.sase/memory/long/*.md`.
- Only critical, universally relevant rules become `memory/short/*.md`.

This preserves the existing dynamic memory model and avoids corrupting always-loaded prompt context with one bad dream.

If SASE later implements the dedicated git-versioned memory repo from the April research, the dream inbox becomes the
staging area for that repo.

## Scheduler Integration

Add dreams as an agent chop, not a bespoke daemon.

Sketch:

```yaml
axe:
  lumberjacks:
    memory:
      interval: 3600
      chops:
        - name: dream
          description: "Distill recent agent chats into memory candidates"
          run_every: "6h"
          agent: |
            %hide
            %name:dream
            #sase_dream
```

The `#sase_dream` xprompt should run a deterministic pre-step that builds the candidate bundle, then feed that bundle to
the LLM step. The pre-step should write an artifact containing:

- current checkpoint;
- selected candidate metadata;
- transcript paths;
- bounded excerpts or full paths depending on size;
- selection reasons;
- previous dream output path.

The dream agent itself should be auto-dismissed or hidden. Users should see notifications only for failures or when
there are memory candidates ready for review.

## Idempotence and Concurrency

Dreams should use a lock file, for example `~/.sase/dreams/dream.lock`, because axe dedup prevents duplicate agent chops
with the same prompt but does not protect against manual dream commands or future multi-machine sync.

The state update sequence should be:

1. Acquire lock.
2. Read `state.json`.
3. Build candidate manifest.
4. Run distillation agent.
5. Write dream run files.
6. Atomically replace `state.json`.
7. Release lock.

If the LLM step fails, do not advance `state.json`.

Use the temp-file plus `os.replace()` pattern already used by axe state and other SASE stores.

## Alternatives

### Alternative A: scan raw `~/.sase/chats` every time

This is simple but scales poorly. It also loses metadata that is present in artifacts. It is acceptable only as a
fallback for legacy chats.

### Alternative B: hook dreams after every agent completion

This gives immediate memory but is too noisy and expensive. It also runs before related follow-up agents may finish.
Batching in a periodic dream produces better synthesis.

### Alternative C: promote dream output directly into `memory/long`

This makes new memory available quickly but risks memory poisoning. Use an inbox first. Later, an `--auto-promote` mode
can exist for trusted categories with tests or human approval.

### Alternative D: one global dream for all projects

This is easy to schedule but weak for relevance. The collector should group candidates by project and produce either
one project-scoped dream per active project or one global dream with project sections. Memory promotion should remain
project-aware.

## Implementation Slices

1. Add `sase dreams collect --since-state --json` that builds the candidate manifest without launching an agent.
2. Add `sase dreams run` that acquires the lock, runs the collector, launches or invokes the dream xprompt, writes
   outputs, and advances state on success.
3. Add a built-in `#sase_dream` xprompt.
4. Add an optional axe chop config example, likely disabled by default until the UX is proven.
5. Add a review command for dream inbox files.
6. Later: promotion into git-versioned memory and defragmentation.

## Open Questions

- Should the first version be global or per-project? My recommendation is to collect globally but group and output by
  project.
- Should dreams read full transcripts or only bounded excerpts plus paths? My recommendation is bounded metadata first,
  with full transcript paths available via `@` references for selected candidates.
- Should dream outputs be committed automatically? Not until the memory repo design exists. For now, use plain inbox
  files under `~/.sase/dreams`.
- Should failed agents be included? Yes, selectively. Failures often contain durable gotchas, but they should not
  dominate the dream batch.

## Bottom Line

Dreams should be a periodic reflection pipeline:

- artifact-first discovery;
- deterministic candidate selection;
- hidden axe-launched distillation agent;
- reviewable memory inbox;
- checkpoint advanced only after successful output;
- promotion into `memory/long` or project memory as a separate step.

That fits the existing SASE architecture and keeps raw chats, dream synthesis, and durable prompt memory as separate
layers.
