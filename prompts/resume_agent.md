Can you help me add support for a new `r` (resume) option on the "Agents" tab of the `sase ace` TUI?

- This option should prompt you for a new prompt to continue the conversation, and then use the chat file associated
  with the currently selected DONE agent entry (this option shouldn't be available for RUNNING agents) to invoke a new
  `#resume` xprompt YAML workflow that you create.
- The `#resume` workflow should take a single input, which has a type of `path` and is a path to a markdown file
  containing a chat transcript in the same format that we use for the files stored in the ~/.sase/chats/ directory.
- The workflow should take the contents of the chat file, transform them by adding some pre-text and extra `#`
  characters to each section header, and use that transformed content to populate the `prompt_part` step for that
  workflow. NOTE: We already perform this transformation when using the `gai run` command's `--resume` opion, so re-use
  that code if possible.
- We might need to make sure that that trailing newlines in `prompt_part` fields are preserved when injected, so our
  prompt to use this workflow could be something like

```
#resume:~/.sase/chats/bbugyi200-gh_bbugyi200_sase-260218_193747.md You forgot to add doc comments to the new methods
you added.
```

instead of

```
#resume:~/.sase/chats/bbugyi200-gh_bbugyi200_sase-260218_193747.md

You forgot to add doc comments to the new methods you added.
```

This is a large piece of work that should be split into phases. I'll let you decide how many phases to create, but keep
in mind that each phase will be completed by a distinct `claude` instance.
