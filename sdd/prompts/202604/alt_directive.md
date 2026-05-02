---
plan: sdd/plans/202604/alt_directive.md
---
Can you help me add support for a new `%alt(<text1>,<text2>,<...>)` directive for sase prompts? When the syntax is used
we should run multiple agents one for each text variation that was provided. We should migrate the behavior when `%m` is
given multiple model names as arguments to be just a shorthand for using multiple `%m` directive calls as arguments to
%alt. Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.
