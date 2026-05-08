---
plan: sdd/epics/202605/artifacts_keymap.md
---
 Can you help me generalize the `V` (view image) keymap on the "Agents" tab of the `sase ace` TUI?

This is a large piece of work that should be split into phases. I'll let you decide how many phases to create, but
keep in mind that each phase will be completed by a distinct agent instance (i.e. a distinct `claude` / `gemini` /
`codex` / `qwen` / `opencode` command). Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.



- Let's change this keymap to `A` (artifacts).
- The big improvement is that we will support viewing markdown files (as PDFs which are converted into PNG images using
  the `pdftoppm -png <pdf_path> <png_path_prefix>` command) in addition to images.
- When the user views a markdown file as a PDF, we should use `kitten icat` to show each PNG file created by `pdftoppm`,
  in order, one at a time. The user should be able to go to the next image with the `n` key, the previous image with the
  `p` key, and back to the TUI with the `q` key. If there is only one available artifact associated with this agent
  (which will be the chat transcript--see the next section), we should use it by default (no user prompt). Otherwise, we
  should show the user a new artifact panel that allows them to select one of the available artifacts with a single
  keypress.

### What other artifacts can an agent have?

- By default, every done agent has one artifact: its chat transcript (i.e. the markdown file in the ~/.sase/chats/
  directory).
- Plan files (submitted via `sase plan` by the agent) are also artifacts.
- Any image file the agent added/modified (regardless of whether or not it is visible in the file panel currently) is an
  artifact.

#### Artifacts Created via the New `sase artifact create` Command

- Finally, the agent can be instructed to "create a new sase artifact" by the user, which should cause it to use its new
  `/sase_artifact` skill.
- This skill will instruct the agent to create a file (whatever type of file the user asked the agent to create) and
  then call the new `sase artifact create` command.
- This command will move the file to the new ~/.sase/artifacts/ directory and permenantly (even if dismissed and then
  later revived) associate it with the current agent (you'll need to figure out how to do this).
- We should display all of these artifacts in as entries of a new ARTIFACTS field in the agent metadata panel when this
  agent is selected.