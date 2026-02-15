from typing import Any

from fasthtml.common import fast_app, serve

from examples.htmx_ui.htmx_common import HDRS, INDEX_ROUTE, htmx_entire_html

# TODO Why are we passing `hdrs` and `title` here if we are later also
#  including them in the `htmx_entire_html` function ?
#  https://github.com/teremterem/Promising/pull/46#discussion_r2807929754
app, rt = fast_app(hdrs=HDRS, title="Hello world")


@app.route(INDEX_ROUTE)
async def index() -> Any:
    return htmx_entire_html("Hello world", html_head_title="Hello world")


if __name__ == "__main__":
    serve()
