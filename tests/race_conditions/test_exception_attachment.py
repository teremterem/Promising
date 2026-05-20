"""Race-condition tests for ``try_to_link_exception``.

Covers deepest-context-wins attachment of
``__promising_context__`` under concurrent re-raise paths, and the
absence of torn writes between ``__promising_context__`` and
``__promising_collapse_traceback__``.
"""
