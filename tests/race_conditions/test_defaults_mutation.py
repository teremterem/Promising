"""Race-condition tests for ``Defaults`` mutation under load (invariants §11).

Covers that flipping ``Defaults.START_SOON`` concurrently with Promise
construction never produces a Promise whose scheduling state disagrees
with its captured ``_start_soon`` flag.
"""
