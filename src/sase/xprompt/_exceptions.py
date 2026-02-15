"""Exception classes for xprompt processing."""


class XPromptError(Exception):
    """Base exception for xprompt processing errors."""



class XPromptArgumentError(XPromptError):
    """Raised when xprompt arguments don't match placeholders."""

