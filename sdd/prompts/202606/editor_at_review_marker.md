---
plan: sdd/tales/202606/editor_at_review_marker.md
---
 Can you help me get rid of the `%edit` directive? Instead, let's migrate the same behavior to a new syntax. Namely, if any line of the submitted prompt (from the user's editor) ends with ` @`, we strip those characters from that line and load the prompt (or prompts, in the case of a multi-agent prompt--don't forget the xprompt/frontmatter properties) in the prompt input widget. Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the
`sase plan propose` command (as the skill instructs) before making any file changes.
