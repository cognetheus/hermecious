"""API entrypoint: `python -m app`. Validates settings before serving."""

import logging
import sys

import uvicorn

from app.core.logging import configure_logging
from app.core.settings import SettingsError, load_settings
from app.main import create_app

logger = logging.getLogger("app")


def main() -> int:
    try:
        settings = load_settings()
    except SettingsError as exc:
        configure_logging("api", "unknown")
        logger.critical("config.invalid", extra={"context": {"settings": exc.names}})
        return 1
    configure_logging("api", settings.environment, settings.log_level)
    logger.info("app.starting")
    # All interfaces inside the container; compose publishes the port on host loopback only.
    uvicorn.run(create_app(settings), host="0.0.0.0", port=8000, log_config=None, access_log=False)  # noqa: S104
    return 0


if __name__ == "__main__":
    sys.exit(main())
