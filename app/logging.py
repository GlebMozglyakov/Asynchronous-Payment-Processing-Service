"""Logging helpers used by API and consumer runtimes."""

import logging


def configure_logging(level: int = logging.INFO) -> None:
    """Configure root logger in a deterministic way."""

    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
