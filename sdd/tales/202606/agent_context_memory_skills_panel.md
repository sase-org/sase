---
create_time: 2026-06-14 11:43:32
status: done
prompt: sdd/prompts/202606/agent_context_memory_skills_panel.md
---
# Plan: "AGENT CONTEXT" metadata panel section (MEMORY + SKILLS)

## Goal

In the `sase ace` TUI Agents-tab metadata panel, replace the standalone **MEMORY READS** section with a new two-level
parent section that groups what the agent _drew upon_ during its run:

```
─────────────────────────────────────────────────
AGENT CONTEXT
  ▸ MEMORY    (migrated from the old MEMORY READS section)
  ▸ SKILLS    (new — the xprompt skills the agent used)
```

This must work uniformly for **all** LLM providers (claude, codex, gemini, qwen, opencode). The design should be
intuitive, reliable, and beautiful — consistent with the existing panel's visual language.

---

## Background / current state (what I found)

- The panel is built as a Rich `Text` in `build_header_text()`
  (`src/sase/ace/tui/widgets/prompt_panel/_agent_display_parts.py`). Major sections are separated by
  `_append_major_section_divider()` (a dim `─`×50 rule) and use a gold-underline header style
  (`bold #D7AF5F underline`). Examples: `OUTPUT VARIABLES`, `AGENT DELTAS`, `AGENT ARTIFACTS`, `MEMORY READS`, `ERROR`.
- **MEMORY READS** is rendered by `append_agent_memory_reads_section()` (`.../prompt_panel/_agent_memory_reads.py`) from
  `summary.memory_reads`, populated in `build_detail_header_summary()` via `load_memory_reads_for_agent()`
  (`src/sase/ace/tui/memory_reads.py`). That loader uses an **mtime-keyed cache + 0.5s throttle** so it is cheap on the
  j/k hot path.
- The underlying audit data is `MemoryReadEvent` rows in `~/.sase/projects/<project>/memory_reads.jsonl`, written by the
  audited `sase memory read` command. Foundation lives in `src/sase/memory/read_log.py` (event model, JSONL append/read
  under a file lock, and **provider-neutral agent attribution** via `discover_agent_identity()` → `SASE_AGENT_NAME` /
  `SASE_AGENT` / `SASE_ARTIFACTS_DIR`→`agent_meta.json`).
- **Critical finding — there is no existing way to know which skills an agent used.** Skills are generated from
  `src/sase/xprompts/skills/*.md` (`skill:` frontmatter) by `sase skills init` / `sase init-skills` and deployed
  per-provider to `~/.<provider>/skills/<name>/SKILL.md`. They are plain Markdown context, not tool calls. The
  per-provider tool-call parsers (`_tool_call_claude.py`, etc.) record nothing for skill use; only Claude even emits a
  `Skill` tool event, and that event's input (the skill name) is **not** persisted in `tool_input_summary` today.
  opencode does not write `tool_calls.jsonl` at all. So passive transcript parsing would be Claude-only and fragile.
- The 13 installable xprompt skills (`bob_dataview`, `sase_agents_status`, `sase_artifact`, `sase_beads`,
  `sase_changespecs`, `sase_chats`, `sase_git_commit`, `sase_hg_commit`, `sase_memory_read`, `sase_notify`, `sase_plan`,
  `sase_questions`, `sase_var`) are each thin wrappers that instruct the agent to run a `sase`/`bob`/`gog` command.
  Notably, the **MEMORY READS section already is, in effect, the `sase_memory_read` skill's usage** — proving the
  audited-command pattern is the right shape here.

---

## Key design decision: how to detect skill usage (reliably, for every provider)

**Recommended: mirror the memory-reads pattern with an audited command.** Add a tiny, fast audit command that records a
skill-use event, and inject a standardized "log this skill use first" directive into **every generated** `SKILL.md` at
generation time (one place in the pipeline, not 13 hand-edits). Detection is then keyed on the agent's environment
identity, exactly like memory reads, so it is **provider-neutral by construction** and reuses proven, locked-JSONL
infrastructure. This honors the repo's "treat all runtimes uniformly" rule (no per-provider branching) and matches the
mental model the user already has from MEMORY READS.

- Reliability is the _same class_ as memory reads (depends on the agent following the skill's first instruction).
  Because the directive is injected by the generator, it is uniform and cannot be forgotten by a skill author.

**Alternatives considered (documented, not chosen):**

1. _Passive tool-call parsing_ of the Claude `Skill` tool event — rejected as primary: Claude-only, breaks the uniform
   -runtimes principle, and opencode logs no tool calls. (Could be added later as corroboration.)
2. _Hooks_ — runtimes support hooks, but there is no uniform "skill invoked" hook event exposed across all five runtimes
   (`PreToolUse`/`PostToolUse` are legacy/unused here), so it is not a reliable uniform trigger.

> **Decision to confirm at review:** proceed with the audited-command approach (requires regenerating skills:
> `sase init-skills --force` + `chezmoi apply`). If you'd rather ship a Claude-only passive version first, say so and
> I'll re-scope.

---

## Naming (chosen, open to your tweak)

- **Parent section: `AGENT CONTEXT`** — consistent with the existing agent-scoped headers `AGENT DELTAS` /
  `AGENT ARTIFACTS`; it reads as "the memory the agent pulled in + the skills it invoked = the structured context behind
  this run."
- **Sub-sections: `MEMORY` and `SKILLS`** (as you specified).
- **CLI: `sase skills log <name> -r/--reason "<why>"`** — folded into the existing `skills` group to avoid a confusing
  `skill` (singular) vs `skills` (plural) pair. (Alt: a new `sase skill` group symmetric with `sase memory read`.)

---

## Technical design (high level)

### 1. Backend: skill-use audit log (`src/sase/skills/use_log.py`)

A near-copy of `memory/read_log.py`, scoped to skills:

- `SkillUseEvent` dataclass:
  `schema_version, id, timestamp, project, cwd, skill_name, agent_name, agent_source, artifacts_dir, reason, runtime`
  (runtime/provider best-effort from env/`agent_meta.json`).
- `skill_use_log_path(project)` → `~/.sase/projects/<project>/skill_uses.jsonl`.
- `build_skill_use_event(...)`, `append_skill_use_event(...)` (locked append), `read_skill_use_events(...)` (skips
  malformed rows), plus light summarizers for symmetry/tests.
- **Reuse agent attribution.** Extract `AgentIdentity` / `discover_agent_identity` / `require_agent_identity` /
  `_agent_name_from_meta` into a shared `src/sase/agent/identity.py` and re-export from `read_log.py` for back-compat
  (no churn at existing call sites). Both features then share one identity source of truth.

> **Rust-core boundary note:** skill-use logging is arguably backend domain behavior. However, the analogous
> memory-reads audit log lives in Python in this repo, so for consistency I propose keeping skill-use logging in Python
> here too. Flagging for your call — if you want it in `../sase-core` to match the boundary policy, that's a scope
> change.

### 2. CLI: `sase skills log`

- Register `log` under the existing `skills` group (`src/sase/main/parser_skills.py`,
  `src/sase/main/skills_handler.py`); new handler in `src/sase/skills/cli_log.py`.
- Args: positional `name`; required `-r/--reason`. Both long+short options; alphabetical, excellent `-h` help; clear
  attribution error when no agent identity is present (mirrors memory-read behavior).

### 3. Skill generation: inject the audit directive

- In `init_skills_handler.py` (around `_render_skill` / `_build_output`), prepend a standardized, imperative first-step
  directive to every generated skill body, parameterized by the skill `name`: _"Before doing anything else, run
  `sase skills log <name> -r "<one-line reason>"` to record that you are using this skill."_ Injected once in the
  pipeline so it applies uniformly to all 13 skills × all providers.
- Regenerate (`sase init-skills --force` + `chezmoi apply`) — this updates the deployed `SKILL.md` files. Honors the
  CLI/skill-contract sync rule from `memory/long/generated_skills.md`.

### 4. TUI loader (`src/sase/ace/tui/skill_uses.py`)

- `load_skill_uses_for_agent(agent, limit=...)` — a structural copy of `memory_reads.py`: mtime-keyed cache + 0.5s
  throttle, per-agent filtering (by realpath `artifacts_dir`, fallback `agent_name`), newest-first, capped. Keeps the
  j/k hot path cheap per `memory/long/tui_perf.md`.
- Add `skill_uses: tuple[SkillUseEvent, ...]` to `_DetailHeaderSummary` and populate it in
  `build_detail_header_summary()` (the existing off-hot-path "expensive enrichments" function).

### 5. TUI rendering: the nested section

- New `append_agent_context_section()` (new `_agent_context.py`, or in `_agent_display_parts.py`) replacing the current
  MEMORY-READS block (lines ~522-529). Behavior:
  - If **both** memory and skills are empty → render nothing (no clutter; matches today).
  - Else → one major divider + `AGENT CONTEXT` header (gold underline), then the two sub-sections.
- **Sub-section visual language (the "beautiful" part):** parent keeps the gold-underline major header; sub-headers use
  a lighter weight + a hierarchy glyph and indent, e.g. `▸ MEMORY` / `▸ SKILLS` in cyan bold (no underline), with the
  body indented under each. An empty sub-section shows a dim `— none recorded —` placeholder so the two-part structure
  is always legible and discoverable (and honest about the audit caveat).
- Refactor `append_agent_memory_reads_section()` into a **sub-section** renderer: drop its own divider, change header
  from `MEMORY READS` to the `▸ MEMORY` sub-header; keep the summary line (`N reads · M files · last HH:MM:SS`) and the
  existing read rows (time, path, `↳ reason`, overflow).
- New `_agent_skill_uses.py` `append_agent_skills_section()`, styled as a sibling of memory reads but with a distinct
  accent for skill names (e.g. green) and a skill glyph: summary line `N uses · M skills · last HH:MM:SS`, then recent
  uses (time, skill name, `↳ reason`) with a `+ N more` overflow. Reuse the shared time/wrap/truncate helpers.

### 6. Tests

- Backend: round-trip + attribution + malformed-row tests for `use_log.py`; identity-extraction tests.
- CLI: `sase skills log` parsing (reason required, short/long opts), event write, attribution-error path.
- Loader: per-agent filtering (artifacts_dir + fallback name), cache/throttle, cap.
- Rendering: `_agent_skill_uses` + combined `AGENT CONTEXT` (empty/one-only/both, overflow, sub-header styling); update
  existing `tests/ace/tui/widgets/test_agent_memory_reads.py` for the sub-header refactor.
- Generation: assert the injected audit directive appears in every generated `SKILL.md` across providers.
- **PNG visual snapshots:** the panel changes, so update goldens via `just test-visual --sase-update-visual-snapshots`
  (per `memory/short/build_and_run.md`).

### 7. Docs / sync obligations

- `?` help-popup / any metadata-panel section list kept in sync if it enumerates sections.
- Run `just check` (after `just install`) before finishing.
- Possible follow-up needing your approval: a note in `memory/long/generated_skills.md` about the injected audit
  directive (I will not edit memory files without approval).

---

## Out of scope / follow-ups

- Passive Claude `Skill`-tool corroboration and an aggregate `sase skills log`-query/dashboard view are left as future
  enhancements.
- Whether to relocate the audit log to `../sase-core` (see boundary note) — deferred to your decision.

## Risks

- **Detection reliability** hinges on agents running the injected first-step command (same risk profile as MEMORY
  READS). Mitigated by uniform generator injection + imperative wording.
- **Regeneration footprint:** ~13 skills × 5 providers of generated `SKILL.md` files change and must be reapplied.
- **Hot-path perf:** mitigated by copying the proven mtime-cache/throttle loader and keeping the load in the existing
  off-hot-path enrichment step.
