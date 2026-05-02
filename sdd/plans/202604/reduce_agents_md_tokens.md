---
create_time: 2026-04-12 18:21:43
status: done
prompt: sdd/prompts/202604/reduce_agents_md_tokens.md
---

# Plan: Reduce AGENTS.md Token Usage

Remove instructions from memory/ files that don't add value — either because the agent can discover them from
code/config, or because they belong in on-demand context rather than always-on.

## Changes

### 1. Delete `memory/e2e_testing.md` and remove from AGENTS.md (~500+ tokens saved)

The largest memory file at ~56 lines. It's a full API reference with code examples for the AcePage testing DSL — exactly
the kind of "testing patterns and templates" that research says belongs in on-demand skills, not always-on context.

**Why safe to remove:**

- The agent can read `sase/ace/testing.py` source code when it needs the API
- Existing tests in the test suite serve as working examples
- This file is loaded on every session even when the agent isn't writing tests

**Actions:**

- Delete `memory/e2e_testing.md`
- Remove the `@memory/e2e_testing.md` line from `AGENTS.md`

### 2. Trim `memory/architecture.md` (~150 tokens saved)

**Remove the project overview bullets.** All 5 bullets (project overview, layout, entry point, config, testing) are
discoverable from `pyproject.toml` and directory structure. Research: "architectural overviews without actionable
specifics produce the same agent behavior at lower token cost."

**Compress the glossary.** The ChangeSpec definition is ~4 lines of prose; the xprompt definitions span ~8 lines with
redundant explanation. Compress to terse definitions that preserve the non-obvious parts (file locations, status
lifecycle, the Part vs Workflow distinction).

### 3. Trim `memory/code_conventions.md` (~80 tokens saved)

**Remove rules enforced by tooling** that the agent discovers from `pyproject.toml`:

- "Target Python 3.12+" — in `requires-python`
- "Follow ruff rules: E, W, F, I, B, C4, UP" — in `[tool.ruff]` config
- "Type annotations on all public functions" — enforced by mypy config
- "Use absolute imports" — enforced by ruff rule I (isort)

**Keep the non-obvious policies** that the agent would get wrong without guidance:

- Short options rule (proven correction — also in user's auto-memory)
- Keymap config update reminder
- Runtime uniformity rule

### 4. Leave these files unchanged

- **`build_and_run.md`** — 11 lines, all critical behavioral rules
- **`external_repos.md`** — Non-obvious repo locations + critical behavioral rules
- **`generated_skills.md`** — Policy decisions and behavioral overrides
- **`workspaces.md`** — 10 lines, non-obvious workspace isolation

## Estimated total savings

~730+ tokens removed from always-on context per session.
