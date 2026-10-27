"""Bencode reader. The infohash is the SHA-1 of the raw info bytes, so
offsets are tracked rather than re-encoding."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any


class BencodeError(ValueError):
    pass


def _decode(data: bytes, i: int) -> tuple[Any, int]:
    if i >= len(data):
        raise BencodeError("unexpected end of data")
    marker = data[i : i + 1]

    if marker == b"d":
        i += 1
        out: dict[bytes, Any] = {}
        while True:
            if i >= len(data):
                raise BencodeError("unterminated dictionary")
            if data[i : i + 1] == b"e":
                return out, i + 1
            key, i = _decode(data, i)
            if not isinstance(key, bytes):
                raise BencodeError("dictionary key is not a byte string")
            out[key], i = _decode(data, i)

    if marker == b"l":
        i += 1
        items: list[Any] = []
        while True:
            if i >= len(data):
                raise BencodeError("unterminated list")
            if data[i : i + 1] == b"e":
                return items, i + 1
            value, i = _decode(data, i)
            items.append(value)

    if marker == b"i":
        end = data.find(b"e", i)
        if end < 0:
            raise BencodeError("unterminated integer")
        return int(data[i + 1 : end]), end + 1

    colon = data.find(b":", i)
    if colon < 0:
        raise BencodeError("malformed byte string")
    length = int(data[i:colon])
    start = colon + 1
    if start + length > len(data):
        raise BencodeError("byte string runs past end of data")
    return data[start : start + length], start + length


def bdecode(data: bytes) -> dict:
    value, _ = _decode(data, 0)
    if not isinstance(value, dict):
        raise BencodeError("torrent root is not a dictionary")
    return value


def _info_slice(data: bytes) -> tuple[int, int]:
    root, _ = _decode(data, 0)
    if not isinstance(root, dict) or b"info" not in root:
        raise BencodeError("torrent has no info dictionary")

    i = 1
    while i < len(data) and data[i : i + 1] != b"e":
        key, i = _decode(data, i)
        start = i
        _, i = _decode(data, i)
        if key == b"info":
            return start, i
    raise BencodeError("could not locate the info dictionary")


@dataclass
class TorrentFile:
    path: str
    length: int
    offset: int  # byte offset of this file within the concatenated torrent data


@dataclass
class TorrentMeta:
    infohash: str
    name: str
    piece_length: int
    total_length: int
    files: list[TorrentFile] = field(default_factory=list)
    announce: str | None = None
    is_single_file: bool = False

    @property
    def piece_count(self) -> int:
        if self.piece_length <= 0:
            return 0
        return (self.total_length + self.piece_length - 1) // self.piece_length

    def largest_video_file(self) -> TorrentFile | None:
        video_ext = (
            ".mkv", ".mp4", ".avi", ".m4v", ".mov", ".ts", ".m2ts", ".wmv", ".mpg",
        )
        candidates = [
            f for f in self.files if f.path.lower().endswith(video_ext)
        ]
        pool = candidates or self.files
        return max(pool, key=lambda f: f.length) if pool else None

    def piece_range_for(self, file: TorrentFile, start: int, end: int) -> tuple[int, int]:
        """Inclusive piece indices for file bytes [start, end]; offsets are relative to the file."""
        if self.piece_length <= 0:
            return 0, 0
        abs_start = file.offset + max(0, start)
        abs_end = file.offset + min(end, max(0, file.length - 1))
        return abs_start // self.piece_length, abs_end // self.piece_length


def parse_torrent(data: bytes) -> TorrentMeta:
    root = bdecode(data)
    info = root.get(b"info")
    if not isinstance(info, dict):
        raise BencodeError("torrent has no info dictionary")

    start, end = _info_slice(data)
    infohash = hashlib.sha1(data[start:end]).hexdigest()

    name = (info.get(b"name") or b"").decode("utf-8", "replace")
    piece_length = int(info.get(b"piece length") or 0)

    files: list[TorrentFile] = []
    offset = 0
    if b"files" in info:
        for entry in info[b"files"]:
            parts = [p.decode("utf-8", "replace") for p in entry.get(b"path", [])]
            length = int(entry.get(b"length") or 0)
            files.append(TorrentFile(path="/".join(parts), length=length, offset=offset))
            offset += length
        single = False
    else:
        length = int(info.get(b"length") or 0)
        files.append(TorrentFile(path=name, length=length, offset=0))
        offset = length
        single = True

    announce_raw = root.get(b"announce")
    return TorrentMeta(
        infohash=infohash,
        name=name,
        piece_length=piece_length,
        total_length=offset,
        files=files,
        announce=announce_raw.decode("utf-8", "replace") if announce_raw else None,
        is_single_file=single,
    )
