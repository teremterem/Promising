import promising


def agent3_plain_func2() -> None:
    raise ValueError("Agent 3 plain function 2 error")


async def agent3_plain_coro1() -> None:
    return agent3_plain_func2()


@promising.function
async def agent3() -> None:
    return await agent3_plain_coro1()


@promising.function
async def agent2() -> None:
    return agent3()


def agent1_plain_func2() -> None:
    return agent2()


async def agent1_plain_coro1() -> None:
    return agent1_plain_func2()


@promising.function
async def agent1() -> None:
    # try:
    return await agent1_plain_coro1()
    # except Exception as e:
    #     # Let's see how the traceback changes upon re-raising
    #     raise e


@promising.function
async def main() -> None:
    return agent1()


# # raise RuntimeError("Test error")
# try:
main.run()
# except Exception as e:
#     # Let's see how the traceback changes upon re-raising
#     raise e
