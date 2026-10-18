import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
for candidate in (ROOT, ROOT / ".bootstrap"):
    if candidate.exists() and str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))


@pytest.fixture(autouse=True)
def isolated_reference_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("VOICE_REF_CACHE", str(tmp_path / "reference-cache"))
