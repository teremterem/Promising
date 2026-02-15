import logging
import os

import dotenv

logger = logging.getLogger(__name__)

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
    import langfuse  # noqa: F401 (unused-import)

    logger.info("Enabling Langfuse logging")
    litellm.success_callback = ["langfuse"]
    litellm.failure_callback = ["langfuse"]
