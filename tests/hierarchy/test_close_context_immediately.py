"""
Tests that a PromisingContext created with ``close_context_immediately=True``
does not leave a stale entry in its parent's ``_active_children``.

A context that is born closed and has no children of its own satisfies
both conditions for unregistration (``_context_closed is True`` and
``_active_children`` is empty), so it must not remain tracked by its
parent.
"""

import promising


async def test_immediately_closed_child_not_in_parent_active_children() -> None:
    """
    A childless context created with ``close_context_immediately=True``
    should unregister from its parent right away — it must not appear in
    ``_active_children``.
    """
    with promising.context() as parent:
        child = promising.PromisingContext(parent=parent, close_context_immediately=True)

        assert child._context_closed
        assert child not in parent._active_children


async def test_immediately_closed_child_not_in_collect_active_children() -> None:
    """
    ``collect_active_children(open_contexts_only=False, futures_only=False)``
    must not include an immediately-closed child that has no active
    descendants.
    """
    with promising.context() as parent:
        promising.PromisingContext(parent=parent, close_context_immediately=True)

        assert parent.collect_active_children(open_contexts_only=False, futures_only=False) == set()


async def test_immediately_closed_child_does_not_prevent_parent_cascade() -> None:
    """
    An immediately-closed child must not block the cascading-unregister
    chain.  If a parent has only immediately-closed children, it should
    be considered childless for unregistration purposes.
    """
    with promising.context() as grandparent:
        parent = promising.PromisingContext(parent=grandparent)
        with parent:
            promising.PromisingContext(parent=parent, close_context_immediately=True)
            promising.PromisingContext(parent=parent, close_context_immediately=True)

        # parent exited and its only children were immediately closed
        # → parent should have cascaded out of grandparent
        assert parent._active_children == set()
        assert parent not in grandparent._active_children
