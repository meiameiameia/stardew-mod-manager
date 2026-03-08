from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def fixtures_root() -> Path:
    return Path(__file__).resolve().parent.parent / "fixtures" / "mods_cases"


@pytest.fixture
def mods_case_path(fixtures_root: Path):
    def _resolve(case_name: str) -> Path:
        return fixtures_root / case_name / "Mods"

    return _resolve
