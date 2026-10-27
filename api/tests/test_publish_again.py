from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vibestream.services.library import PublishResult, _link_or_copy  # noqa: E402


def test_every_outcome_is_a_counter_on_the_result(tmp_path):
    src, dst = tmp_path / "a.mkv", tmp_path / "lib" / "a.mkv"
    src.write_bytes(b"x")
    result = PublishResult(path=str(tmp_path))
    for _ in range(2):
        outcome = _link_or_copy(str(src), str(dst))
        setattr(result, outcome, getattr(result, outcome) + 1)
    assert (result.linked, result.existing) == (1, 1)
