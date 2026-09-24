"""Mounted metadata bottom-follow behavior for the prompt panel.

The legacy `#agent-prompt-scroll` bottom-pin cases were deleted by
sase-17d.10.1.1; decks are the only runtime path. The essential pin cases
(growth keeps the view at the end, a relative scroll releases the pin) were
migrated to the focused deck panel's Main scroll in
`tests/ace/tui/widgets/decks/test_deck_panels.py`.
"""
