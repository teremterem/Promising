import promising
from promising import Promise


@promising.function
async def unreachable_agent() -> None:
    print("Unreachable agent has been reached (and it shouldn't have been)")


def agent3_plain_func2() -> None:
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


try:
    main.run(collapse_tracebacks=True)
except Exception as e:
    # Let's see how the traceback changes upon re-raising
    raise e
