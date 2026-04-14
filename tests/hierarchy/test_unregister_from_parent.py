"""
Tests for the automatic unregistration of a PromisingContext from its parent.

A context unregisters itself from its parent when both conditions are met:
1. The context has been exited (``_context_closed`` is True).
2. The context has no active children left.

This means unregistration can be triggered by two different events:
- Exiting the context when it already has no active children.
- The last active child being unregistered from a context that was
  already exited.
"""

import promising


async def test_unregisters_from_parent_on_exit_when_no_children() -> None:
    """
    A childless context unregisters itself from its parent immediately
    upon exit.
    """
    with promising.context() as parent:
        child = promising.PromisingContext(parent=parent)
        assert child in parent._unsettled_children

        with child:
            pass

        assert child not in parent._unsettled_children


async def test_does_not_unregister_from_parent_on_exit_when_children_remain() -> None:
    """
    A context that still has active children does NOT unregister itself
    from its parent upon exit — it must stay visible in the hierarchy
    until its own children are done.
    """
    with promising.context() as grandparent:
        parent = promising.PromisingContext(parent=grandparent)
        with parent:
            grandchild = promising.PromisingContext(parent=parent)
            assert grandchild in parent._unsettled_children

        # parent has exited but grandchild is still registered
        assert grandchild in parent._unsettled_children
        assert parent in grandparent._unsettled_children


async def test_unregisters_from_parent_when_last_child_is_unregistered() -> None:
    """
    When a context was already exited but had active children keeping it
    registered in its parent, unregistering the last child triggers the
    deferred unregistration from the parent.
    """
    with promising.context() as grandparent:
        parent = promising.PromisingContext(parent=grandparent)
        with parent:
            grandchild = promising.PromisingContext(parent=parent)

        # parent exited, but still registered because grandchild exists
        assert parent in grandparent._unsettled_children

        # removing the last child triggers deferred unregistration
        parent._unregister_children_threadsafe(grandchild)
        assert grandchild not in parent._unsettled_children
        assert parent not in grandparent._unsettled_children


async def test_does_not_unregister_while_other_children_remain() -> None:
    """
    Unregistering one child does not trigger parent unregistration when
    other children still remain.
    """
    with promising.context() as grandparent:
        parent = promising.PromisingContext(parent=grandparent)
        with parent:
            child_a = promising.PromisingContext(parent=parent)
            child_b = promising.PromisingContext(parent=parent)

        # parent exited with two children still registered
        assert parent in grandparent._unsettled_children

        # removing one child — parent should stay registered
        parent._unregister_children_threadsafe(child_a)
        assert parent in grandparent._unsettled_children

        # removing the last child triggers deferred unregistration
        parent._unregister_children_threadsafe(child_b)
        assert parent not in grandparent._unsettled_children


async def test_does_not_unregister_from_parent_while_still_active() -> None:
    """
    A context that has not been exited yet does NOT unregister from its
    parent, even if it has no children.
    """
    with promising.context() as parent:
        child = promising.PromisingContext(parent=parent)
        assert child in parent._unsettled_children

        # child was never entered/exited — it's not "used"
        assert not child._context_closed
        assert child in parent._unsettled_children
