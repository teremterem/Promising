import sys
import traceback

import promising


# TODO Move this hook somewhere in the promising framework itself
def my_excepthook(exc_type, exc_value, exc_tb):
    # TODO Fallback to default printing behavior if the exception does not have
    #  __promising_context__  attribute at all
    # TODO Is it possible to fetch the width of the terminal and use it for the
    #  horizontal line length ?
    print("━" * 60)
    print(f"💥  {exc_type.__name__}: {exc_value}")
    print("━" * 60)
    traceback.print_tb(exc_tb)
    print("━" * 60)

    pc = getattr(exc_value, "__promising_context__", None)
    if pc is None:
        return

    print("📍  Promise creation stacks (outermost → innermost):")
    print("━" * 60)
    for ctx in pc.get_trace(parents_first=True):
        if not isinstance(ctx, promising.Promise):
            continue
        stack_summary = getattr(ctx, "_creation_stack_summary", None)
        if stack_summary is None:
            continue
        print(f"{ctx!r}")
        for line in stack_summary.format():
            print(line, end="")
        print("━" * 60)
    # TODO At the very end the final traceback should be printed in the same
    #  filtered fashion - the actual traceback of the exception that was raised
    # TODO Make sure something like this is printed everytime framework frames
    #  are omitted ?
    #  `... (`promising` internals omitted) ...`


# TODO What about formatting it for the loggers, and not just stderr/stdout ?
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
    try:
        return await agent1_plain_coro1()
    except Exception as e:
        # Let's see how the traceback changes upon re-raising
        raise e


@promising.function
async def main() -> None:
    return agent1()


try:
    main.run()
except Exception as e:
    # Let's see how the traceback changes upon re-raising
    raise e
