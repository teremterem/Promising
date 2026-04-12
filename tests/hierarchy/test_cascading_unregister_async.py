"""
Tests that unregistration cascades up through 3+ levels of the hierarchy.

When a child completes and unregisters from its parent, the parent checks
whether it is itself closed and now childless — if so, it unregisters from
*its* parent in turn. This cascade continues until it reaches an ancestor
that is still open or still has other active children.

Async variants — uses ``await`` and ``await_children``.
"""

import asyncio

import promising


async def test_cascading_unregister_through_four_levels() -> None:
    """
    Four-level hierarchy: root → parent → child → grandchild.

    All inner contexts exit before ``await_children`` is called on root.
    When grandchild completes (the deepest leaf), the cascade should
    unregister grandchild from child, then child from parent, then parent
    from root — leaving ``_active_children`` empty at every level.
    """

    @promising.function
    async def grandchild_func() -> str:
        await asyncio.sleep(0.1)
        return "grandchild"

    @promising.function
    async def child_func() -> str:
        grandchild_func()
        return "child"

    @promising.function
    async def parent_func() -> str:
        child_func()
        return "parent"

    with promising.context() as root:
        parent_promise = parent_func()
        await root.await_children(recursively=True)

    assert parent_promise._active_children == set()
    assert root._active_children == set()


async def test_cascading_unregister_partial_when_sibling_remains() -> None:
    """
    Root → parent_a → child_a (fast)
         → parent_b → child_b (slow)

    When child_a completes, the cascade should unregister child_a from
    parent_a, then parent_a from root. But root still has parent_b, so
    root must NOT unregister from *its* parent (if any).

    After child_b completes, parent_b also cascades out of root.
    """

    @promising.function
    async def fast_grandchild() -> str:
        return "fast"

    @promising.function
    async def slow_grandchild() -> str:
        await asyncio.sleep(0.2)
        return "slow"

    @promising.function
    async def parent_a_func() -> str:
        fast_grandchild()
        return "parent_a"

    @promising.function
    async def parent_b_func() -> str:
        slow_grandchild()
        return "parent_b"

    with promising.context() as root:
        parent_a = parent_a_func()
        parent_b = parent_b_func()

        # Wait for parent_a and its entire subtree to drain
        await parent_a
        await parent_a.await_children(recursively=True)

        # parent_a subtree fully drained → unregistered from root
        assert parent_a not in root._active_children
        # parent_b subtree still active → still registered
        assert parent_b in root._active_children

        await root.await_children(recursively=True)

    assert root._active_children == set()


async def test_cascading_unregister_with_bare_contexts() -> None:
    """
    Four-level hierarchy using only bare PromisingContexts (no Promises).

    Exiting each ``with`` block from the inside out triggers the cascade
    once the innermost context closes.
    """
    with promising.context() as root:
        level1 = promising.PromisingContext(parent=root)
        with level1:
            level2 = promising.PromisingContext(parent=level1)
            with level2:
                level3 = promising.PromisingContext(parent=level2)
                with level3:
                    # All four levels active
                    assert level3 in level2._active_children
                    assert level2 in level1._active_children
                    assert level1 in root._active_children

                # level3 exited, childless → unregisters from level2
                assert level3 not in level2._active_children

            # level2 exited, now childless → cascades up to level1
            assert level2 not in level1._active_children

        # level1 exited, now childless → cascades up to root
        assert level1 not in root._active_children

    assert root._active_children == set()
