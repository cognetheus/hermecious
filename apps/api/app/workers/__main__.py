"""Worker entrypoint: `python -m app.workers`."""

import sys

from app.workers.worker import run

if __name__ == "__main__":
    sys.exit(run())
