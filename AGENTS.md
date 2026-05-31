# Structured Agentic Software Engineering (SASE) - Agent Instructions

IMPORTANT: You should not modify any of these memory files without approval from the user.

## Short-Term Memory Files

The following memory files contain core (always loaded) context:

<!-- sase-amd:short-memory:start -->

- @memory/short/build_and_run.md
- @memory/short/glossary.md
- @memory/short/gotchas.md
- @memory/short/rust_core_backend_boundary.md
- @memory/short/sase.md
<!-- sase-amd:short-memory:end -->

## Dynamic Memory Files

When a user prompt matches keywords from dynamic memories, we append a `### DYNAMIC MEMORY` section at the bottom of
that prompt listing individual `.sase/memory/` file paths — one per matched memory:

```
### DYNAMIC MEMORY
- @.sase/memory/long-facts-about-foobar.md (memory/long/facts_about_foobar, matched: `foobar facts`)
```

File names use a prefix that encodes the memory source: `long-` means the file originates from a long-term memory
source. If a `long-` prefixed file appears in your dynamic memory section, it contains the same content as the
corresponding long-term memory file below — you do NOT need to separately read the canonical file.

## Long-Term Memory Files

The below files contain detailed reference material. When working in their domain, you MUST use your `/sase_memory_read`
skill to review their contents. Do not read canonical `memory/long/*.md` files directly.

<!-- sase-amd:long-memory:start -->

**`memory/long/generated_skills.md`**  
Skill file generation pipeline, CLI/skill contract synchronization, commit skills per runtime.

**`memory/long/tui_jk_baseline.md`**  
Baseline j/k key-to-paint latency data and reproduction steps.

<!-- sase-amd:long-memory:end -->
