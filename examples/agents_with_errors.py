import promising


def agent3_plain_func2() -> None:
    with promising.context(start_soon_default="This should fail"):
        print("It did not fail =/")


async def agent3_plain_coro1() -> None:
    return agent3_plain_func2()


@promising.function
async def agent3() -> None:
    try:
        return await agent3_plain_coro1()
    except Exception as e:
        # Let's see how the traceback changes upon re-raising
        raise e


@promising.function
async def agent2() -> None:
    return agent3()


def agent1_plain_func2() -> None:
    return agent2()


async def agent1_plain_coro1() -> None:
    return agent1_plain_func2()


@promising.function
async def agent1() -> None:
    return await agent1_plain_coro1()


@promising.function
async def main() -> None:
    return agent1()


try:
    main.run(collapse_tracebacks=False)
except Exception as e:
    # Let's see how the traceback changes upon re-raising
    raise e
