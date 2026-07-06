import json
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def gumbo_l1_dir() -> Path:
    return FIXTURES / "gumbo_l1"


@pytest.fixture
def gumbo_l2_dir() -> Path:
    return FIXTURES / "gumbo_l2"


@pytest.fixture
def gumbo_l1_request(gumbo_l1_dir) -> dict:
    return json.loads((gumbo_l1_dir / "cvm_request.json").read_text())
