# {{ title }}

IMPORTANT: You should not modify any of these memory files without approval from the user. However, when the user
explicitly asks you to update a SASE memory file, that request already carries the required approval for the full
workflow: make the requested edit to the canonical note under `sase/memory/`, then you MUST run `sase memory init` to
regenerate `AGENTS.md`, the provider instruction shims, and the memory README. Do NOT ask for separate permission to
initialize sase memory in that case.

## Tier 1 (short-term) Memory

The following memories contain core (always loaded) context:

{{ tier1_sections }}

## Tier 2 (long-term) Memory

The below files contain detailed reference material. When working in their domain, you MUST use your `/sase_memory_read`
skill to review their contents. Do not read canonical memory files directly.

{{ tier2_entries }}
