"""Race-condition tests for event-loop discipline (invariants §4).

Covers that ``_*_from_loop`` methods stay on the owning loop,
``SyncUsageError`` is raised (not deadlock) for sync calls from the loop
thread, ``start_soon=True`` cross-thread scheduling, no leaked task refs
on prefilled/never-awaited Promises, and race-free loop-mismatch
detection.
"""
