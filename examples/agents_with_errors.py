"""
Smoke-test for the promising-traceback rendering.

This example wires together a multi-agent call graph that ultimately fails
(``unreachable_agent`` is called with a non-bool ``start_soon`` argument),
then re-raises the failure twice — once plain, once chained via
``__context__``, and once chained via ``__cause__`` — so all three
exception-chain mechanisms are exercised in a single run.

What to look at when running ``python examples/agents_with_errors.py``:

- The output contains three "Traceback" sections separated by the chain
  banners ``During handling of the above exception...`` and ``The above
  exception was the direct cause...``.
- Each section is enriched with the promising-context trace of the
  Promise / context hierarchy that was active when the failure occurred.
- Because ``main.run(collapse_tracebacks=True)`` is used, promising-
  internal frames are collapsed and replaced with ``... (collapsed
  frames)``. Flip it to ``False`` to see the full, uncollapsed
  tracebacks.
"""

import promising
from promising import Promise


@promising.function
async def unreachable_agent() -> None:
    print("Unreachable agent has been reached (and it shouldn't have been)")


def agent3_plain_func2() -> Promise[None]:
    return unreachable_agent(start_soon="This call should fail")


@promising.context
async def agent3_plain_coro1() -> Promise[None]:
    with promising.context():
        return agent3_plain_func2()


@promising.function
async def agent3() -> Promise[None]:
    try:
        return await agent3_plain_coro1()
    except Exception as e:
        # The error will NOT go through here - it will be raised later, when
        # the promise is unpacked
        raise e


@promising.function
async def agent2() -> Promise[None]:
    return agent3()


@promising.context
def agent1_plain_func2() -> Promise[None]:
    return agent2()


async def agent1_plain_coro1() -> Promise[None]:
    return agent1_plain_func2()


@promising.function
async def agent1() -> Promise[None]:
    return await agent1_plain_coro1()


@promising.function
async def agent0(promise: Promise[None]) -> None:
    return await promise


@promising.function
async def main() -> Promise[None]:
    promise: Promise[None] = agent1()
    return agent0(promise)


if __name__ == "__main__":
    try:
        main.run(collapse_tracebacks=True)
    except Exception as e:
        try:
            try:
                # Let's see how the traceback changes upon re-raising
                raise e
            except Exception:
                # Test Exception.__context__
                raise RuntimeError("Unrelated error")  # noqa: B904 (raise-without-from-inside-except)
        except Exception as e:
            # Test Exception.__cause__
            raise ValueError("This is a test error") from e
