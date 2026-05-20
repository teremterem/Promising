"""Race-condition tests for the Promise state machine (invariants §1).

Covers monotonic state transitions, single terminal state, writer/reader
ordering behind ``done()``, predicate consistency, one-shot result caching,
shared cached values across consumers, and single-assignment of the
internal unpacking tasks.
"""
