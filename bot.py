from __future__ import annotations

import asyncio
import logging

from memeradar.config import Config
from memeradar.engine import MemeRadar


def main() -> None:
    cfg = Config.from_env()
    logging.basicConfig(
        level=getattr(logging, cfg.log_level, logging.INFO),
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
    try:
        asyncio.run(MemeRadar(cfg).run())
    except KeyboardInterrupt:
        logging.getLogger(__name__).info("Stopped by user")


if __name__ == "__main__":
    main()
