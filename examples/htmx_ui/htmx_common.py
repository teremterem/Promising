from typing import Any

from fasthtml.common import Body, Head, Html, Link, Meta, Script, Title

from examples.htmx_ui.config import DEV_MODE, HTMX_LOG_ALL

# DaisyUI themes for light and dark mode (auto-switches based on browser preference)
# TODO Make theme configurable through the UI
DAISYUI_THEME_LIGHT = "light"
DAISYUI_THEME_DARK = "black"

# Routes
INDEX_ROUTE = "/"

# List of elements that should be disabled during HTMX requests. The
# `hx-disabled-elt` attribute should be set on the element doing the HTMX
# request explicitly.
DEFAULT_HX_DISABLED_ELT = "button, input, textarea, select, a"

HDRS = (
    Meta(name="viewport", content="width=device-width, initial-scale=1.0"),
    # Theme switcher script - runs early to avoid flash of wrong theme
    Script(f"""
(function() {{
    var light = '{DAISYUI_THEME_LIGHT}';
    var dark = '{DAISYUI_THEME_DARK}';
    function setTheme(e) {{
        document.documentElement.setAttribute('data-theme', e.matches ? dark : light);
    }}
    var mq = window.matchMedia('(prefers-color-scheme: dark)');
    setTheme(mq);
    mq.addEventListener('change', setTheme);
}})();
"""),
    Script(
        src=(
            "https://unpkg.com/htmx.org@2.0.8/dist/htmx.js"
            if DEV_MODE
            else "https://unpkg.com/htmx.org@2.0.8/dist/htmx.min.js"
        ),
    ),
    *([Script("htmx.logAll();")] if HTMX_LOG_ALL else []),
    Link(href="https://cdn.jsdelivr.net/npm/daisyui@5", rel="stylesheet", type="text/css"),
    Link(href="https://cdn.jsdelivr.net/npm/daisyui@5/themes.css", rel="stylesheet", type="text/css"),
    Script(src="https://cdn.jsdelivr.net/npm/@tailwindcss/browser@4"),
)


def htmx_entire_html(
    *body_inner_html: Any,
    html_head_title: str,
    hx_boost: bool = True,
    reenable_controls_upon_back: bool = False,
) -> Any:
    return Html(
        Head(Title(html_head_title, id="head-title"), *HDRS),
        Body(
            *body_inner_html,
            # Remove disabled state when navigating back via bfcache
            Script("""
window.addEventListener('pageshow', function(event) {
    if (event.persisted) {
        document.querySelectorAll('[data-disabled-by-htmx]').forEach(function(el) {
            el.removeAttribute('data-disabled-by-htmx');
        });
    }
});
""")
            if reenable_controls_upon_back
            else None,
        ),
        **({"hx_boost": "true"} if hx_boost else {}),
    )
