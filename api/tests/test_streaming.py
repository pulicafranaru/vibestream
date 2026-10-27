"""RFC 9110: an unparseable Range is ignored (full body); 416 is only for a valid range outside the file."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vibestream.services import streaming  # noqa: E402
from vibestream.services.streaming import parse_range_header  # noqa: E402

SIZE = 1_000_000


def test_no_header_serves_whole_body():
    assert parse_range_header(None, SIZE) == ("ignore", None)
    assert parse_range_header("", SIZE) == ("ignore", None)


def test_malformed_headers_are_ignored_not_rejected():
    for header in ("bytes=", "bytes=abc-def", "bytes=xyz", "items=0-10", "0-10"):
        verdict, span = parse_range_header(header, SIZE)
        assert verdict == "ignore", f"{header!r} should be ignored, got {verdict}"
        assert span is None


def test_simple_range():
    assert parse_range_header("bytes=0-1023", SIZE) == ("ok", (0, 1023))


def test_open_ended_range_runs_to_end_of_file():
    assert parse_range_header("bytes=500-", SIZE) == ("ok", (500, SIZE - 1))


def test_end_beyond_file_is_clamped():
    assert parse_range_header("bytes=0-99999999", SIZE) == ("ok", (0, SIZE - 1))


def test_suffix_range_returns_last_n_bytes():
    assert parse_range_header("bytes=-1000", SIZE) == ("ok", (SIZE - 1000, SIZE - 1))


def test_suffix_larger_than_file_returns_whole_file():
    assert parse_range_header("bytes=-99999999", SIZE) == ("ok", (0, SIZE - 1))


def test_zero_length_suffix_is_unsatisfiable():
    assert parse_range_header("bytes=-0", SIZE) == ("unsatisfiable", None)


def test_start_past_end_of_file_is_unsatisfiable():
    assert parse_range_header("bytes=1000000-", SIZE) == ("unsatisfiable", None)
    assert parse_range_header("bytes=99999999-", SIZE) == ("unsatisfiable", None)


def test_inverted_range_is_unsatisfiable():
    assert parse_range_header("bytes=900-100", SIZE) == ("unsatisfiable", None)


def test_only_the_first_range_of_a_multi_range_is_used():
    # Multipart ranges are not supported; serving the first is allowed.
    assert parse_range_header("bytes=0-99,200-299", SIZE) == ("ok", (0, 99))


def test_case_insensitive_unit():
    assert parse_range_header("BYTES=0-99", SIZE) == ("ok", (0, 99))


def test_last_byte_is_reachable():
    assert parse_range_header(f"bytes={SIZE - 1}-", SIZE) == ("ok", (SIZE - 1, SIZE - 1))


def _collect(ctx, start, end):
    import asyncio

    async def run():
        return b"".join([chunk async for chunk in streaming.iter_range(ctx, start, end)])

    return asyncio.run(run())


def test_a_hole_in_a_preallocated_file_is_waited_for(monkeypatch, tmp_path):
    """qBittorrent preallocates, so unfetched pieces read as zeros and must not be served."""
    from types import SimpleNamespace

    real = bytes(range(256)) * 16          # 4 KiB, four 1 KiB pieces
    path = tmp_path / "film.mkv"
    path.write_bytes(b"\x00" * len(real))
    asked: list[tuple[int, int]] = []

    meta = SimpleNamespace(piece_range_for=lambda _f, s, e: (s // 1024, e // 1024))

    async def ensure_meta(*_a):
        return meta

    async def wait_for_bytes(_hash, _meta, _target, offset, length):
        asked.append((offset, length))
        begin, finish = offset // 1024 * 1024, ((offset + length - 1) // 1024 + 1) * 1024
        with open(path, "r+b") as fh:
            fh.seek(begin)
            fh.write(real[begin:finish])
        return True

    monkeypatch.setattr(streaming, "ensure_meta", ensure_meta)
    monkeypatch.setattr(streaming, "_stream_file", lambda *_a: object())
    monkeypatch.setattr(streaming, "wait_for_bytes", wait_for_bytes)
    monkeypatch.setattr(streaming, "CHUNK_SIZE", 512)
    ctx = streaming.StreamContext(download_id=1, path=str(path), file_size=len(real),
                                  complete=False, info_hash="ab" * 20, torrent_id=1)
    assert _collect(ctx, 0, len(real) - 1) == real
    assert [offset // 1024 for offset, _ in asked] == [0, 1, 2, 3]


def test_a_read_past_the_end_gives_up_without_metadata(monkeypatch, tmp_path):
    import dataclasses

    path = tmp_path / "film.mkv"
    path.write_bytes(b"abc")

    async def ensure_meta(*_a):
        return None

    monkeypatch.setattr(streaming, "ensure_meta", ensure_meta)
    monkeypatch.setattr(streaming, "POLL_INTERVAL", 0.01)
    monkeypatch.setattr(streaming, "settings",
                        dataclasses.replace(streaming.settings, stream_wait_timeout_s=0.05))
    ctx = streaming.StreamContext(download_id=1, path=str(path), file_size=10,
                                  complete=False)
    assert _collect(ctx, 0, 9) == b"abc"
