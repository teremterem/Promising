import promising


async def test_calling_sync_promising_function_returns_promise() -> None:
    """
    Calling a decorated sync function returns a Promise;
    awaiting it returns the expected value.
    """

    @promising.function(use_thread_pool=True)
    def greet() -> str:
        return "hello"

    assert isinstance(greet, promising.PromisingFunction)
    result = greet()
    assert isinstance(result, promising.Promise)
    assert await result == "hello"
