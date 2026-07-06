"""Race-condition tests for ``wrap_awaitable`` and construction.

Covers concurrency-safe wrapping of bare coroutines from many threads,
and that ``__init__`` validation runs before parent registration so
failed constructions never appear in the parent's ``_unsettled_children``.
"""
