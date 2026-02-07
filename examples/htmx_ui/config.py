import os

import dotenv

# Let's load the environment variables from the .env file before importing any
# other modules
dotenv.load_dotenv()

import litellm  # noqa: E402 (module-import-not-at-top-of-file)

DEV_MODE = os.getenv("DEV_MODE", "false").lower() in ["true", "1", "yes", "y"]
HTMX_LOG_ALL = os.getenv("HTMX_LOG_ALL", "false").lower() in ["true", "1", "yes", "y"]


langfuse_secret_key = os.getenv("LANGFUSE_SECRET_KEY")
langfuse_public_key = os.getenv("LANGFUSE_PUBLIC_KEY")
langfuse_host = os.getenv("LANGFUSE_HOST")


if langfuse_secret_key or langfuse_public_key or langfuse_host:
    try:
        import langfuse  # noqa: F401 (unused-import)
    except ImportError:
        print(
            "\033[1;31mLangfuse is not installed. Please install it with either `uv sync --extra langfuse` or "
            "`uv sync --all-extras`.\033[0m"
        )
    else:
        # TODO Replace with a logger ?
        print("\033[1;34mEnabling Langfuse logging...\033[0m")
        litellm.success_callback = ["langfuse"]
        litellm.failure_callback = ["langfuse"]
