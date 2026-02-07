from typing import Any

from fasthtml.common import fast_app, serve

from examples.htmx_ui.htmx_common import HDRS, INDEX_ROUTE, htmx_entire_html

app, rt = fast_app(hdrs=HDRS, title="Hello world")


@app.route(INDEX_ROUTE)
async def index() -> Any:
    return htmx_entire_html("Hello world", html_head_title="Hello world")


if __name__ == "__main__":
    serve()
