"""Race-condition tests for ``__active_context`` ``ContextVar``.

Covers per-task isolation, non-reentrant ``__enter__``, cross-thread
context inheritance via ``copy_context`` into thread-pool workers, and
no active-context bleed across reused worker invocations.
"""
