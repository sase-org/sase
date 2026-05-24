# Structured Agentic Software Engineering (SASE) - Agent Instructions

IMPORTANT: You should not modify any of these memory files without approval from the user.

## Tier 1 (short-term) Memory

The following memory files contain core (always loaded) context:

- @memory/short/build_and_run.md
- @memory/short/glossary.md
- @memory/short/gotchas.md
- @memory/short/rust_core_backend_boundary.md
- @memory/short/sase.md

## Tier 2 (dynamic) Memory

When a user prompt matches keywords from dynamic memories, we append a `### DYNAMIC MEMORY` section at the bottom of
that prompt listing individual `.sase/memory/` file paths — one per matched memory:

```
### DYNAMIC MEMORY
- @.sase/memory/long-facts-about-foobar.md (memory/long/facts_about_foobar, matched: `foobar facts`)
```

File names use a prefix that encodes the source tier: `long-` means the file originates from a long-term (tier 3) memory
source. If a `long-` prefixed file appears in your dynamic memory section, it contains the same content as the
corresponding tier 3 file below — you do NOT need to separately read the tier 3 file.

## Tier 3 (long-term) Memory

The below files contain detailed reference material. When working in their domain, you MUST use `/sase_memory_read` and
perform the audited `sase memory read` workflow. Do not read canonical `memory/long/*.md` files directly.

#### Long-Term Memory Files

**`memory/long/generated_skills.md`**  
Skill file generation pipeline, CLI/skill contract synchronization, commit skills per runtime. _Read when modifying
skill source files or the commit workflow._

**`memory/long/tui_jk_baseline.md`**  
Baseline j/k key-to-paint latency data and reproduction steps. _Read when working on TUI navigation latency or related
performance instrumentation._
