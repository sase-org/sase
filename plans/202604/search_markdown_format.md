---
create_time: 2026-04-01 15:35:17
status: done
---

# Add `markdown` output mode to `sase search`

## Objective

Add a new `-f|--format markdown` mode to `sase search` that renders matching ChangeSpecs as polished, readable Markdown
while preserving existing behavior for `plain` and `rich` formats.

## Product Design

### User-facing behavior

- `sase search <query> -f markdown` prints Markdown to stdout.
- Output remains deterministic and copy-paste friendly for docs, PR descriptions, and chat.
- Existing behavior is unchanged for `plain` and `rich`.
- No-match and query-parse error behavior remains unchanged.

### Markdown information architecture

- Document title section with query and result count.
- Per-ChangeSpec section as `## <name>` with compact metadata first.
- Structured sections only when data exists:
  - Description / Kickstart as blockquotes for readable multi-line prose.
  - Running claims as table.
  - Commits / Hooks / Comments / Mentors as bullets with consistent indentation.
- Final summary section with status breakdown and quick links (name anchors).

### Formatting principles

- Intuitive: same semantic ordering as current ChangeSpec display.
- Reliable: omit empty fields, normalize paths to `~`, escape Markdown-special characters in free text where needed.
- Beautiful: clear hierarchy, balanced whitespace, concise but expressive headings.

## Technical Design

### Parser changes

- Extend `register_search_parser` choices from `plain|rich` to `plain|rich|markdown`.
- Update help text to describe markdown usage.

### Search handler changes

- In `handle_search_command`, route `args.format == "markdown"` to new renderer.
- Implement `_display_markdown(matching: list)` in `search_handler.py`.
- Add small helper utilities in same module for:
  - Markdown escaping for inline text.
  - Formatting multi-line blocks and optional sections.
  - Rendering status breakdown summary.

### Rendering detail strategy

- Header:
  - `# ChangeSpec Search Results`
  - `**Query:** <query>`
  - `**Matches:** N`
- For each ChangeSpec:
  - `## <name>`
  - metadata bullets (`Status`, `Path:line`, optional `Parent`, optional `CL/PR`, optional `Bug`, optional
    `Test Targets`)
  - `### Description` and optional `### Kickstart` as quoted blocks
  - Optional sections in this order: `Running`, `Commits`, `Hooks`, `Comments`, `Mentors`
- Footer summary:
  - `## Summary`
  - status counts bullet list
  - quick-jump list of names

## Validation Strategy

### Unit tests

Add a dedicated `tests/test_search_command.py` covering:

- Parser accepts `--format markdown`.
- Markdown renderer includes required structure for a fully populated mock ChangeSpec.
- Optional/empty fields are omitted cleanly.
- Existing dispatch still calls `plain` and `rich` paths correctly.

### Regression checks

- Run targeted tests for new file(s).
- Run `just install` (workspace setup prerequisite).
- Run `just check` before finishing (per repo instruction).

## Risks and mitigations

- Risk: Markdown escaping breaks readability.
  - Mitigation: Escape only inline control characters; keep body text minimally transformed.
- Risk: Output drift from existing field semantics.
  - Mitigation: Preserve field ordering and labels aligned with current displays.
- Risk: brittle tests due full-string equality.
  - Mitigation: assert key sections/tokens and ordering-sensitive anchors only where valuable.
