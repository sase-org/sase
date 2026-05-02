---
create_time: 2026-04-29 00:45:21
status: done
bead_id: sase-15
prompt: sdd/prompts/202604/sase_chats_skill_1.md
---
# Plan: `/sase_chats` Skill for Agent Chat Transcript Access

## Problem

SASE already saves agent conversations as markdown chat histories under `~/.sase/chats/`, sharded by month. Named agent
artifacts also point at those histories through `done.json["response_path"]` for completed agents and sometimes
`agent_meta.json["chat_path"]` for in-progress or fallback cases. Existing xprompts such as `#resume` and
`#resume_by_chat` can inline a transcript into a new prompt, but there is no first-class skill or stable command recipe
for an agent that is simply asked "what did the previous agent say?" or "look at the transcript from agent X."

The requested `/sase_chats` xprompt skill should give agents a reliable, low-friction way to discover, resolve, inspect,
and summarize prior SASE agent chat transcripts.

## Current Context

- Generated skill sources live in `src/sase/xprompts/skills/` and are rendered by `sase init-skills`.
- `/sase_agents_status` is implemented as `src/sase/xprompts/skills/sase_agents_status.md`: front matter with
  `skill: true`, a trigger description, a primary command, and summarization rules.
- Chat histories are managed in `src/sase/history/chat.py`.
- Existing useful APIs:
  - `list_chat_histories()` returns recent chat basenames.
  - `_load_chat_history()` loads by basename or path.
  - `load_chat_for_resume()` returns flat User/Assistant turns and expands nested resume references.
  - `extract_response_from_chat_file()` extracts the latest response.
  - `find_named_agent()` resolves named agents across project artifact dirs.
- Existing `#resume` resolution already demonstrates the desired fallback order:
  - completed named agent `done.json["response_path"]`
  - any named agent `agent_meta.json["chat_path"]`

## Design Direction

Do not make the new skill teach agents to hand-scan `~/.sase/chats` or parse artifact metadata inline. That would be
fragile and repetitive. Instead, add a small first-class `sase chats` CLI with stable JSON output, then make
`/sase_chats` a concise generated skill that tells agents which commands to run and how to summarize the results.

The CLI should be intentionally narrow:

```text
sase chats list -j
sase chats list -j -l 20
sase chats list -j -q '<text>'
sase chats show --agent <name>
sase chats show --path <path>
sase chats show --basename <basename>
sase chats show --agent <name> -f response
sase chats show --agent <name> -f resume
```

JSON list output should be stable and cheap to summarize. Raw transcript output should remain plain markdown so agents
can quote or summarize from the actual source file. `show -f resume` should reuse `load_chat_for_resume()` for flattened
conversation context; `show -f response` should reuse `extract_response_from_chat_file()` for "what did they conclude?"
questions.

## Phase 1: Chat Catalog Foundation

Build the reusable transcript discovery and resolution layer. This phase should not add parser wiring or the skill yet.

### Scope

- Add a focused helper module, preferably `src/sase/history/chat_catalog.py`, rather than overloading
  `src/sase/history/chat.py`.
- Define a small dataclass such as `ChatTranscriptInfo` with:
  - `path` (`~`-prefixed display path)
  - `absolute_path`
  - `basename`
  - `mtime`
  - `size_bytes`
  - best-effort `workflow`, `agent`, and `timestamp` parsed from the filename/header
  - short `prompt_snippet` and `response_snippet`
- Add `list_chat_transcripts(limit: int | None = None, query: str | None = None)`.
  - Iterate with `iter_sharded_files("chats", pattern="*.md")`.
  - Include legacy top-level chats automatically through existing sharded-file helpers.
  - Sort newest first by mtime.
  - Apply `query` as a case-insensitive content/path/basename search after cheap path checks.
  - Bound snippet reads so a very large transcript does not slow the list command.
- Add `resolve_chat_ref(agent: str | None, path: str | None, basename: str | None) -> str`.
  - Exactly one selector is required.
  - `--agent` follows the existing `#resume` fallback order: done `response_path`, then meta `chat_path`.
  - `--path` expands `~` and validates existence.
  - `--basename` uses existing chat basename resolution behavior.
- Add serialization helper `chat_info_to_json(info)` with stable key order.

### Tests

- Unit tests under `tests/history/`, using `redirect_sase_home()`.
- Cover sharded chats, legacy/basename resolution, newest-first ordering, limit, query filtering, snippets, malformed or
  giant transcript tolerance, and named-agent resolution from `done.json`.
- Include fallback from `agent_meta.json["chat_path"]` for a named agent without `done.json["response_path"]`.

### Acceptance

- Foundation helpers pass unit tests without requiring any live `~/.sase` data.
- No user-facing CLI behavior changes yet.

## Phase 2: `sase chats` CLI

Expose the foundation through a stable command surface suitable for agent skills.

### Scope

- Add parser registration, likely in `src/sase/main/parser_chats.py`, and wire it into the main parser/entry flow.
- Add a handler, likely `src/sase/main/chats_handler.py`.
- Add CLI implementation under a small package such as `src/sase/chats/`.
- Commands:
  - `sase chats list`
  - `sase chats show`
- `list` options:
  - `-j, --json` for machine-readable output.
  - `-l, --limit` with a conservative default, e.g. 20.
  - `-q, --query` for simple content/path search.
  - Optional pretty table for terminal use, but JSON is the primary skill contract.
- `show` options:
  - One selector: `-n, --agent`, `-p, --path`, or `-b, --basename`.
  - `-f, --format` with `raw`, `resume`, and `response`; default `raw`.
  - `raw` prints the transcript markdown.
  - `resume` prints `load_chat_for_resume(path)`.
  - `response` prints `extract_response_from_chat_file(path)` and exits non-zero if no response can be parsed.
- Error behavior:
  - Missing selector or multiple selectors: argparse error.
  - Unknown agent/chat: stderr plus exit code 2.
  - Corrupt/unreadable file: stderr plus exit code 1 or 2 depending on whether the selector resolved.

### JSON Shape

`sase chats list -j` should emit an array of objects with stable key order:

```json
{
  "path": "~/.sase/chats/202604/example-run-a-260429_101500.md",
  "basename": "example-run-a-260429_101500",
  "mtime": "2026-04-29T10:15:08-04:00",
  "size_bytes": 12345,
  "workflow": "run",
  "agent": "a",
  "timestamp": "260429_101500",
  "prompt_snippet": "Can you help me...",
  "response_snippet": "Implemented the..."
}
```

### Tests

- Handler/parser tests under `tests/main/`.
- Verify JSON key presence/order, limit behavior, query behavior, selector validation, raw/resume/response output, named
  agent lookup, and friendly failures.

### Acceptance

- `sase chats list -j -l 5` works from a real workspace.
- `sase chats show --agent <name> -f response` can answer "what did agent `<name>` conclude?"
- `just check` passes after `just install` if needed.

## Phase 3: Generated `/sase_chats` Skill

Add the agent-facing xprompt skill modeled after `/sase_agents_status`.

### Scope

- Add `src/sase/xprompts/skills/sase_chats.md`.
- Front matter:
  - `name: sase_chats`
  - `skill: true`
  - Description should explicitly trigger on previous chats, chat transcripts, prior agent conversations, "what did
    agent X say?", "summarize the previous agent", and similar wording.
- Body should include:
  - Primary command: `sase chats list -j`.
  - Exact named-agent lookup: `sase chats show --agent <name>`.
  - Raw path/basename lookup.
  - `-f response` for latest answer/conclusion.
  - `-f resume` when full chronological context is needed.
  - Summarization rules: cite the agent name/path, distinguish prompt vs response, avoid fabricating missing
    transcripts, and use short excerpts only when necessary.
  - Guidance to prefer JSON list output for discovery and raw/show output for source-grounded answers.
- Regenerate generated skills with:

```bash
sase init-skills --force --no-commit --no-push --no-apply
```

Use `--dry-run` first if the implementing agent wants to inspect output before writing generated files.

### Tests

- Add or extend init-skills tests to confirm `sase_chats` is discovered as a generated skill for all providers.
- Add a small catalog/frontmatter test if existing tests do not already cover skill source discovery.

### Acceptance

- `/sase_chats` appears in generated provider skill output.
- Future agents receive the skill when the user asks about previous agent chats.
- The skill text is concise enough to be useful as always-loaded skill guidance.

## Phase 4: Integration Polish and Documentation

Make the new surface coherent with nearby agent tooling.

### Scope

- Update any relevant help text or docs that list agent-facing commands.
- Consider adding `chat_path`/`response_path` to `sase agents status -a -j` only if it stays backward-compatible and
  helps bridge from status to chats. This is optional; `sase chats show --agent` should be the primary bridge.
- If a dynamic memory entry exists for agent/status tooling, add a small entry or keyword rule for chat transcript
  questions only if the generated skill alone is not sufficient in practice.
- Run the real commands against current local data and capture any rough edges:
  - `sase chats list -j -l 5`
  - `sase chats show --agent <recent-name> -f response`
  - `sase init-skills --force --no-commit --no-push --no-apply`
  - `just check`

### Acceptance

- The CLI, generated skill, and docs agree on command names and options.
- Agent-facing guidance has one canonical path: use `/sase_chats`, which in turn uses `sase chats`.
- No generated chezmoi files are hand-edited.

## Phase Dependencies

- Phase 1 blocks Phase 2.
- Phase 2 blocks Phase 3 because the skill should document stable commands, not provisional filesystem recipes.
- Phase 3 can land before Phase 4 if the CLI is complete.
- Phase 4 should be the final consistency pass by a distinct agent instance.

## Non-Goals

- Do not replace `#resume` or `#resume_by_chat`; they remain the right tools for continuing a conversation.
- Do not build semantic search or embeddings over transcripts in this change.
- Do not add a TUI transcript browser; the skill needs a command-line surface first.
- Do not change chat file format unless a later phase discovers a hard blocker.
- Do not hand-edit generated provider skill files in chezmoi; use `sase init-skills`.

## Risks

- Filename parsing is best-effort because branch/workflow/agent segments are not fully self-describing. The canonical
  identity should remain `path` and `basename`; parsed `workflow`/`agent` fields may be null when ambiguous.
- Full-content query across many large transcripts could be slow. Keep the default listing bounded, do cheap path checks
  first, and avoid reading entire huge files just for snippets.
- Named-agent resolution can find historical/dismissed artifacts whose chat file was later removed. Report this plainly
  rather than falling back to an unrelated transcript.
- `response` extraction depends on recognizable Prompt/Response headings. If parsing fails, fail loudly and suggest raw
  output instead of returning misleading partial content.
