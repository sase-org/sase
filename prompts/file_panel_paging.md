When the files in the file panel on the "Agents" tab of the `sase ace` TUI get too big, it really slows down the TUI.
Can you help me start trimming each file's contents to just fill the panel size?

- The user should have new keymaps to populate another N lines (where N is the number of lines that fit in the panel
  currently) in the panel incrementally, to decrement the file contents by N lines (they should only be able to
  decrement the file contents down to the original trimmed size, not all the way down to zero). The user should also
  have a keymap to reset the file contents back to the original trimmed size and another keymap that shows all of the
  lines in the file.
- We should also auto-increment N if the user attempts to scroll down using the `ctrl+d` keymap when they are already at
  the bottom of the file contents in the panel. The scroll down operation should then scroll down appropriately after
  the new lines load.
- The user should be able to see how many lines are currently being shown for each file in the panel, and how many lines
  are being hidden.
- When `sase ace` is restarted, we should forget all of the user's previous trimming and show the original trimmed size
  for each file in the panel again.

Other than the requirements above, I want you to take the lead on the design of this feature. Make it as simple as
possible (but not simpler) and make it beautiful!

NOTE: This is a large piece of work that should be split into phases. I'll let you decide how many phases to create, but
keep in mind that each phase will be completed by a distinct `claude` instance.
