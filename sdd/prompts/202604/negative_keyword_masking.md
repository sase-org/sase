---
plan: sdd/plans/202604/negative_keyword_masking.md
---
  Negative memory keywords (those prefixed with an "!") should only prevent dynamic memory matches when those negative keywords being removed would cause no positive matches to be found. For example, assume the following keywords: [foo, "!/foo/"]. This would match the prompt "Add foo to the /path/to/foo/ directory", but not match the prompt "Add bar to the /path/to/foo/ directory". Can you help me fix this? Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.
