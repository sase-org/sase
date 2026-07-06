---
plan: sdd/tales/202607/tab_onboarding_quickstart.md
---
 On the Agents tab and the PRs tab in the TUI, we currently show onboarding pages specific to those tabs when there's nothing else interesting to show. Can you help me make several big improvements to those pages?

- The content that we show there now should be preserved via the `,?` keymap that already exists and shows the contents for these pages in a pop-up panel.
- The new content will be very different. We'll start with a one to two sentence summary of what the tab is all about. Then we'll describe the five to seven most important global keymaps that the user Would most likely find value from if they don't know where to get started or if they are just getting started (i.e. configuring sase, installing plugins, etc...)
- The logic that decides when we show the onboarding page for the PRs tab is currently broken. What we should do instead is always show the search query up top but if there is no content to the query (as in no PRs matched), we should show the onboarding page in the search results panel. This onboarding page should be identical except for the description of the tab (Which should describe the PRs tab instead of the Agents tab).
- I want you to lead the design on this one. Make sure you design this feature so it is intuitive, reliable, and (last but not least) beautiful!

Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the
`sase plan propose` command (as the skill instructs) before making any file changes.
 