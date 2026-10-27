#!/usr/bin/env python3
"""Recover the filelist passkey from the announce URLs of existing .torrent files.

Usage: scripts/find-passkey.py [directory or .torrent ...]   (default: /data/torrents)
"""

from __future__ import annotations

import glob
import os
import re
import sys
from collections import Counter

PASSKEY_RE = re.compile(r"/([0-9a-f]{32})/announce", re.I)


def bdecode(data: bytes, i: int = 0):
    """Minimal bencode reader. Enough for the announce fields."""
    marker = data[i : i + 1]
    if marker == b"d":
        i += 1
        out = {}
        while data[i : i + 1] != b"e":
            key, i = bdecode(data, i)
            val, i = bdecode(data, i)
            out[key] = val
        return out, i + 1
    if marker == b"l":
        i += 1
        out = []
        while data[i : i + 1] != b"e":
            val, i = bdecode(data, i)
            out.append(val)
        return out, i + 1
    if marker == b"i":
        end = data.index(b"e", i)
        return int(data[i + 1 : end]), end + 1
    colon = data.index(b":", i)
    length = int(data[i:colon])
    return data[colon + 1 : colon + 1 + length], colon + 1 + length


def announce_urls(path: str) -> list[str]:
    with open(path, "rb") as fh:
        meta, _ = bdecode(fh.read())
    urls = []
    primary = meta.get(b"announce")
    if primary:
        urls.append(primary.decode("utf-8", "replace"))
    for tier in meta.get(b"announce-list", []) or []:
        for url in tier:
            urls.append(url.decode("utf-8", "replace"))
    return urls


def collect(paths: list[str]) -> list[str]:
    files: list[str] = []
    for target in paths:
        if os.path.isdir(target):
            files.extend(sorted(glob.glob(os.path.join(target, "**", "*.torrent"),
                                          recursive=True)))
        elif target.endswith(".torrent"):
            files.append(target)
    return files


def main(argv: list[str]) -> int:
    targets = argv[1:] or ["/data/torrents"]
    files = collect(targets)
    if not files:
        print(f"no .torrent files found under: {', '.join(targets)}", file=sys.stderr)
        return 1

    found: Counter[str] = Counter()
    for path in files:
        try:
            for url in announce_urls(path):
                match = PASSKEY_RE.search(url)
                if match:
                    found[match.group(1).lower()] += 1
        except Exception as exc:  # a truncated torrent must not stop the scan
            print(f"  skipped {os.path.basename(path)}: {exc}", file=sys.stderr)

    if not found:
        print(f"scanned {len(files)} file(s), no filelist announce URL found",
              file=sys.stderr)
        return 1

    print(f"scanned {len(files)} torrent file(s)\n")
    for passkey, count in found.most_common():
        masked = f"{passkey[:6]}{'.' * 20}{passkey[-6:]}"
        print(f"  passkey {masked}  (seen in {count} torrent(s))")
        print(f"  full value: {passkey}")
    if len(found) > 1:
        print("\nMore than one passkey seen. The most frequent one is almost")
        print("certainly the current account. Older ones are from before a reset.")
    print("\nPut it in .env as:")
    print(f"  FILELIST_PASSKEY={found.most_common(1)[0][0]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
