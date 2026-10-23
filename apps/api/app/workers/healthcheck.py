"""Worker container health check: `python -m app.workers.healthcheck`."""

import sys

from app.workers.worker import healthcheck

if __name__ == "__main__":
    sys.exit(healthcheck())
