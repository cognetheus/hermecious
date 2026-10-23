"""API entrypoint: `python -m app`. Validates settings before serving."""

import sys

import uvicorn

from app.core.settings import SettingsError, load_settings
from app.main import create_app


def main() -> int:
    try:
        settings = load_settings()
    except SettingsError as exc:
        print(f"hermecious-api: refusing to start: {exc}", file=sys.stderr)
        return 1
    # All interfaces inside the container; compose publishes the port on host loopback only.
    uvicorn.run(create_app(settings), host="0.0.0.0", port=8000)  # noqa: S104
    return 0


if __name__ == "__main__":
    sys.exit(main())
