from pathlib import Path

import pytest

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"


@pytest.fixture
def fixture_path():
    def _get(name: str) -> Path:
        return FIXTURES / name

    return _get
