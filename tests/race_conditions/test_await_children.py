"""Race-condition tests for ``await_children`` under churn.

Covers eventual quiescence with grand-children spawned mid-wait,
non-awaitable context siblings being filtered out, child exceptions not
interrupting the wait, ``await_children_sync`` correctness, and
``unpack_promises_fully=False`` early-return semantics.
"""
