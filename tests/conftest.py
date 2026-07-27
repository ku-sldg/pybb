import json
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def gumbo_l1a_dir() -> Path:
    return FIXTURES / "gumbo_l1a"


@pytest.fixture
def gumbo_l1b_dir() -> Path:
    return FIXTURES / "gumbo_l1b"


@pytest.fixture
def gumbo_l2_dir() -> Path:
    return FIXTURES / "gumbo_l2"

