"""Race-condition tests for parent-child bookkeeping (invariants §2).

Covers ``_unsettled_children`` correctness under concurrent
register/unregister: no lost or stuck children, no double
register/unregister, safe iteration, ``close_context_threadsafe`` races,
late-child rejection, unregister ordering, and untorn ``_parent`` pointers.
"""
