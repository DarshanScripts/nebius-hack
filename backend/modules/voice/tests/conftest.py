import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
# Prefer the real shared contracts; fall back to the ignored bootstrap copy only if they are absent.
for candidate in (ROOT / ".bootstrap", ROOT) if not (ROOT / "contracts").is_dir() else (ROOT,):
    if candidate.exists() and str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))


@pytest.fixture(autouse=True)
def isolated_reference_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("VOICE_REF_CACHE", str(tmp_path / "reference-cache"))
