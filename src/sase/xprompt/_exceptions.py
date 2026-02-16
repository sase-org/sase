"""Exception classes for xprompt processing."""


class XPromptError(Exception):
    """Base exception for xprompt processing errors."""

    pass


class XPromptArgumentError(XPromptError):
    """Raised when xprompt arguments don't match placeholders."""

    pass


class DirectiveError(XPromptError):
    """Raised when a prompt directive is invalid (e.g., duplicate known directive)."""

    pass
