"""Race-condition tests for sentinel safety (invariants §12).

Covers that no internal code path triggers ``SentinelUsageError`` (i.e.
the framework never truthiness-tests a sentinel) under any of the race
scenarios exercised by the rest of this suite.
"""
