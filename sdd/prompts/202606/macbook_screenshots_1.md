---
plan: sdd/tales/202606/macbook_screenshots_1.md
---
 I want to add support to sase for taking screenshots from my macbook that I can then reference in prompts on
this machine. Can you help me implement this? See the requirements below for further context.

- We can accomplish this by using the apollo SSH host (see the ~/.ssh/config file) as a proxy since both this machine
  and my macbook have passwordless (via private/public SSH key pairs) access to the apollo machine (this machine needs
  2-factor authentication to SSH into).
- You will need to implement a bash script (in my chezmoi repo) that I can run on my mac to trigger the native
  screenshot app (using a custom capture that the user can move and resize). The screenshot should be stored to the
  `~/tmp/screenshots/<timestamp>.png` (or `.jpeg` or some other image type--whatever you think will work best) file. We
  should then copy that file to the same file location on the apollo machine.
- I want to be able to trigger the bash script mentioned in the previous bullet on my macbook, using Hammerspoon (see
  the config in my chezmoi repo), with a new `<ctrl+alt+shift+s>` keymap.
- You will also need to implement a new `#sshot` xprompt workflow (also in my chezmoi repo) that takes an optional,
  integer `n` argument, which defaults to `1`. This argument should determine which screenshot the xprompt workflow
  fetches from the apollow machine (we should fetch the `n`th most recent screenshot--for example, `1` means that we
  should fetch the last screenshot that was uploaded to the `~/tmp/screenshots/` directory on the apollo machine). The
  `#sshot` xprompt workflow should have a `prompt_part` step that resolves to the file path (in the `~/tmp/screenshots/`
  directory) of the screenshot we just fetched from apollo.

Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the
`sase plan propose` command (as the skill instructs) before making any file changes.
