---
create_time: 2026-04-01 15:41:39
status: done
---

# Add `markdown` Output Mode to `sase search -f|--format`

## Goal

Add a new `markdown` value for `sase search --format` that produces a high-signal, agent-friendly Markdown rendering of
matched ChangeSpecs. The output should be intuitive for readers unfamiliar with ChangeSpec internals, reliable for
machine/agent consumption, and visually clean in plain-text/Markdown contexts.

## Current State

- `sase search` supports two formats:
  - `rich`: styled terminal panels via Rich.
  - `plain`: raw field dump in project-file style.
- Existing formatters are in `src/sase/main/search_handler.py`.
- Current output preserves internal field names (e.g., `COMMITS`, `HOOKS`) but does not explain domain semantics.

## Design Principles

1. Intuitive for non-ChangeSpec agents

- Keep canonical field names for traceability, but pair them with human-readable labels.
- Add a short glossary-style interpretation where terminology is specialized (entry IDs, suffixes, status lines).

2. Reliable and deterministic

- Stable section ordering and stable item ordering.
- Avoid rich/ANSI dependencies in markdown mode.
- Escape markdown-sensitive text to prevent malformed output.

3. Beautiful but practical

- Use headings, tables, and compact bullet lists with minimal noise.
- Keep line widths and nesting shallow enough for both humans and LLMs.

## Proposed Markdown Shape

Top-level document:

- `# Search Results`
- Summary block:
  - query string
  - total matches
  - status breakdown
- Optional glossary note for ChangeSpec concepts.

Per ChangeSpec section:

- `## <index>. <NAME>`
- Metadata table including:
  - Status
  - Project file + line
  - Parent (if present)
  - CL/PR URL (if present)
  - Bug (if present)
- `### Purpose` (DESCRIPTION)
- `### Kickstart` (if present)
- `### Test Targets` (if meaningful)
- `### Running Workspaces` (if active claims exist)
- `### Commits` with itemized entries and attached artifacts (`CHAT`, `DIFF`, `PLAN`)
- `### Hooks` with command + status timeline rows
- `### Comments` as reviewer/file entries
- `### Mentors` as profile/status entries
- `### Timeline` (TIMESTAMPS) when available

Formatting policies:

- Use backticks for IDs, paths, and short tokens.
- Preserve multiline text blocks with fenced code blocks only where needed.
- Normalize home directory in paths to `~` for readability.
- Include suffix/type info verbatim but with short label context (e.g., “status suffix”).

## Implementation Plan

1. Extend CLI parser choices and help

- Update `register_search_parser` to allow `markdown`.
- Update help text to describe markdown intent.

2. Add markdown renderer to search handler

- Introduce `_display_markdown(matching, query)` in `search_handler.py`.
- Route `args.format == "markdown"` to this renderer.
- Keep `plain` and `rich` behavior unchanged.

3. Add small markdown formatting helpers

- Inline-safe escaping helper.
- Path normalization helper.
- Reusable helpers for suffix and optional field formatting.
- Keep helpers local/private unless shared use emerges.

4. Preserve domain fidelity while adding plain-language labels

- Keep canonical field names discoverable in section labels.
- Add one-line explanations in section headers where ambiguity exists.

5. Test coverage

- Add parser test verifying `search --format markdown` is accepted.
- Add renderer-focused tests validating:
  - summary header and status breakdown
  - core fields rendered for a minimal ChangeSpec
  - optional sections appear only when populated
  - multiline and special characters are escaped safely
  - artifact paths and timestamps are included correctly

6. Validation

- Run `just install` (workspace requirement).
- Run targeted tests for new parser/renderer tests.
- Run `just check` before final response.

## Acceptance Criteria

- `sase search <query> -f markdown` executes successfully.
- Output is valid Markdown and readable in plain terminal logs.
- A reader unfamiliar with ChangeSpecs can infer meaning of each section.
- Existing `plain` and `rich` outputs remain unchanged.
- New tests pass and `just check` passes.
