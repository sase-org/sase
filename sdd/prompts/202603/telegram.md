Can you help me integrate sase with telegram? I've already set up a bot account. See the
@sdd/research/202602/telegram_integration.md file for context. The bot user name and chat ID are stored in environment
variables (`SASE_TELEGRAM_BOT_USERNAME` and `SASE_TELEGRAM_BOT_CHAT_ID`, respectively) and the API token can be
retrieved by using the `pass show telegram_sase_bot_token` command. Some design decisions:

- We should use the python-telegram-bot library since I want to support inline keyboards (for "Approve" and "Reject"
  buttons for plan notifications, for example). These chop scripts are complicated enough to warrant their own repo, so
  let's put these in a new ~/projects/github/bbugyi200/sase-telegram/ directory. Use all of the same modern best
  practices that we use for the sase repo (ex: Justfile, hatch packaging, etc.).
- Chops don't support their own configuration at the moment, so we will not support any user configuration.
- **Question**: What should trigger outbound messages? **Answer**:
  - We should start tracking user-activity in the `sase ace` TUI (make sure this is VERY fast so it doesn't slow down
    user interaction with the TUI) and which notifications have been received since the last time the user interacted
    with `sase ace`.
  - When the user has been inactive for `N` seconds (defaults to 600, but is optionally configurabe via an environment
    variable), we should send a message for each new notification that has been received since the last user
    interaction.
  - We should also add a new `I` keymap to the `sase ace` TUI that allows users to mark themselves as inactive.
  - This will require changes to the core codebase and (likely) a new public API method that chops can use.
- **Question** How should outbound messages be formatted and what content should be included? **Answer**:
  - I want you to take the lead on this design, but err on the side of including too much rather than too little. And
    make sure that the formatting you decide on results in beautiful outbound messsages! One constraint: We NEED to
    support inline keyboards for as many actions as possible (at least "Approve" and "Reject" buttons for plan
    notifications, but ideally for all actionable notifications). Also, think about how you can use file attachments to
    include more content with cluttering the message.
- We should support some kind of rate limiting to make sure I don't get 100 messages in 10 seconds, for example. But we
  do not need to support "quiet hours".

This is a large piece of work that should be split into phases. I'll let you decide how many phases to create, but keep
in mind that each phase will be completed by a distinct `claude` instance. Write your plan to a new plans/telegram.md
file, but do NOT create any beads for it.
