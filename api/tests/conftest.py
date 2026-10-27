"""Point the database at a temporary path before any vibestream import creates it."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix="vibestream-tests-")
os.environ.setdefault("VIBESTREAM_DB_PATH", os.path.join(_TMP, "test.db"))
os.environ.setdefault("LIBRARY_MOVIES_DIR", os.path.join(_TMP, "Movies"))
os.environ.setdefault("LIBRARY_SHOWS_DIR", os.path.join(_TMP, "Shows"))

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
