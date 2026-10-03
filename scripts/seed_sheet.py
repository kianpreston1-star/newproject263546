#!/usr/bin/env python3
"""Print (and optionally write) the header rows for the Google Sheet tabs.

The control spreadsheet needs three tabs:
  - config : imported from config.csv (key/value control panel)
  - queue  : the AI topic queue the idea-engine fills and the AI engine consumes
  - log    : post history + dedupe source

Run with no args to print the headers. Pass --write <dir> to drop queue.csv and
log.csv files you can import as tabs.
"""
import argparse
import csv
import os

TABS = {
    "queue": ["id", "topic", "niche", "status", "created_at", "used_at"],
    "log": ["id", "engine", "source_url", "title", "platforms", "post_ids", "status", "created_at"],
}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--write", metavar="DIR", help="write queue.csv and log.csv to DIR")
    args = p.parse_args()

    for tab, headers in TABS.items():
        print(f"[{tab}] {', '.join(headers)}")

    if args.write:
        os.makedirs(args.write, exist_ok=True)
        for tab, headers in TABS.items():
            path = os.path.join(args.write, f"{tab}.csv")
            with open(path, "w", newline="") as f:
                csv.writer(f).writerow(headers)
            print("wrote", path)


if __name__ == "__main__":
    main()
