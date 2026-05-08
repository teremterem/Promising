import promising


def agent3_non_promise2() -> None:
    raise ValueError("Agent 3 sub-function 2 error")


async def agent3_non_promise1() -> None:
    return agent3_non_promise2()


@promising.function
async def agent3() -> None:
    return await agent3_non_promise1()


@promising.function
async def agent2() -> None:
    return agent3()


@promising.function
async def agent1() -> None:
    return agent2()


@promising.function
async def main() -> None:
    return agent1()


main.run()
