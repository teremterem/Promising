"""Race-condition tests for ``Promise.cancel()`` (invariants §3).

Covers thread-safety and bounded completion of concurrent ``cancel()``
calls, terminal-state guarantee, result-vs-cancel races, idempotency,
waiter wake-up, documented (non-)propagation to nested promises, and
coroutine cleanup on synthesize-cancel.
"""
