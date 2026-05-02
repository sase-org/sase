---
plan: sdd/plans/202604/negative_memory_keywords.md
---
 Can you help me add support for negative matches to memory xprompts and long-term memory files (by extension)? Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.


### Additional Requirements

- Let's use the same 'keywords' field, but allow entries to be prefixed with "!" to indicate that the given keyword is a negative/anti keyword.

### Update 2026-04-24

The blanket-veto rule described above was refined shortly after landing. A negative keyword now only excludes a memory when removing the text it matched from the prompt would leave no positive-keyword hits — i.e. it is a contextual carve-out around _where_ a positive matched, not a blanket veto. See `specs/202604/negative_keyword_masking.md` and `plans/202604/negative_keyword_masking.md` for the refined semantics.