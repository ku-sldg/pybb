import json
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def temp_control_aadl_slang_l1a_dir() -> Path:
    return FIXTURES / "temp_control_aadl_slang_l1a"


@pytest.fixture
def temp_control_aadl_slang_l1b_dir() -> Path:
    return FIXTURES / "temp_control_aadl_slang_l1b"


@pytest.fixture
def temp_control_aadl_slang_l2_dir() -> Path:
    return FIXTURES / "temp_control_aadl_slang_l2"

