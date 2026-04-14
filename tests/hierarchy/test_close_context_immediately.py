"""
Tests that a PromisingContext created with ``close_context_immediately=True``
does not leave a stale entry in its parent's ``_unsettled_children``.

A context that is born closed and has no children of its own satisfies
both conditions for unregistration (``_context_closed is True`` and
``_unsettled_children`` is empty), so it must not remain tracked by its
parent.
"""

import promising


async def test_immediately_closed_child_not_in_parent_unsettled_children() -> None:
    """
    A childless context created with ``close_context_immediately=True``
    should unregister from its parent right away — it must not appear in
    ``_unsettled_children``.
    """
    with promising.context() as parent:
        child = promising.PromisingContext(parent=parent, close_context_immediately=True)

        assert child._context_closed
        assert child not in parent._unsettled_children


async def test_immediately_closed_child_not_in_collect_unsettled_children() -> None:
    """
    ``collect_unsettled_children(open_contexts_only=False, futures_only=False)``
    must not include an immediately-closed child that has no active
    descendants.
    """
    with promising.context() as parent:
        promising.PromisingContext(parent=parent, close_context_immediately=True)

        assert parent.collect_unsettled_children(open_contexts_only=False, futures_only=False) == set()


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
        assert parent._unsettled_children == set()
        assert parent not in grandparent._unsettled_children
