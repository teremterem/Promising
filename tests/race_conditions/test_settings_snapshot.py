"""Race-condition tests for per-Promise settings snapshot.

Covers immutability of resolved settings after ``__init__`` (even when
``promising.Defaults.*`` is mutated concurrently) and absence of
cross-promise leak when a parent's setting is changed between sibling
constructions.
"""
