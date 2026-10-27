#!/usr/bin/env python3
"""Generate a qBittorrent.conf with a known WebUI password.

UseIncompleteExtension must stay false: the ".!qB" rename breaks open streams.
DefaultSavePath must match the path mounted into the VibeStream container.

Usage:
    python3 api/vibestream/tools/qbt_config.py <password> [output_path]
    QBIT_PASSWORD=... python -m vibestream.tools.qbt_config
"""

from __future__ import annotations

import base64
import hashlib
import os
import secrets
import sys

# WebUI password: PBKDF2-HMAC-SHA512, stored as "@ByteArray(<b64 salt>:<b64 key>)".
ITERATIONS = 100_000
SALT_BYTES = 16
KEY_BYTES = 64

TEMPLATE = """[AutoRun]
enabled=false

[BitTorrent]
Session\\DefaultSavePath=/data/downloads
Session\\TempPathEnabled=false
Session\\Port={torrent_port}
Session\\QueueingSystemEnabled=false
Session\\GlobalMaxSeedingMinutes=-1
Session\\MaxActiveDownloads=3
Session\\MaxActiveTorrents=8
Session\\MaxActiveUploads=6
Session\\AddTorrentStopped=false
Session\\ShareLimitAction=Stop
Session\\AnonymousMode=false

[Preferences]
Downloads\\SavePath=/data/downloads
Downloads\\UseIncompleteExtension=false
Downloads\\PreAllocation=false
Downloads\\StartInPause=false
General\\Locale=en
WebUI\\Address=*
WebUI\\Port=8081
WebUI\\Username={username}
WebUI\\Password_PBKDF2="@ByteArray({password_hash})"
WebUI\\LocalHostAuth=false
WebUI\\CSRFProtection=true
WebUI\\HostHeaderValidation=false
WebUI\\ClickjackingProtection=true
"""


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(SALT_BYTES)
    key = hashlib.pbkdf2_hmac("sha512", password.encode(), salt, ITERATIONS, KEY_BYTES)
    return f"{base64.b64encode(salt).decode()}:{base64.b64encode(key).decode()}"


def build(password: str, username: str = "admin", torrent_port: int = 38801) -> str:
    return TEMPLATE.format(
        username=username,
        password_hash=hash_password(password),
        torrent_port=torrent_port,
    )


def main(argv: list[str]) -> int:
    password = argv[1] if len(argv) > 1 else os.environ.get("QBIT_PASSWORD", "")
    if not password:
        print(__doc__, file=sys.stderr)
        return 1

    output = argv[2] if len(argv) > 2 else "-"
    content = build(password)

    if output == "-":
        sys.stdout.write(content)
    else:
        os.makedirs(os.path.dirname(output) or ".", exist_ok=True)
        with open(output, "w", encoding="utf-8") as fh:
            fh.write(content)
        print(f"wrote {output}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
