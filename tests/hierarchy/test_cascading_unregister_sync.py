"""
Tests that unregistration cascades up through 3+ levels of the hierarchy.

When a child completes and unregisters from its parent, the parent checks
whether it is itself closed and now childless — if so, it unregisters from
*its* parent in turn. This cascade continues until it reaches an ancestor
that is still open or still has other active children.

Sync variants — uses ``use_thread_pool=True`` and ``await_children_sync``.
"""

import time

import promising


async def test_cascading_unregister_through_four_levels() -> None:
    """
    Four-level hierarchy: root → parent → child → grandchild.

    All inner contexts exit before ``await_children_sync`` is called on root.
    When grandchild completes (the deepest leaf), the cascade should
    unregister grandchild from child, then child from parent, then parent
    from root — leaving ``_unsettled_children`` empty at every level.
    """

    @promising.function(use_thread_pool=True)
    def grandchild_func() -> str:
        time.sleep(0.1)
        return "grandchild"

    @promising.function(use_thread_pool=True)
    def child_func() -> str:
        grandchild_func()
        return "child"

    @promising.function(use_thread_pool=True)
    def parent_func() -> str:
        child_func()
        return "parent"

    @promising.function(use_thread_pool=True)
    def _test() -> str:
        with promising.context() as root:
            parent_promise = parent_func()
            root.await_children_sync()

        assert parent_promise._unsettled_children == set()
        assert root._unsettled_children == set()

        return "success"

    assert await _test.protected_run() == "success"


async def test_cascading_unregister_partial_when_sibling_remains() -> None:
    """
    Root → parent_a → child_a (fast)
         → parent_b → child_b (slow)

    When child_a completes, the cascade should unregister child_a from
    parent_a, then parent_a from root. But root still has parent_b, so
    root must NOT unregister from *its* parent (if any).

    After child_b completes, parent_b also cascades out of root.
    """

    @promising.function(use_thread_pool=True)
    def fast_grandchild() -> str:
        return "fast"

    @promising.function(use_thread_pool=True)
    def slow_grandchild() -> str:
        time.sleep(0.2)
        return "slow"

    @promising.function(use_thread_pool=True)
    def parent_a_func() -> str:
        fast_grandchild()
        return "parent_a"

    @promising.function(use_thread_pool=True)
    def parent_b_func() -> str:
        slow_grandchild()
        return "parent_b"

    @promising.function(use_thread_pool=True)
    def _test() -> str:
        with promising.context() as root:
            parent_a = parent_a_func()
            parent_b = parent_b_func()

            # Wait for parent_a and its entire subtree to drain
            parent_a.sync()
            parent_a.await_children_sync()

            # parent_a subtree fully drained → only parent_b remains
            assert root._unsettled_children == {parent_b}

            root.await_children_sync()

        assert root._unsettled_children == set()

        return "success"

    assert await _test.protected_run() == "success"


async def test_cascading_unregister_with_bare_contexts() -> None:
    """
    Four-level hierarchy using only bare PromisingContexts (no Promises).

    Exiting each ``with`` block from the inside out triggers the cascade
    once the innermost context closes.
    """

    @promising.function(use_thread_pool=True)
    def _test() -> str:
        with promising.context() as root:
            level1 = promising.PromisingContext(parent=root)
            with level1:
                level2 = promising.PromisingContext(parent=level1)
                with level2:
                    level3 = promising.PromisingContext(parent=level2)
                    with level3:
                        # All four levels active
                        assert level3._unsettled_children == set()
                        assert level2._unsettled_children == {level3}
                        assert level1._unsettled_children == {level2}
                        assert root._unsettled_children == {level1}

                    # level3 exited, childless → unregisters from level2
                    assert level3._unsettled_children == set()
                    assert level2._unsettled_children == set()
                    assert level1._unsettled_children == {level2}
                    assert root._unsettled_children == {level1}

                # level2 exited, now childless → cascades up to level1
                assert level3._unsettled_children == set()
                assert level2._unsettled_children == set()
                assert level1._unsettled_children == set()
                assert root._unsettled_children == {level1}

            # level1 exited, now childless → cascades up to root
            assert level3._unsettled_children == set()
            assert level2._unsettled_children == set()
            assert level1._unsettled_children == set()
            assert root._unsettled_children == set()

        assert level3._unsettled_children == set()
        assert level2._unsettled_children == set()
        assert level1._unsettled_children == set()
        assert root._unsettled_children == set()

        return "success"

    assert await _test.protected_run() == "success"


async def test_cascading_unregister_with_bare_contexts_and_promise() -> None:
    """
    Four-level hierarchy of bare PromisingContexts with a Promise leaf.

    All bare context ``with`` blocks exit while the leaf Promise is still
    unresolved. The bare contexts must stay registered in their parents
    because the Promise descendant is still active. Once the Promise is
    synced and completes, the entire chain cascades upward in one shot.
    """

    @promising.function(use_thread_pool=True)
    def level4_func() -> str:
        return "level4"

    @promising.function(use_thread_pool=True)
    def _test() -> str:
        with promising.context() as root:
            level1 = promising.PromisingContext(parent=root)
            with level1:
                level2 = promising.PromisingContext(parent=level1)
                with level2:
                    level3 = promising.PromisingContext(parent=level2)
                    with level3:
                        level4_promise = level4_func()

                        # All four levels active
                        assert level4_promise._unsettled_children == set()
                        assert level3._unsettled_children == {level4_promise}
                        assert level2._unsettled_children == {level3}
                        assert level1._unsettled_children == {level2}
                        assert root._unsettled_children == {level1}

                    # All four levels still active (because of the unfinished promise)
                    assert level4_promise._unsettled_children == set()
                    assert level3._unsettled_children == {level4_promise}
                    assert level2._unsettled_children == {level3}
                    assert level1._unsettled_children == {level2}
                    assert root._unsettled_children == {level1}

                # All four levels still active (because of the unfinished promise)
                assert level4_promise._unsettled_children == set()
                assert level3._unsettled_children == {level4_promise}
                assert level2._unsettled_children == {level3}
                assert level1._unsettled_children == {level2}
                assert root._unsettled_children == {level1}

            # All four levels active (because of the unfinished promise)
            assert level4_promise._unsettled_children == set()
            assert level3._unsettled_children == {level4_promise}
            assert level2._unsettled_children == {level3}
            assert level1._unsettled_children == {level2}
            assert root._unsettled_children == {level1}

        # All four levels active (because of the unfinished promise)
        assert level4_promise._unsettled_children == set()
        assert level3._unsettled_children == {level4_promise}
        assert level2._unsettled_children == {level3}
        assert level1._unsettled_children == {level2}
        assert root._unsettled_children == {level1}

        level4_promise.sync()

        # None of the levels active anymore
        assert level4_promise._unsettled_children == set()
        assert level3._unsettled_children == set()
        assert level2._unsettled_children == set()
        assert level1._unsettled_children == set()
        assert root._unsettled_children == set()

        return "success"

    assert await _test.protected_run() == "success"
