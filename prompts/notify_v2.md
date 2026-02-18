Can you help me make some improvements to the notification system? Split this work up into phases (parallel if
possible). You can decide how many phases there should be, but keep in mind that each phase will be handed off to a
distinct `claude` instance.

## Notification Popup (`N` keymap)

I want to make some changes to the notification popup that is triggered by the `N` keymap in the `sase ace` TUI? I want
the popup to be much bigger. It should take up almost the whole screen, but not quite.

I also want to get rid of the keymap that shows the file list and instead always show the contents of one of the files
in a pane on the right, then allow the user to use the Ctrl+N and Ctrl+P keymaps to switch between the different
available files.

## NEW Notification Indicator

I want to add a new notification indicator that shows the number of unread notifications. This should be displayed in
the top right hand corner of the `sase ace` TUI. Make sure that an audible bell is rung everytime a new notification is
received, and that the notification count is updated accordingly. This indicator should ALWAYS be visible, even when
there are no notifications, in which case it should show some indication that there are no notifications.

## Expected Files Sent by Senders

- All agents are expected to send their `~/.sase/chats/*.md` files
- Any agent that makes file changes when one of the #hg, #git, or #gh workflows are embedded should save a diff file and
  send that as well.
