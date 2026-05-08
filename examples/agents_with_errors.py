import sys
import traceback

import promising


def my_excepthook(exc_type, exc_value, exc_tb):
    print("━" * 60)
    print(f"💥  {exc_type.__name__}: {exc_value}")
    print("━" * 60)
    traceback.print_tb(exc_tb)
    print("━" * 60)


sys.excepthook = my_excepthook


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
    return await agent1_plain_coro1()


@promising.function
async def main() -> None:
    return agent1()


main.run()
