---
create_time: 2026-04-12 22:05:13
status: wip
prompt: sdd/prompts/202604/gemini_three_tiers.md
---

# Plan: Refactor ~/.gemini/GEMINI.md into a 3-tier Architecture

## Objective

Refactor the current `~/.gemini/GEMINI.md` file to follow a 3-tier memory architecture (similar to SASE's `AGENTS.md`).
This preserves all existing context while significantly reducing token usage by loading specific contexts dynamically.

## Tier 1: Always Loaded (Short-term Memory)

Create `~/.gemini/memory/short/google3_rules.md` to hold universal, high-priority rules. **Contents:**

- Prohibition on creating/updating CLs.
- Coding standards (doc comments requirement).
- Miscellaneous universal rules (TODO prefix, preference for CodeSearch over find/grep, plan mode and questions skills).

Update `~/.gemini/GEMINI.md` to cleanly load this tier and provide instructions on Tier 2 and Tier 3:

```markdown
# Google3 Workflow and Guidelines

## Tier 1 (short-term) Memory

The following memory files contain core (always loaded) context:

- <!-- Imported from: memory/short/google3_rules.md -->
  ...content...
  <!-- End of import from: memory/short/google3_rules.md -->

## Tier 2 (dynamic) Memory

When your prompt matches keywords from memory-tagged xprompts, sase injects a `DYNAMIC MEMORY: @<memory_file_path>` line
at the bottom of your prompt. `<memory_file_path>` should be the file path of a markdown file that contains some context
gathered by sase based on the prompt.

## Tier 3 (long-term) Memory

The below files contain detailed reference material. Read them when working in their domain.

- **memory/long/golinks_reference.md** - Detailed rules for resolving multi-slash go links and reading golink contents.
```

## Tier 2: Dynamic (Keyword-triggered)

Create xprompt files in `~/xprompts/` directory to act as dynamic memory injected via keyword matching.

1. `~/xprompts/build_cleaner.md`
2. `~/xprompts/buganizer.md`
3. `~/xprompts/golinks.md`
4. `~/xprompts/screenshots.md`

These xprompts will have frontmatter like:

```yaml
---
name: build_cleaner
tags: [memory]
keywords: [build, BUILD, dependency, build_cleaner]
---
```

And will contain the exact content currently in `GEMINI.md` for those sections. `golinks.md` will contain the short
rules and an `@` reference to the Tier 3 file.

## Tier 3: Long-term Reference (Read on Demand)

Create `~/.gemini/memory/long/golinks_reference.md`. **Contents:**

- The full multi-slash resolution algorithm for go links.
- Example resolutions.
- How to read the content of a golink.

## Implementation Steps

1. Create directories `~/.gemini/memory/short/` and `~/.gemini/memory/long/` if they don't exist.
2. Write `~/.gemini/memory/short/google3_rules.md`.
3. Write `~/.gemini/memory/long/golinks_reference.md`.
4. Write `~/xprompts/build_cleaner.md`, `~/xprompts/buganizer.md`, `~/xprompts/golinks.md`, `~/xprompts/screenshots.md`
   with appropriate YAML frontmatter.
5. Replace the contents of `~/.gemini/GEMINI.md` with the new 3-tier structured content.
