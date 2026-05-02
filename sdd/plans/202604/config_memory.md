---
create_time: 2026-04-13 14:10:31
status: done
prompt: sdd/prompts/202604/config_memory.md
---

# Plan: Create `memory/long/config.md` Long-Term Memory File

## Context

The sase configuration system has several non-obvious behaviors — dual list merge strategies, a schema file that isn't
enforced at runtime, local config disabling for the TUI, mentor profile auto-scoping — that would trip up an agent
reading the code alone. There is currently no long-term memory file covering config.

Research (ETH Zurich AGENTbench, 2,500+ repo survey) shows effective agent context files must only contain what agents
**cannot discover independently**. Including derivable information (field lists, enum values, CLI tables) degrades
performance 4+ pp and increases inference costs 20-23%. The filter: "would removing this cause the agent to make
mistakes?"

## What to Include (Non-Derivable)

These are the architectural decisions, invariants, and gotchas an agent would likely get wrong without guidance:

1. **5-layer merge chain with precedence** — The ordering (defaults → plugins → user → overlays → local) and how plugin
   configs are discovered via entry points.

2. **Dual list merge strategies** — User config (layer 3) uses `replace` (wipes default lists), but overlays and local
   config (layers 4-5) use `concatenate` (extend lists). This is the #1 gotcha — agents would assume uniform behavior.

3. **Schema file is informational, not enforced** — `config/sase.schema.json` is for IDE support only. No runtime
   validation occurs. But it **must** be updated whenever config fields are added, removed, or modified so IDE
   validation stays accurate.

4. **Local config disabled for TUI** — `ace_handler.py` calls `set_include_local_config(False)` before starting the TUI.
   Agents modifying TUI startup must preserve this. Agent runs (separate processes) keep local config enabled.

5. **Per-subsystem validation** — No centralized schema enforcement. Each subsystem validates its own config
   independently. Invalid config in one subsystem doesn't break others (errors are logged as warnings, profiles
   skipped).

6. **Mentor profile auto-scoping** — Profiles defined in local `./sase.yml` auto-tag with the detected project name if
   no explicit `projects` list is provided. Setting `projects: []` disables this.

7. **XPrompt alias resolution order** — Aliases are raw string substitutions that run before any other xprompt
   processing. They can introduce syntax needed by later processors (e.g., `#gh_sase` → `#gh:sase` for
   directory-switching).

8. **Environment variable scope** — Only `SASE_WORKSPACE_ROOT` affects config loading (overrides
   `vcs_provider.workspace_root`). Other `SASE_*` env vars are for agent workflows, not config.

## What to Exclude (Derivable from Code)

- Top-level config key listings (read `default_config.yml`)
- Mentor profile field names (read `mentor.py` dataclass)
- Axe/lumberjack config field names (read `axe/config.py`)
- LLM provider field names (read `llm_provider/config.py`)
- Keymap structure (read `keymaps/loader.py`)
- CLI commands like `sase config layers` (read `--help`)
- Full schema property listings (read the schema file)

## Implementation

### Phase 1: Create and Register the Memory File

**Step 1** — Create `memory/long/config.md` (~80-100 lines):

- Frontmatter with keywords: `[config, configuration, sase.yml, schema, merge, default_config, overlay, plugin config]`
- Sections covering the 8 non-derivable items above
- Prominently mention the schema update requirement (item 3)

**Step 2** — Update `AGENTS.md` Tier 3 section:

- Add entry:
  `**memory/long/config.md** - Merge chain precedence, dual list strategies, schema maintenance, local config disabling, auto-scoping. Read when modifying config loading, adding config fields, or changing merge behavior.`
- Insert alphabetically (after `changespec_lifecycle.md`, before `external_repos.md`)

**Step 3** — Run `just check` to verify nothing is broken.
