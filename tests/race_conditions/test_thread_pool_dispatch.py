"""Race-condition tests for thread-pool dispatch.

Covers that ``use_thread_pool=True`` sync promising functions run on the
expected executor regardless of caller thread, and that non-overlapping
sibling ``.sync()`` calls on a shared bounded pool do not starvation-
deadlock.
"""
