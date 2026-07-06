"""Race-condition tests for sentinel safety.

Covers that no internal code path triggers ``SentinelUsageError`` (i.e.
the framework never truthiness-tests a sentinel) under any of the race
scenarios exercised by the rest of this suite.
"""
