"""
Error classes for the promising library.
"""


class BasePromisingError(Exception):
    """
    Base exception class for all promising library errors.
    """


class PromisingContextError(BasePromisingError):
    """
    Base exception class for PromisingContext related errors.
    """


class NoCurrentContextError(PromisingContextError):
    """
    Raised when trying to get the current context but none exists.
    """


class ContextAlreadyActiveError(PromisingContextError):
    """
    Raised when trying to activate a context that is already active.
    """


class ContextNotActiveError(PromisingContextError):
    """
    Raised when trying to finalize a context that is not currently active.
    """
