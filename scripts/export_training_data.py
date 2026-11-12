from __future__ import annotations

import argparse
import json
from pathlib import Path

from memeradar.storage import Store


def main() -> None:
    parser = argparse.ArgumentParser(description="Export completed 15m paper outcomes to CSV")
    parser.add_argument("--database", default="data/meme_radar.sqlite3")
    parser.add_argument("--output", default="data/model_training.csv")
    args = parser.parse_args()
    store = Store(Path(args.database))
    try:
        count = store.export_model_dataset(Path(args.output))
    finally:
        store.close()
    print(json.dumps({"rows_exported": count, "output": args.output}, indent=2))


if __name__ == "__main__":
    main()