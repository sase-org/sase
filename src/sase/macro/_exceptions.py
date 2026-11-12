"""Exception classes for macro processing."""


class MacroError(Exception):
    """Base exception for macro processing errors."""

    pass


class MacroArgumentError(MacroError):
    """Raised when macro arguments don't match placeholders."""

    pass


class DirectiveError(MacroError):
    """Raised when a prompt directive is invalid (e.g., duplicate known directive)."""

    pass


class LocalMacroTrustError(MacroError):
    """Raised when an explicit local executable macro is blocked by trust."""

    pass
