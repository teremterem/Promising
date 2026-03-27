import promising


async def test_calling_promising_function_returns_promise() -> None:
    """
    Calling a decorated function returns a Promise;
    awaiting it returns the expected value.
    """

    @promising.function
    async def greet() -> str:
        return "hello"

    assert isinstance(greet, promising.PromisingFunction)
    result = greet()
    assert isinstance(result, promising.Promise)
    assert await result == "hello"
