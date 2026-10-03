#!/usr/bin/env python3
"""Build a Creative-Commons attribution line for a clipped source video.

CC BY requires crediting the original author. This produces the line that the
clipping engine appends to each post's description (see docs/COMPLIANCE.md).

Usage:
    python3 cc_attribution.py --title "..." --author "..." --url "..." [--license "CC BY"]
    echo '{"title":"...","author":"...","url":"..."}' | python3 cc_attribution.py
"""
import argparse
import json
import sys


def build_attribution(title: str, author: str, url: str, license: str = "CC BY") -> str:
    """Return a single-line attribution string. Falls back gracefully on missing fields."""
    title = (title or "").strip()
    author = (author or "").strip()
    url = (url or "").strip()
    parts = ["Clip from"]
    parts.append(f'"{title}"' if title else "original video")
    if author:
        parts.append(f"by {author}")
    if url:
        parts.append(f"({url})")
    line = " ".join(parts)
    return f"{line} — licensed {license}."


def main(argv=None):
    p = argparse.ArgumentParser(description="Build a CC attribution line.")
    p.add_argument("--title", default="")
    p.add_argument("--author", default="")
    p.add_argument("--url", default="")
    p.add_argument("--license", default="CC BY")
    args = p.parse_args(argv)

    # If no CLI args given, try reading JSON from stdin.
    if not (args.title or args.author or args.url) and not sys.stdin.isatty():
        try:
            data = json.load(sys.stdin)
            args.title = data.get("title", "")
            args.author = data.get("author", "")
            args.url = data.get("url", "")
            args.license = data.get("license", args.license)
        except Exception:
            pass

    print(build_attribution(args.title, args.author, args.url, args.license))


if __name__ == "__main__":
    main()
